"""Live browser GUI: a small local web server inside the seqtool process.

  GET  /?t=TOKEN            the app page
  GET  /api/events?t=TOKEN  Server-Sent Events (push): changed, out, ask, done, busy
  GET  /api/state           song, results folder, seed, cache status, timeline data
  GET  /api/job?id=&from=   a job's output so far (catch-up after a reconnect)
  GET  /audio               the current song (Range requests, so seeking works)
  GET  /api/image?i=N       image N of the face shown with 'face show' (only those files)
  POST /api/cmd             {"line": "..."}           -> {"job": id}   run a seqtool command
  POST /api/answer          {"job": id, "text": "..."}               answer a question
  POST /api/cancel          {"job": id}                              cancel at a question

Everything the server sends goes over one Server-Sent Events stream; everything
the browser sends is a plain POST. Change detection: commands run in this
process notify immediately; changes made by another seqtool process are found
by a light background check of file times (twice a second).

Only 127.0.0.1 is served and every request needs the session token (header
X-Seqtool-Token, or ?t= for the page and the event stream), so other web pages
can't run commands. Commands run one at a time; the GUI console and the
terminal prompt share one lock and say who they are waiting for.
"""
from __future__ import annotations

import io
import json
import mimetypes
import queue
import secrets
import shlex
import sys
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP = Path(__file__).with_name("app.html")
_server = None


# ------------------------------------------------------------ command lock --

# GUI menu: commands that are complete on their own, and common variants of others
# (a line ending in a space is put in the command line to complete; others run)
MENU_RUN = {"doctor", "status", "effects", "presets", "demo", "lyrics", "memory", "pwd", "check", "pause",
            "undo", "redo"}
MENU_EXTRA = {
    "run": [("current song", "run"), ("current song, best of 5 seeds", "run --candidates 5"),
            ("current song, with vocal stems", "run --stems"), ("another song ...", "run --audio "),
            ("every song in the baseline", "run --baseline"), ("a baseline song ...", "run --baseline ")],
    "inspect": [("the song", "inspect audio"), ("where the singing is", "inspect vocals"), ("the layout", "inspect layout"),
                ("xLights training", "inspect xlights")],
    "sections": [("list", "sections"), ("merge ...", "sections merge "), ("split ...", "sections split "),
                 ("move ...", "sections move "), ("set type ...", "sections type "), ("import labels ...", "sections import "),
                 ("snap your boundaries to bars", "sections snap bar"),
                 ("score detection vs your fixes", "sections score"), ("score, per boundary", "sections score --detail"),
                 ("tune detection to your fixes", "sections tune")],
    "pin": [("list pins", "pin"), ("pin ...", "pin ")],
    "unpin": [("remove all pins", "unpin --all"), ("unpin ...", "unpin ")],
    "promote": [("props' effect up to their group ...", "promote ")],
    "demote": [("a group's effect down to what is in it ...", "demote ")],
    "reroll": [("whole song", "reroll"), ("undo the last reroll", "reroll --undo"), ("a prop or section ...", "reroll ")],
    "baseline": [("compare with the baseline", "baseline diff"), ("add the current song", "baseline add"), ("accept the current results", "baseline update"),
                 ("remove a song ...", "baseline remove "), ("list baselines", "baseline")],
    "pref": [("preference files", "pref"), ("what you changed", "pref changed"), ("show or set ...", "pref ")],
    "groups": [("review roles", "groups"), ("list", "groups --list")],
    "rules": [("list", "rules"), ("add ...", "rules add "), ("test a pattern ...", "rules test ")],
    "xlights-kit": [("train or resume", "xlights-kit"), ("learn only new steps", "xlights-kit --update")],
    "xlights-export": [("current song", "xlights-export"), ("verification sequence", "xlights-export --checks")],
    "face": [("faces in the layout", "face list"), ("the face format learned", "face format"),
             ("build from a face image ...", "face build ")],
    "explain": [("a prop ...", "explain "), ("the music at ...", "explain music @")],
    "react": [("set ...", "react "), ("presets", "presets")],
    "layout": [("show the stored layout", "layout"), ("store a show folder (or another one) ...", "layout "),
               ("forget the stored layout", "layout --forget")],
    "tutorial": [("list", "tutorial"), ("basics", "tutorial basics")],
    "lyrics": [("show", "lyrics"), ("transcribe from the singing", "lyrics transcribe"),
               ("transcribe with a larger model ...", "lyrics transcribe --model "), ("Whisper models", "lyrics models"),
               ("align your text ...", "lyrics align "), ("import a file ...", "lyrics import "),
               ("re-time the stored lines", "lyrics align")],
    "play": [("from the play head", "play"), ("pause", "pause"), ("from a section ...", "play #"), ("from the first chorus", "play chorus")],
    "seek": [("to the beginning", "seek 0"), ("back 5 s", "seek -5"), ("forward 5 s", "seek +5"), ("to ...", "seek @")],
    "volume": [("show", "volume"), ("louder", "volume +10"), ("quieter", "volume -10"), ("set ...", "volume ")],
    "speed": [("normal", "speed 1"), ("75%", "speed 0.75"), ("50%", "speed 0.5"), ("set ...", "speed ")],
}

