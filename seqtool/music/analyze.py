# seqtool-command: analyze-music | main | stages | audio file -> music.json
# seqtool-inspect: audio | inspect_audio | a song file and its analysis: inspect audio [file] (default: last song)
"""Music analyzer: audio file -> seqtool.music (measurements only).

Two resolutions:
  fine   : 10 ms hop, used internally for onset/beat tracking
  frames : frame_interval (preferences/music.json, default 0.05 s; any multiple
           of 10 ms), written to music.json (columnar). Nothing downstream
           assumes a particular value - consumers read frame_interval.
Feature extraction streams the audio in chunks; tempo, beats and boundaries
then run on compact whole-song arrays (a 4-minute song is ~100 KB of onset
envelope), which is the 'whole-stream data' allowance.

Field naming: *_norm = normalised within this song (0..1, 5th..95th percentile);
*_dbfs / *_hz = absolute measurements.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from ..common.canonical import file_sha256, write_json
from ..common.envelope import envelope
from ..common.log import elapsed, good, info, warn
from ..common.schemas import validate
from . import decode, rhythm, segment
from ..common.paths import arg as paths_arg

SR = decode.SR
HOP = 240                     # 10 ms fine hop
FINE_S = HOP / SR
NFFT = 1024
DEFAULT_FRAME_INTERVAL = 0.05
NBANDS = 24
EDGES_HZ = np.geomspace(40, 11000, NBANDS + 1)


def _chroma_matrix() -> np.ndarray:
    """FFT bin -> pitch class (C=0 ... B=11), 60 Hz - 5 kHz."""
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    M = np.zeros((12, len(f)))
    ok = (f >= 60) & (f <= 5000)
    pc = (np.round(12 * np.log2(f[ok] / 440.0)).astype(int) + 9) % 12
    M[pc, np.where(ok)[0]] = 1.0
    return M


def _band_matrix() -> np.ndarray:
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    M = np.zeros((NBANDS, len(f)))
    for b in range(NBANDS):
        M[b] = (f >= EDGES_HZ[b]) & (f < EDGES_HZ[b + 1])
    return M


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / (hi - lo), 0, 1) if hi > lo else np.zeros_like(x)


def extract(path: Path) -> dict:
    """Stream the file once; return fine-resolution arrays."""
    win = np.hanning(NFFT).astype(np.float32)
    M = _band_matrix()
    CM = _chroma_matrix()
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    bands, cent, rms, flux, low_flux, chroma = [], [], [], [], [], []
    buf = np.zeros(NFFT // 2, dtype=np.float32)        # centre the first window
    prev = None
    for chunk in decode.chunks(path):
        buf = np.concatenate([buf, chunk])
        n = (len(buf) - NFFT) // HOP + 1
        if n <= 0:
            continue
        idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
        fr = buf[idx] * win
        P = np.abs(np.fft.rfft(fr, axis=1)) ** 2
        B = P @ M.T + 1e-10
        logB = np.log10(B)
        bands.append(B)
        chroma.append(P @ CM.T)
        cent.append((P * freqs).sum(axis=1) / (P.sum(axis=1) + 1e-10))
        core = buf[idx[:, NFFT // 2 - HOP // 2: NFFT // 2 + HOP // 2]]
        rms.append(np.sqrt((core ** 2).mean(axis=1)))
        d = np.diff(np.vstack([logB[:1] if prev is None else prev, logB]), axis=0)
        flux.append(np.maximum(d, 0).sum(axis=1))
        low_flux.append(np.maximum(d[:, :6], 0).sum(axis=1))
        prev = logB[-1:]
        buf = buf[n * HOP:]
    if not bands:
        raise ValueError(f"no audio decoded from {path}")
    return {"bands": np.vstack(bands), "chroma": np.vstack(chroma), "centroid": np.concatenate(cent),
            "rms": np.concatenate(rms), "flux": np.concatenate(flux),
            "low_flux": np.concatenate(low_flux)}


def per_frame(frame_interval: float) -> int:
    k = int(round(frame_interval / FINE_S))
    if k < 1 or abs(k * FINE_S - frame_interval) > 1e-6:
        raise ValueError(f"frame_interval {frame_interval} must be a positive multiple of {FINE_S} s")
    return k


def _pool(x: np.ndarray, k: int, how: str = "mean") -> np.ndarray:
    n = len(x) // k
    y = x[: n * k].reshape(n, k, *x.shape[1:])
    return y.max(axis=1) if how == "max" else y.mean(axis=1)


def _stem_rms_frames(stem: Path, n_frames: int, k: int) -> np.ndarray:
    """Per-frame RMS of the stem, streamed (no whole-file buffer)."""
    step = HOP * k
    out, carry = [], np.zeros(0, dtype=np.float32)
    for chunk in decode.chunks(stem):
        carry = np.concatenate([carry, chunk])
        m = len(carry) // step
        if m:
            out.append(np.sqrt((carry[: m * step].reshape(m, step) ** 2).mean(axis=1)))
            carry = carry[m * step:]
    r = np.concatenate(out)[:n_frames] if out else np.zeros(0)
    return np.pad(r, (0, n_frames - len(r)))


def _stem_parts(got: dict, fields: dict, n: int, k: int, frame_interval: float, rms_db: np.ndarray):
    """Drum, bass and other levels, drum hits, bass notes and the melody (stem_features.py)."""
    from . import stem_features as sf
    from .stems import stem_record
    summary, events = {}, {}
    names = {"drums": "drums", "bass": "bassline", "other": "other"}
    for stem, field in names.items():
        f = got.get(stem)
        if f is None:
            continue
        info(f"  {stem} stem: level{', hits' if stem == 'drums' else ', notes' if stem == 'bass' else ''} ...")
        db = 20 * np.log10(_stem_rms_frames(f, n, k) + 1e-9)
        fields[f"{field}_dbfs"] = db
        fields[field] = np.clip((db - (rms_db - 18)) / 18, 0, 1)
        rec = {**stem_record(f), "mean": float(fields[field].mean()),
               "active_fraction": float((fields[field] > 0.4).mean())}
        if stem in ("drums", "bass"):
            feat = extract(f)
            if stem == "drums":
                hits = sf.drum_hits(feat, EDGES_HZ, 1 / FINE_S)
                events.update(hits)
                rec.update({f"{h}_count": len(v) for h, v in hits.items()})
            else:
                events["bass"] = sf.bass_notes(sf.read_samples(f), feat, SR, HOP, 1 / FINE_S)
                rec["note_count"] = len(events["bass"])
        summary[stem] = rec
        info(f"    done, {elapsed()}")
    if "vocals" in got:
        summary["vocals"] = stem_record(got["vocals"])
    n_fine = n * k
    act = None
    if "vocal" in fields:
        act = np.repeat(fields["vocal"] > 0.5, k)
    mel = sf.melody(got.get("vocals"), got.get("other"), act, SR, HOP, n_fine)
    if mel:
        midi = mel["midi"][: n * k].reshape(n, k)
        voiced = np.isfinite(midi)
        vf = voiced.mean(axis=1)
        import warnings
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)          # frames with no pitch at all
            mf = np.where(vf > 0, np.nanmedian(np.where(voiced, midi, np.nan), axis=1), np.nan)
        hz = np.where(np.isfinite(mf), 440 * 2 ** ((mf - 69) / 12), 0.0)
        fields["melody_hz"] = hz
        fields["melody_voiced"] = vf
        if mel["range"]:
            lo, hi = mel["range"]
            fields["melody_norm"] = sf.hold(np.clip((mf - lo) / max(hi - lo, 1.0), 0, 1))
        events["melody"] = mel["notes"]
        src = mel["source"][mel["voiced"]]
        summary["melody"] = {"notes": len(mel["notes"]), "voiced_fraction": float(mel["voiced"].mean()),
                             "range": [sf.note_name(mel["range"][0]), sf.note_name(mel["range"][1])]
                             if mel["range"] else None,
                             "from_vocals": float((src == "vocals").mean()) if len(src) else 0.0}
        info(f"  melody: {len(mel['notes'])} notes"
             + (f", {summary['melody']['range'][0]}-{summary['melody']['range'][1]}" if mel["range"] else "")
             + f", {elapsed()}")
    return summary, events


def analyze(path: Path, use_stems: bool = False, frame_interval: float = DEFAULT_FRAME_INTERVAL) -> dict:
    k = per_frame(frame_interval)
    meta = decode.probe(path)
    info(f"analyzing {path.name}  ({meta['duration']:.1f} s)")
    x = extract(path)
    info(f"  features extracted in {elapsed()}")

    onset = x["flux"] - np.convolve(x["flux"], np.ones(50) / 50, mode="same")  # local-mean removal
    onset = np.maximum(onset, 0)
    bpm, tconf = rhythm.tempo(onset)
    bt = rhythm.beats(onset, bpm)
    phase = rhythm.downbeat_phase(bt, x["low_flux"])
    on_n = onset / (np.percentile(onset, 99) or 1.0)
    def strength(t):
        i = int(t * rhythm.FPS)
        return float(np.clip(on_n[max(0, i - 3): i + 4].max(initial=0), 0, 1))
    beats = [{"time": float(t), "strength": strength(t)} for t in bt]
    downbeats = [b for i, b in enumerate(beats) if i % 4 == phase]
    info(f"  tempo {bpm:.1f} BPM (confidence {tconf:.2f}), {len(beats)} beats, {elapsed()}")

    # ---- 50 ms frames
    rms_f = _pool(x["rms"], k)
    n = len(rms_f)
    bands_f = _pool(x["bands"], k)
    tot = bands_f.sum(axis=1)
    def share(lo, hi):
        sel = (EDGES_HZ[:-1] >= lo) & (EDGES_HZ[:-1] < hi)
        return bands_f[:, sel].sum(axis=1) / tot
    bass, mid, treb = share(0, 250), share(250, 2000), share(2000, 1e9)
    cent_f = _pool(x["centroid"], k)
    onset_f = _pool(on_n, k, "max")
    rms_db = 20 * np.log10(rms_f + 1e-9)
    # beat salience: on-beat onset vs off-beat onset in a sliding +/-2 s window
    on_mask = np.zeros(len(onset))
    for t in bt:
        i = int(t * rhythm.FPS)
        on_mask[max(0, i - 3): i + 4] = 1
    kern = np.ones(int(round(4.0 / FINE_S)))       # +/-2 s
    on_sum = np.convolve(onset * on_mask, kern, "same")
    off_sum = np.convolve(onset * (1 - on_mask), kern, "same")
    on_cnt = np.convolve(on_mask, kern, "same") + 1e-9
    off_cnt = np.convolve(1 - on_mask, kern, "same") + 1e-9
    ratio = (on_sum / on_cnt) / (on_sum / on_cnt + off_sum / off_cnt + 1e-9)
    beat_salience = _pool(np.clip((ratio - 0.5) * 2.5, 0, 1), k)
    fields = {
        "energy_norm": _norm(rms_db),
        "rms_dbfs": rms_db,
        "onset_norm": onset_f,
        "beat_strength": beat_salience * np.clip(_norm(rms_db) * 1.5, 0, 1),
        "brightness_hz": cent_f,
        "brightness_norm": _norm(np.log(cent_f + 1)),
        "bass_norm": _norm(bass), "mid_norm": _norm(mid), "treble_norm": _norm(treb),
        "bass_share": bass, "mid_share": mid, "treble_share": treb,
    }
    vocal_note = "not measured (enable --stems)"
    stem_rec, stems_summary, stem_events = {}, {}, {}
    if use_stems:
        from .stems import separate, legacy_vocal, stem_record
        got = separate(path) or {}
        st = got.get("vocals")
        if st is None and legacy_vocal(path).is_file() and not got:
            st = legacy_vocal(path)                    # Demucs not here now: the older vocal-only stem
        if st is not None:
            vr = 20 * np.log10(_stem_rms_frames(st, n, k) + 1e-9)
            fields["vocal_dbfs"] = vr
            fields["vocal"] = np.clip((vr - (rms_db - 12)) / 12, 0, 1)   # vocal level vs mix
            vocal_note = "demucs stem"
            stem_rec = stem_record(st)
        if got:
            stems_summary, stem_events = _stem_parts(got, fields, n, k, frame_interval, rms_db)
        if st is None:
            from ..common.log import error
            from ..common.prompt import ask
            error("--stems: no stems were made (see above), so this analysis would have no vocal, drum, bass "
                  "or melody data ('doctor' checks Demucs)")
            if ask("Continue without stem data? [Y/n]", "y", show_default=False).lower() in ("n", "no"):
                raise SystemExit("stopped: fix the stems (see 'doctor'), then run again")

    # ---- boundaries on bar-synchronous features (whole-stream)
    edges = np.array([d["time"] for d in downbeats] + [meta["duration"]])
    if len(edges) < 12:
        edges = np.append(np.arange(0, meta["duration"], 2.0), meta["duration"])
    unit = float(np.median(np.diff(edges)))
    if edges[0] > 0.5 * unit:
        edges = np.insert(edges, 0, 0.0)            # pickup before the first downbeat
    if len(edges) > 2 and edges[-1] - edges[-2] < 0.5 * unit:
        edges = np.delete(edges, -2)                # merge a trailing sliver into the last bar
    feat = np.column_stack([np.log10(bands_f + 1e-10), rms_db[:, None] / 10])
    times = np.arange(n) * frame_interval
    X = segment.sync_features(feat, times, edges)
    level = 10 * np.log10(segment.sync_features((rms_f ** 2)[:, None], times, edges)[:, 0] + 1e-12)
    bnds = segment.boundaries(X, edges, level)
    info(f"  {len(bnds)} structural boundaries (novelty), {elapsed()}")
    lap = None
    if len(bt) >= 16:                                     # Laplacian segmentation on beat-synchronous features
        from . import laplacian
        fine_t = np.arange(len(x["rms"])) * FINE_S
        bedges = np.append(bt, meta["duration"])
        chroma_b = segment.sync_features(x["chroma"], fine_t, bedges)
        logb = np.log10(x["bands"] + 1e-10)
        n_c = 13
        dct = np.cos(np.pi / NBANDS * (np.arange(NBANDS) + 0.5)[None, :] * np.arange(n_c)[:, None])
        timbre_b = segment.sync_features(logb @ dct.T, fine_t, bedges)
        labels, k = laplacian.segment(chroma_b, timbre_b)
        lap = {"k": int(k), "beat_labels": [int(v) for v in labels],
               "boundaries": laplacian.boundaries(labels, bt, meta["duration"])}
        info(f"  laplacian segmentation: {k} kinds of material, {len(lap['boundaries'])} boundaries, {elapsed()}")

    vocal_summary = {"source": vocal_note, **stem_rec}
    if "vocal" in fields:
        vocal_summary["mean"] = float(fields["vocal"].mean())
        vocal_summary["active_fraction"] = float((fields["vocal"] > 0.5).mean())
    doc = envelope("seqtool.music", "seqtool-analyze-music",
                   {"filename": path.name, "sha256": file_sha256(path)},
                   {"audio": file_sha256(path)})
    doc["audio"] = meta
    doc["analysis"] = {
        "frame_interval": frame_interval,
        "summary": {
            "tempo": {"bpm": float(bpm), "confidence": float(tconf)},
            "energy": {"mean_norm": float(fields["energy_norm"].mean()),
                       "mean_dbfs": float(rms_db.mean()),
                       "p95_dbfs": float(np.percentile(rms_db, 95))},
            "dynamic_range_db": float(np.percentile(rms_db, 95) - np.percentile(rms_db, 10)),
            "spectral": {"centroid_hz_mean": float(cent_f.mean()), "bass_share_mean": float(bass.mean()),
                         "mid_share_mean": float(mid.mean()), "treble_share_mean": float(treb.mean())},
            "beat_strength_mean": float(fields["beat_strength"].mean()),
            "onset_rate_per_s": float((onset_f > 0.3).mean() / frame_interval),
            "vocal": vocal_summary,
            **({"stems": stems_summary} if stems_summary else {}),
        },
        "frames": {"start": 0.0, "count": int(n),
                   "fields": {k: [float(v) for v in arr[:n]] for k, arr in fields.items()}},
        "events": {"beats": beats, "downbeats": downbeats, **stem_events},
        "boundaries": bnds,
    }
    if lap:
        doc["analysis"]["segmentation"] = {"laplacian": lap}
    doc["run"] = {"audio": str(Path(path).resolve())}     # where the audio is; excluded from content hashes
    validate(doc, "seqtool.music")
    return doc


def vocal_line(music: dict, audio: Path | None = None) -> str:
    """One line on the vocal data in a music.json: where it came from and how much singing it heard."""
    v = music.get("analysis", {}).get("summary", {}).get("vocal", {})
    if v.get("source") != "demucs stem":
        return "vocals: {note}not measured{/} (add --stems to 'run', or 'pref stems = true' for every song)"
    line = (f"vocals: from {v.get('stem_file', 'the vocal stem')}, singing in {v.get('active_fraction', 0):.0%} "
            f"of the song (mean level {v.get('mean', 0):.2f})")
    from .stems import stem_problems
    probs = stem_problems(music, audio)
    return line + (f"  {{warn}}{'; '.join(probs)}{{/}}" if probs else "")


def inspect_audio(args) -> list[str]:
    import time as _t
    from ..common import config
    from ..common.canonical import read_json
    from ..common.paths import show
    from ..common.paths import expand
    f = expand(" ".join(args), "file") if args else \
        (Path(config.answer("last_audio")) if config.answer("last_audio") else None)
    if f is None:
        return ["no song given and none used yet - inspect audio path/to/song.mp3"]
    if not f.exists():
        return [f"no such file: {f}"]
    meta = decode.probe(f)
    st = f.stat()
    out = [f"file:     {show(f)}  ({st.st_size / 1e6:.1f} MB, modified {_t.strftime('%Y-%m-%d %H:%M', _t.localtime(st.st_mtime))})",
           f"audio:    {meta['duration']:.1f} s, {meta['sample_rate']} Hz, {meta['channels']} ch"
           + (f", {meta['codec']}" if meta.get("codec") else "")]
    sha = file_sha256(f)
    from ..common import songs
    rec = songs.get(sha)
    so = rec.get("seed_overrides", {})
    out.append(f"seed:     {songs.seed(sha)}" + ("" if rec.get("seed") else " (derived from the audio)")
               + (f"; overrides: {', '.join(f'{k}={v}' for k, v in sorted(so.items()))}" if so else "")
               + ("; sections edited by you" if rec.get("sections") else ""))
    from ..common.paths import legacy_name, seqtool_folder
    cands = [(legacy_name(f, "music"), legacy_name(f, "music-profile"))]            # standalone output before 0.19.9
    for d in [seqtool_folder(f), Path(config.answer("last_out", "seqtool-out")), Path("seqtool-out"),
              Path("seqtool-demo")]:
        cands.append((d / f"{f.stem}.music.json", d / f"{f.stem}.music-profile.json"))
    for mj, pj in cands:
        if mj.exists():
            m = read_json(mj)
            if m.get("lineage", {}).get("audio") != sha:
                out.append(f"analysis: {show(mj)} is for a different version of this file")
                break
            summ = m["analysis"]["summary"]
            out.append(f"analysis: {show(mj)}")
            out.append(f"  tempo {summ['tempo']['bpm']:.1f} BPM (confidence {summ['tempo']['confidence']:.2f}), "
                       f"{len(m['analysis']['events']['beats'])} beats, loudness p95 {summ['energy']['p95_dbfs']:.1f} dBFS")
            out.append("  " + vocal_line(m, f))
            from .stem_features import stems_line
            if stems_line(m):
                out.append("  " + stems_line(m))
            if pj.exists():
                p = read_json(pj)
                styles = sorted(p["profile"]["styles"].items(), key=lambda kv: -kv[1])[:3]
                out.append("  styles: " + ", ".join(f"{k} {v:.2f}" for k, v in styles))
                ids = {x["id"]: x["index"] for x in p["sections"]}
                out.append("  sections:")
                out.append("    #    start -    end  (length)  type        energy  repeats")
                for s_ in p["sections"]:
                    rep = f"#{ids.get(s_['repeat_of'], '?')}" if s_.get("repeat_of") else ""
                    from .sections_cmd import span
                    out.append(f"    {s_['index']:<2} {span(s_['start'], s_['end'])}  {s_.get('type', '?'):<10}"
                               f"  {s_.get('energy', 0):5.2f}   {rep}")
            break
    else:
        out.append("analysis: none yet - run: seqtool run --audio " + show(f))
    return out


def main(argv=None) -> int:
    from ..common.canonical import dumps  # noqa
    ap = argparse.ArgumentParser(prog="seqtool analyze-music", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=paths_arg)
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: <song>-seqtool/<song>.music.json, the song's results folder")
    ap.add_argument("--stems", action="store_true", help="separate vocals, drums, bass and other with Demucs (optional dep): vocal level, drum hits, "
                    "bass notes, melody")
    ap.add_argument("--frame-interval", type=float, default=None,
                    help="seconds per output frame (multiple of 0.01; default from preferences/music.json)")
    ap.add_argument("--preferences", type=paths_arg, default=None)
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    a = ap.parse_args(argv)
    from ..common.config import music_prefs
    fi = a.frame_interval or music_prefs(a.preferences)["analysis"]["frame_interval"]  # user prefs overlay defaults
    from ..common.paths import show, stage_output
    out = a.output or stage_output(a.audio, "music")
    doc = analyze(a.audio, a.stems, fi)
    write_json(out, doc)
    from ..common import current
    current.remember(audio=a.audio, music=out)          # this song is now the current one
    good(f"wrote {show(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