class ExecLock:
    """One command at a time, from the GUI console or the terminal prompt.
    Records who holds it, so the other side can say what it is waiting for."""

    def __init__(self):
        self._lock = threading.RLock()
        self.holder: tuple[str, str] | None = None      # (source, command line)

    def acquire(self, source: str, line: str, on_wait=None):
        if not self._lock.acquire(blocking=False):
            if on_wait and self.holder:
                on_wait(*self.holder)
            self._lock.acquire()
        self.holder = (source, line)

    def release(self):
        self.holder = None
        self._lock.release()

    # plain 'with EXEC_LOCK:' for internal callers
    def __enter__(self):
        self.acquire("internal", "")
        return self

    def __exit__(self, *exc):
        self.release()


EXEC_LOCK = ExecLock()


# ------------------------------------------------------------------- push --
class Hub:
    """Fan-out of events to every connected page (Server-Sent Events)."""

    def __init__(self):
        self.clients: list[queue.Queue] = []
        self.lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def send(self, event: str, data: dict):
        with self.lock:
            for q in self.clients:
                q.put((event, data))


class Job:
    def __init__(self, jid: str, line: str, hub: Hub):
        self.id, self.line, self.hub = jid, line, hub
        self.chunks: list[str] = []
        self.done = False
        self.answer_ev = threading.Event()
        self.answer: str | None = None
        self.question: dict | None = None
        self.cancelled = False

    def write(self, text: str):
        if self.cancelled and not getattr(self, "_stopping", False):   # 0.24.4: stopped at its next output
            self._stopping = True
            from ..common.prompt import Cancelled
            raise Cancelled()
        if text:
            self.chunks.append(text)
            self.hub.send("out", {"job": self.id, "text": text, "n": len(self.chunks) - 1})

    def ask(self, question: str, default: str) -> str:
        """Called (via the prompt module) from the command's thread: send the
        question to the browser and wait for the answer."""
        from ..common.prompt import Cancelled
        from ..common.prompt import answer_kind
        self.question = {"job": self.id, "question": question, "default": default, "complete": answer_kind()}
        self.answer, self.answer_ev = None, threading.Event()
        self.hub.send("ask", self.question)
        self.answer_ev.wait()
        self.question = None
        if self.cancelled:
            self._stopping = True                       # its 'cancelled' line still gets out
            raise Cancelled()
        self.write(f"> {self.answer or default}\n")
        return self.answer or ""


class _ThreadRouter(io.TextIOBase):
    """Stands in for sys.stdout / sys.stderr once the GUI is running: a thread
    running a GUI command writes to its job; every other thread (the terminal
    prompt, the server itself) keeps writing to the real stream. Colour codes
    pass through (the GUI and the terminal stream each render them)."""
    tag_aware = True

    def __init__(self, real):
        self.real = real
        self.local = threading.local()

    def _target(self):
        return getattr(self.local, "target", None) or self.real

    def write(self, s):
        return self._target().write(s)

    def flush(self):
        try:
            self._target().flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self):
        return self._target().isatty()

    @property
    def handles_cr(self):
        return getattr(self._target(), "handles_cr", False)

    def fileno(self):
        return self.real.fileno()

    @property
    def encoding(self):
        return getattr(self.real, "encoding", "utf-8")

    @property
    def errors(self):                      # input() checks these before it will use readline
        return getattr(self.real, "errors", "strict")

    @property
    def buffer(self):
        return self.real.buffer

    @property
    def line_buffering(self):
        return getattr(self.real, "line_buffering", True)


def _install_routers() -> tuple[_ThreadRouter, _ThreadRouter]:
    import sys
    if not isinstance(sys.stdout, _ThreadRouter):
        sys.stdout = _ThreadRouter(sys.stdout)
    if not isinstance(sys.stderr, _ThreadRouter):
        sys.stderr = _ThreadRouter(sys.stderr)
    return sys.stdout, sys.stderr


# commands the GUI runs as they are (no '--later'): they make or need the plan themselves
SYNC_IN_GUI = {"run", "demo", "gui", "batch", "undo", "redo", "test", "clear", "package", "xlights-kit", "replan", "start",
               "xlights-export", "bundle"}


def _in_child(job, argv: list[str]) -> int:
    """A long command in a process of its own, at a lower priority (0.24.39): the GUI's own
    work - the page, the song it plays - isn't held up by it. Its output goes to the job with its
    colour codes (SEQTOOL_TAGS=1)."""
    import os
    import subprocess
    import seqtool
    from ..common import config
    env = {**os.environ, "SEQTOOL_NONINTERACTIVE": "1", "SEQTOOL_TAGS": "1", "SEQTOOL_PREFS": str(config.user_dir()),
           "PYTHONPATH": os.pathsep.join([str(Path(seqtool.__file__).resolve().parent.parent)]
                                         + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}
    kw = {"preexec_fn": lambda: os.nice(10)} if hasattr(os, "nice") else {}
    p = subprocess.Popen([sys.executable, "-m", "seqtool", "--stale=rebuild", *argv], cwd=os.getcwd(), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", bufsize=1, **kw)
    for line in p.stdout:
        if not line.startswith("seqtool 0."):          # its version line
            job.write(line)
    return p.wait()


class _Writer(io.TextIOBase):
    tag_aware = True                    # the GUI renders colour codes
    handles_cr = True                   # 0.24.32: a progress line ('\r') is rewritten in the console

    def __init__(self, job: Job):
        self.job = job

    def write(self, s):
        from ..common.color import mark_commands
        self.job.write(mark_commands(s.replace("\x1b[K", "")))
        return len(s)

    def isatty(self):
        return False


def fingerprint() -> str:
    """Changes whenever anything the GUI shows could have changed: which song is
    current, and the times of all its result files (pipeline folder and
    single-stage files beside the song)."""
    from ..common import config, current
    parts = [str(config.answer(k)) for k in ("last_audio", "last_out", "last_matchup", "last_music")]
    for f in current.files():
        try:
            parts.append(f"{f}:{f.stat().st_mtime_ns}")
        except OSError:
            pass
    for f in (config.user_dir() / "songs.json", config.user_dir() / "layout" / "source.json"):
        if f.exists():
            parts.append(f"{f.name}:{f.stat().st_mtime_ns}")
    return str(hash(tuple(parts)))


def cached_peaks(audio: Path) -> dict:
    from ..demo.view import cached_peaks as _cp
    return _cp(audio)


class Server:
    def vocal_edges(self) -> dict:
        """Rising / falling edges of the current song's singing (music/edges.py), kept per stem file."""
        from ..common import current
        from ..music.edges import vocal_edges
        from ..music.stems import stem_path
        song = current.song()
        if not song or not song.get("audio") or not Path(song["audio"]).exists():
            return {"rise": [], "fall": [], "error": "no song"}
        f = Path(song["audio"])
        st = stem_path(f)
        src = st if st.is_file() else f
        key = ("edges", str(src), src.stat().st_mtime_ns)
        if key not in self._peaks_cache:
            self._peaks_cache[key] = vocal_edges(f)
        return self._peaks_cache[key]

    def peaks_span(self, t0: float, t1: float, n: int, src: str = "mix") -> dict:
        """Max |amplitude| per bucket between t0 and t1, from a fine envelope of the current
        song (200 per second, made once per song and kept). src 'vocals' (0.24.6): the vocal
        stem's, when there is one (the answer says which was used)."""
        from ..common import current
        from ..demo.view import peaks_timed
        song = current.song()
        if not song or not song.get("audio") or not Path(song["audio"]).exists():
            return {"peaks": [], "error": "no song"}
        f, used = Path(song["audio"]), "mix"
        if src == "vocals":
            from ..music.stems import stem_path
            st = stem_path(f)
            if st.is_file():
                f, used = st, "vocals"
        key = ("fine", str(f))
        if key not in self._peaks_cache:
            from ..music import decode
            dur = decode.probe(f)["duration"]
            step, P = peaks_timed(f, buckets=max(1000, int(dur * 200)))
            self._peaks_cache[key] = (step, P)
        step, P = self._peaks_cache[key]
        per = 1.0 / step                                  # buckets per second, as decoded (0.24.19)
        a, b = max(0, int(t0 * per)), min(len(P), int(t1 * per) + 1)
        seg = P[a:b]
        n = max(10, min(4000, n))
        if len(seg) > n:
            k = len(seg) / n
            seg = [max(seg[int(i * k):max(int(i * k) + 1, int((i + 1) * k))]) for i in range(n)]
        return {"from": a / per, "to": b / per, "peaks": seg, "src": used}

    def __init__(self, port: int | None = None):
        from ..__main__ import discover
        self.token = secrets.token_urlsafe(12)
        self.hub = Hub()
        from ..common import current as _cur, history as _hs
        if not _hs._STARTED:                          # the GUI on its own: a session of its own
            _cur.follow_song()
        _hs.session_start("gui")
        from ..common import update as _up
        _up.at_start("gui")                                      # 0.24.56: says so; 'update' gets it
        self.jobs: dict[str, Job] = {}
        self.cmds = discover()
        self.version, self._fp = 0, fingerprint()
        self.last_tb = None
        self._peaks_cache: dict = {}
        self._stop = threading.Event()
        try:                                          # 0.24.37: the session's start commands run in the GUI
            from ..common import start_cmd             # console (the first page asks for them)
            self.start_pending = bool(start_cmd.commands())
        except Exception:  # noqa: BLE001
            self.start_pending = False
        self.player_state: dict = {}           # the page's player: t, playing, volume, rate
        self.httpd = None
        for p in ([port] if port else range(8765, 8800)):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", p), self._handler())
                break
            except OSError:
                continue
        if self.httpd is None:
            raise SystemExit("could not open a local port for the GUI")
        self.httpd.daemon_threads = True

        def handle_error(request, client_address, _orig=self.httpd.handle_error):
            import sys as _sys
            if isinstance(_sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
                return                                  # the browser closed a connection: normal, not an error
            _orig(request, client_address)
        self.httpd.handle_error = handle_error
        self.routers = _install_routers()
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def stop(self):
        self._stop.set()
        self.hub.send("bye", {})
        self.httpd.shutdown()
        self.httpd.server_close()

    # ---------------------------------------------------------- changes
    def check_now(self) -> bool:
        """Compare the fingerprint; push 'changed' if it moved. Cheap."""
        fp = fingerprint()
        if fp != self._fp:
            self._fp = fp
            self.version += 1
            self.hub.send("changed", {"v": self.version})
            return True
        return False

    def _watch(self):
        """Finds changes made outside this process (another seqtool, an editor), and cancels
        the GUI's command when every page is gone (0.24.4)."""
        while not self._stop.wait(0.5):
            try:
                self.check_now()
                self._orphans()
            except Exception:  # noqa: BLE001 - never let the watcher die
                pass

    GONE_AFTER = 3.0                                     # s without a page (a reload reconnects sooner)

    def _orphans(self):
        """The GUI's page closed while its command runs or asks something: cancel it, so the
        terminal isn't left 'waiting for the GUI command ... to finish'. One that asks stops at
        once; one that works stops at its next line of output."""
        if self.hub.clients:
            self._gone = None
            return
        now = time.monotonic()
        self._gone = getattr(self, "_gone", None) or now
        if now - self._gone < self.GONE_AFTER:
            return
        for j in list(self.jobs.values()):
            if j.done or j.cancelled:
                continue
            j.cancelled = True
            if j.question is not None:
                j.answer = ""
                j.answer_ev.set()
            try:
                (sys.__stderr__ or sys.stderr).write(f"\n(the GUI page was closed: its command '{j.line}' is cancelled)\n")
            except Exception:  # noqa: BLE001
                pass

    def state(self) -> dict:
        from .. import __version__
        from ..common import config, songs
        from ..common.paths import show
        st = {"version": __version__, "v": self.version, "song": None, "results": None,
              "cache": [], "timeline": None, "message": None,
              "replan_after": float(config.load("general").get("replan_after", 3))}
        from ..common import current
        cur = current.song()
        if cur:
            st["song"] = {"name": cur["audio"].name, "path": show(cur["audio"]), "exists": cur["audio"].exists()}
            st["results"] = show(cur["folder"])
            try:
                from ..common.status import current_rows
                st["cache"] = [{"file": n, "ok": not why, "why": "; ".join(why)} for n, why in current_rows()]
            except Exception as e:  # noqa: BLE001
                st["cache"] = [{"file": "?", "ok": False, "why": str(e)}]
        try:
            from ..demo.run import section_matches
            from ..demo.view import current_results, peaks, timeline_data
            out_d, stem, audio, music, profile, matchup = current_results()
            data = timeline_data(stem, music, profile, matchup,
                                 section_matches(profile, matchup) if matchup else {}, folder=out_d)
            cp = cached_peaks(audio)
            data["peaks"], data["peaks_step"] = cp["peaks"], cp["step"]
            st["timeline"] = data
            sha = music.get("lineage", {}).get("audio")
            if sha:
                st["seed"] = songs.seed(sha)
                st["seed_overrides"] = songs.seed_overrides(sha)
            if st["song"] is None:
                st["song"] = {"name": audio.name, "path": show(audio), "exists": audio.exists()}
        except SystemExit as e:
            st["message"] = str(e.code)
        except Exception as e:  # noqa: BLE001
            st["message"] = f"{e.__class__.__name__}: {e}"
        busy = EXEC_LOCK.holder
        st["busy"] = {"source": busy[0], "line": busy[1]} if busy else None
        st["questions"] = [j.question for j in self.jobs.values() if j.question]
        return st

    def audio_path(self) -> Path | None:
        """What the page plays: the song, or for a compressed file (MP3 ...) a WAV copy of it in the
        results folder (0.24.19) - browsers place a seek in an MP3 by estimate, so after a click
        or a jump late in the song the sound can be a fraction of a second off what is shown;
        in a WAV every position is exact."""
        from ..common import current
        s = current.song()
        if not s:
            return None
        a = Path(s["audio"])
        if a.suffix.lower() in (".wav", ".wave") or not a.exists():
            return a
        try:
            return play_copy(a, Path(s.get("folder") or a.parent))
        except Exception:  # noqa: BLE001 - the song as it is, then
            return a

    # --------------------------------------------------------- commands
    def run_line(self, line: str) -> str:
        if line.strip().split()[:1] == ["start"]:
            self.start_pending = False
        jid = secrets.token_hex(4)
        job = Job(jid, line, self.hub)
        self.jobs[jid] = job
        if len(self.jobs) > 50:                               # keep memory bounded
            for k in [k for k, j in self.jobs.items() if j.done][:-20]:
                self.jobs.pop(k, None)
        threading.Thread(target=self._execute, args=(job,), daemon=True).start()
        return jid

    def _execute(self, job: Job):
        from ..__main__ import _expand, dispatch
        from ..common import prompt
        from ..common.args import split_line
        w = _Writer(job)

        def waiting(source, line):
            job.write(f"(waiting for the {source} command '{line}' to finish ...)\n")
        EXEC_LOCK.acquire("GUI", job.line, waiting)
        self.hub.send("busy", {"source": "GUI", "line": job.line})
        r_out, r_err = self.routers
        r_out.local.target = r_err.local.target = w           # only this thread's output goes to the job
        try:
            if True:
                prompt.set_gui_asker(job.ask)
                try:
                    cmd = job.line.strip()
                    from ..common import history
                    if cmd.startswith("!"):                  # !! / !N / !TEXT (0.19.6)
                        got = history.expand(cmd)
                        if got is None:
                            raise SystemExit(f"no command {cmd} in the history - 'history' lists them")
                        print(got)
                        cmd = job.line = got
                    if not cmd.startswith("history"):
                        history.add(cmd)
                    if cmd == "trace":
                        print(self.last_tb or "no error so far")
                    elif cmd in ("quit", "exit", "q", "bye"):
                        print("the GUI keeps running while seqtool does; close this tab when you're done")
                    elif split_line(cmd)[:1] == ["replan"]:
                        _in_child(job, split_line(cmd))    # 0.24.39: the page (and its sound) stay responsive
                    else:
                        argv = _expand(split_line(job.line))
                        if argv and argv[0] in self.cmds and argv[0] not in SYNC_IN_GUI:
                            from .. import __main__ as _m      # 0.24.40: every GUI change: the setting now, the
                            _m.LATER[0] = "gui"                # plan a little later (the page asks for it)
                        dispatch(argv, self.cmds)
                except prompt.Cancelled:
                    print("cancelled")
                except SystemExit as e:
                    if e.code not in (0, None) and not isinstance(e.code, int):
                        print(e.code)
                except Exception as e:  # noqa: BLE001
                    self.last_tb = traceback.format_exc()
                    print(f"error: {e.__class__.__name__}: {e}   ('trace' shows details)")
                finally:
                    prompt.set_gui_asker(None)
                    from ..common import current as _cur
                    _cur.after_command()             # a new current song: its folder (0.21.4)
        finally:
            r_out.local.target = r_err.local.target = None
            EXEC_LOCK.release()
            job.done = True
            from ..common import config as _cfg
            self.hub.send("done", {"job": job.id, "pending": bool(_cfg.answer("replan_pending"))})
            self.hub.send("busy", {})
            self.check_now()

    # ------------------------------------------------------------- help
    def help_tree(self) -> list[dict]:
        """Sections of the GUI help: the overview, each help topic with its commands,
        effect types and reaction presets."""
        from ..__main__ import BUILTINS, TOPICS
        from ..common import config
        cmds = self.cmds
        out = [{"title": "Overview", "items": [{"kind": "usage", "name": "seqtool", "summary": "what seqtool does, the pipeline"}]}]

        def rows(secs):
            r = [{"kind": "cmd", "name": n, "summary": c[3]} for n, c in cmds.items() if c[2] in secs]
            r += [{"kind": "builtin", "name": n, "summary": h} for n, (sec, h) in BUILTINS.items() if sec in secs]
            return sorted(r, key=lambda x: x["name"])
        out.append({"title": "Pipeline", "items": rows(["pipeline"])})
        for t, (title, secs) in TOPICS.items():
            out.append({"title": title, "items": rows(secs)})
        try:
            effs = config.load("effects")["effects"]
            out.append({"title": "Effect types", "items": [{"kind": "effect", "name": k, "summary": e.get("help", "")}
                                                           for k, e in effs.items()]})
            from ..matchup.reactive import load_presets
            out.append({"title": "Reaction presets (react)", "items": [
                {"kind": "preset", "name": k, "summary": p.get("help", "")} for k, p in load_presets().items()]})
        except Exception:  # noqa: BLE001
            pass
        return out

    def menu_tree(self) -> list[dict]:
        """The GUI menu: one menu per command section, one entry per command; common
        variants as a submenu. An entry 'run's a complete command line, or 'fill's the
        command line with a start to complete (args to add)."""
        from ..__main__ import TOPICS
        menus = [("Pipeline", ["pipeline"])] + [(t.split(" (")[0], secs) for t, secs in TOPICS.values()]
        out = []
        for title, secs in menus:
            items = []
            for name in sorted(n for n, c in self.cmds.items() if c[2] in secs):
                if name == "gui":
                    continue
                extra = MENU_EXTRA.get(name)
                if extra:
                    sub = [{"label": lab, "line": ln, "run": not ln.endswith(" ")} for lab, ln in extra]
                    items.append({"label": name, "help": self.cmds[name][3], "sub": sub})
                else:
                    runs = name in MENU_RUN
                    items.append({"label": name + ("" if runs else " ..."), "help": self.cmds[name][3],
                                  "line": name if runs else name + " ", "run": runs})
            if items:
                out.append({"label": title, "items": items})
        out.append({"label": "Help", "items": [{"label": "Help window", "help": "commands, effect types, presets",
                                                "action": "help"},
                                               {"label": "tutorial ...", "help": "guided walk-throughs",
                                                "line": "tutorial ", "run": False}]})
        return out

    def help_text(self, kind: str, name: str) -> str:
        from ..__main__ import TOPICS, dispatch, usage
        if kind == "usage":
            return usage(self.cmds)
        if kind == "topic" and name in TOPICS:
            return usage(self.cmds, name)
        if kind == "effect":
            from ..matchup.catalog import effects_text
            return effects_text(name)
        if kind == "preset":
            from ..matchup.catalog import presets_text
            return presets_text(name)
        if kind == "builtin":
            from ..__main__ import BUILTINS
            return f"{name}: {BUILTINS.get(name, ('', ''))[1]}"
        if name in ("effects", "presets"):                   # their listing is the help
            from ..matchup import catalog
            return (catalog.effects_text() if name == "effects" else catalog.presets_text() + "\n\n" + catalog.HOWTO)
        if name not in self.cmds:
            return f"no command '{name}'"
        buf = io.StringIO()
        r_out, r_err = self.routers
        r_out.local.target = r_err.local.target = buf     # this request thread only
        try:
            dispatch([name, "-h"], self.cmds)
        except SystemExit:
            pass
        except Exception as e:  # noqa: BLE001
            buf.write(f"(no help: {e})")
        finally:
            r_out.local.target = r_err.local.target = None
        return buf.getvalue().strip()

    def explain_at(self, target: str, t: float) -> str:
        from ..matchup.explain import find_matchup, run
        path = find_matchup(None)
        if path is None:
            return "no plan yet"
        try:
            return f"$ seqtool explain {target} @{t:.1f}\n" + run(target, f"@{t:.2f}", path)
        except SystemExit as e:
            return str(e.code)

    def about(self, target: str) -> str:
        """explain TARGET without a time, for the GUI's name column."""
        from ..matchup.cli import explain_context
        from ..matchup.explain import find_matchup, overview
        from ..common.canonical import read_json
        path = find_matchup(None)
        if path is None:
            return "no plan yet"
        try:
            return overview(read_json(path), target, explain_context(path))
        except SystemExit as e:
            return str(e.code)

    # ------------------------------------------------------------- HTTP
    def _handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):          # keep the terminal quiet
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self, q) -> bool:
                tok = self.headers.get("X-Seqtool-Token") or (q.get("t") or [""])[0]
                if not secrets.compare_digest(tok, srv.token):
                    self._json({"error": "forbidden"}, 403)
                    return False
                return True

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if not self._authorised(q):
                    return
                if u.path == "/":
                    from .icons import head_links
                    body = APP.read_text(encoding="utf-8").replace("__TOKEN__", srv.token).replace(
                        "/*__THUMBS__*/", APP.with_name("thumbs.js").read_text(encoding="utf-8")).replace(
                        "<!--__ICONS__-->", head_links()).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/events":
                    self._events()
                elif u.path == "/api/state":
                    self._json(srv.state())
                elif u.path == "/api/job":
                    j = srv.jobs.get(q.get("id", [""])[0])
                    if j is None:
                        return self._json({"error": "no such job"}, 404)
                    start = int(q.get("from", ["0"])[0])
                    self._json({"chunks": j.chunks[start:], "from": start, "next": len(j.chunks),
                                "text": "".join(j.chunks[start:]), "done": j.done, "question": j.question})
                elif u.path == "/api/help":
                    if "name" in q:
                        from ..common.color import mark_commands
                        self._json({"text": mark_commands(srv.help_text(q.get("kind", ["cmd"])[0], q["name"][0]))})
                    else:
                        self._json({"tree": srv.help_tree()})
                elif u.path == "/api/history":           # the shared command history (0.19.6)
                    from ..common import history
                    self._json({"lines": history.lines()[-200:]})
                elif u.path == "/api/complete":          # completion for the console (0.19.5)
                    from ..common.complete import complete, complete_answer
                    try:
                        if q.get("kind"):                # an answer to a question (0.24.3)
                            self._json(complete_answer(q.get("line", [""])[0], q["kind"][0]))
                        else:
                            self._json(complete(q.get("line", [""])[0]))
                    except Exception as e:  # noqa: BLE001
                        self._json({"start": 0, "word": "", "items": [], "error": str(e)})
                elif u.path == "/api/menu":
                    self._json({"menu": srv.menu_tree()})
                elif u.path == "/api/explain":
                    from ..common.color import mark_commands
                    self._json({"text": mark_commands(srv.explain_at(q.get("target", [""])[0],
                                                                     float(q.get("t", ["0"])[0])))})
                elif u.path == "/api/place":           # promote / demote choices for the effect menu (0.21)
                    from ..matchup.place_cmd import options
                    try:
                        self._json(options([x for x in q.get("ids", [""])[0].split("\n") if x]))
                    except SystemExit as e:
                        self._json({"up": [], "down": [], "error": str(e)})
                elif u.path == "/api/steps":           # the step bar (0.21.7)
                    from . import steps
                    try:
                        self._json(steps.state())
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e)})
                elif u.path == "/api/feel":            # the feel panel (0.24.30)
                    try:
                        from ..demo.view import current_results
                        from ..matchup import feel as _F
                        from ..matchup.feel_cmd import show as _fshow
                        from ..common import songs
                        _, _, _, music, profile, m = current_results()
                        sha = (music.get("lineage") or {}).get("audio")
                        fe = songs.get(sha).get("feel") if sha else None
                        self._json({"values": {n: _F.song_value(fe, n) for n in _F.NAMES}, "about": _F.ABOUT,
                                    "per_section": list(_F.PER_SECTION),
                                    "sections": [ln.strip() for ln in _fshow(fe, profile)[len(_F.NAMES):]]})
                    except SystemExit as e:
                        self._json({"error": str(e.code)})
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e)})
                elif u.path == "/api/palette":         # the palette panel (0.24.25)
                    try:
                        from ..demo.view import current_results
                        from ..matchup.palette_cmd import info_for
                        _, _, _, music, profile, m = current_results()
                        self._json(info_for(m, profile, (music.get("lineage") or {}).get("audio")))
                    except SystemExit as e:
                        self._json({"error": str(e.code)})
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e)})
                elif u.path == "/api/layout-tree":     # the layout panel (0.21.8)
                    from . import steps
                    try:
                        self._json(steps.layout_tree())
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e)})
                elif u.path == "/api/prefs":           # the preferences window (0.21.9)
                    from . import steps
                    try:
                        self._json(steps.prefs_tree(q.get("file", [""])[0] or None))
                    except (Exception, SystemExit) as e:  # noqa: BLE001
                        self._json({"error": str(e)})
                elif u.path == "/api/edges":           # where the singing starts / stops (0.24.8): magnifier snapping
                    try:
                        self._json(srv.vocal_edges())
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e), "rise": [], "fall": []})
                elif u.path == "/api/peaks":           # the magnifier's waveform (0.21.9): a span in detail
                    try:
                        self._json(srv.peaks_span(float(q.get("from", ["0"])[0]), float(q.get("to", ["10"])[0]),
                                                  int(q.get("n", ["800"])[0]), q.get("src", ["mix"])[0]))
                    except Exception as e:  # noqa: BLE001
                        self._json({"error": str(e), "peaks": []})
                elif u.path == "/api/browse":          # the file picker: seqtool lists the folders
                    from . import steps
                    self._json(steps.browse(q.get("dir", [""])[0] or None, q.get("kind", ["any"])[0]))
                elif u.path == "/api/about":
                    from ..common.color import mark_commands
                    self._json({"text": mark_commands(srv.about(q.get("target", [""])[0]))})
                elif u.path == "/audio":
                    self._audio()
                elif u.path == "/api/image":           # only the images 'face show' listed (0.19.2)
                    try:
                        f = Path(srv.images[int(q.get("i", ["-1"])[0])])
                    except (ValueError, IndexError, AttributeError):
                        return self._json({"error": "no such image"}, 404)
                    if not f.exists():
                        return self._json({"error": "missing"}, 404)
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                u = urlparse(self.path)
                if not self._authorised({}):
                    return
                if u.path == "/api/upload":            # a file dropped on the page (0.21.7)
                    from urllib.parse import parse_qs as _pq
                    from . import steps
                    n = int(self.headers.get("Content-Length", "0") or 0)
                    if n <= 0 or n > 2 * 1024 ** 3:
                        return self._json({"error": "nothing to keep (or over 2 GB)"}, 400)
                    name = (_pq(u.query).get("name") or ["upload"])[0]
                    f = steps.save_upload(name, self.rfile.read(n))
                    return self._json({"path": str(f), "kind": steps.kind_of(f.name)})
                body = self._body()
                if u.path == "/api/cmd":
                    self._json({"job": srv.run_line(body.get("line", ""))})
                elif u.path == "/api/player":          # the page reports its player state
                    srv.player_state = {k: body[k] for k in ("t", "playing", "volume", "rate") if k in body}
                    self._json({"ok": True})
                elif u.path in ("/api/answer", "/api/cancel"):
                    j = srv.jobs.get(body.get("job", ""))
                    if j is None or j.question is None:
                        return self._json({"error": "no question pending"}, 409)
                    if u.path == "/api/cancel":
                        j.cancelled = True
                    j.answer = str(body.get("text", ""))
                    j.answer_ev.set()
                    self._json({"ok": True})
                elif u.path == "/api/face-marks":      # the face viewer's marked pixels (0.20.7)
                    from ..faces.cmd import save_marks
                    r = save_marks(list(getattr(srv, "images", None) or []), str(body.get("name", "")),
                                   body.get("marks") or {})
                    self._json(r, 400 if r.get("error") else 200)
                elif u.path == "/api/face-recolor":    # the face viewer's colour touch-up (0.20.5)
                    import re as _re
                    a_, b_ = str(body.get("from", "")), str(body.get("to", ""))
                    imgs = list(getattr(srv, "images", None) or [])
                    if not imgs or not all(_re.fullmatch(r"#?[0-9a-fA-F]{6}", c) for c in (a_, b_)):
                        return self._json({"error": "needs from/to colours (#RRGGBB) and a face shown "
                                                    "('face show NAME')"}, 400)
                    from ..faces.cmd import touch_up
                    try:
                        i = int(body["index"]) if body.get("index") is not None else None
                    except (TypeError, ValueError):
                        i = None
                    self._json(touch_up(imgs, "#" + a_.lstrip("#"), "#" + b_.lstrip("#"),
                                        "this" if body.get("scope") == "this" else "all", i))
                else:
                    self._json({"error": "not found"}, 404)

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = srv.hub.subscribe()
                try:
                    self.wfile.write(f"event: hello\ndata: {json.dumps({'v': srv.version, 'start': srv.start_pending})}\n\n".encode())
                    self.wfile.flush()
                    while not srv._stop.is_set():
                        try:
                            event, data = q.get(timeout=2)     # 0.24.4: 2 s, so a closed page is noticed soon
                        except queue.Empty:
                            # keeps the connection alive; the page also uses it to re-check a running command
                            self.wfile.write(b"event: tick\ndata: {}\n\n")
                            self.wfile.flush()
                            continue
                        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                        self.wfile.flush()
                        if event == "bye":
                            break
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    srv.hub.unsubscribe(q)
                    self.close_connection = True

            def _audio(self):
                p = srv.audio_path()
                if p is None or not p.exists():
                    return self._json({"error": "no audio"}, 404)
                size = p.stat().st_size
                start, end = 0, size - 1
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    start = int(a) if a else 0
                    end = min(int(b) if b else size - 1, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                with open(p, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    try:
                        while left > 0:
                            chunk = f.read(min(1 << 16, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
        return H


_PLAY_LOCK = threading.Lock()


def play_copy(audio: Path, folder: Path) -> Path:
    """<results>/<song>.play.wav, made once (again when the song changes) with ffmpeg; the song
    itself when ffmpeg isn't there."""
    from ..common.deps import need_exe
    out = folder / f"{audio.stem}.play.wav"
    with _PLAY_LOCK:
        if out.exists() and out.stat().st_mtime >= audio.stat().st_mtime and out.stat().st_size > 44:
            return out
        ffmpeg = need_exe("ffmpeg", purpose="a WAV copy of the song for exact positions in the GUI")
        if not ffmpeg:
            return audio
        folder.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.wav")
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(audio), "-vn", "-acodec", "pcm_s16le", str(tmp)],
                       check=True, timeout=300)
        tmp.replace(out)
    return out


def ensure_running(port: int | None = None) -> str:
    global _server
    if _server is None:
        _server = Server(port)
    return _server.url


def running() -> Server | None:
    return _server


def stop() -> None:
    global _server
    if _server is not None:
        _server.stop()
        _server = None
