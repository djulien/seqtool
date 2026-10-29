# seqtool — Design Notes (rev 139, 2026-10-28, seqtool 0.24.58)

Supersedes the October 4 MVP design PDF and the model-categorization notes.
Findings on the developer's own songs and show (song names, measurements, the
layout's props) are kept apart in DESIGN-addendum.md, so this file stays general;
"(addendum A1)" and the like point there. It is not part of the shared package.
Section 15 covers versioning and stale data; §13g is what seqtool does now, by topic. History -
the notes of each release, how each review concern was resolved and the changes by revision of
this file - is in REVISIONS.md. The roadmap is §13e, with design notes for 0.19 - 0.21 in §13f.
(The project was called xseq through rev 2.)

## 0. What it is (overview)

A Python toolchain: MP3/WAV + xLights layout (`xlights_rgbeffects.xml`) →
xLights `.xsq` sequence. The stages, as `run` numbers them in its banners:

1. music analysis
2. music classification (sections, styles)
3. layout (the stored show layout, or one given)
4. model analysis (geometry and capabilities)
5. matchup (scoring, continuity, passes, reactive presets, choreographies)
6. validation (5 and 6 repeat as a feedback loop)
7. summary (text, timeline page)
8. xLights export (when the layout is from xLights)

The core is generic. xLights lives only in `seqtool/adapters/xlights/`: the
layout import, the learned encoding (kit wizard) and the .xsq export. The
seqtool-direction skill (`skills/seqtool-direction/SKILL.md`) lets Claude turn
plain-language direction into seqtool commands.

## 1. Goal and principles

Generate a sensible, editable light sequence from an audio file and a display
layout. xLights is the first target, but **the core toolchain knows nothing
about xLights**: input adapters convert external formats into generic
artifacts, and output adapters convert generic plans into external formats.

Principles (unchanged unless noted):
- Separate measurement, interpretation, capability analysis, decisions,
  serialization and validation; every intermediate file is inspectable.
- Model fit and music fit stay separate; geometry-derived capabilities are
  explicit.
- Deterministic: same inputs + preferences + seed → byte-identical artifacts.
- Explainable: every decision keeps its score breakdown and reasons.
- **New:** adapter isolation. Groups, layers, palettes and effects are generic
  concepts. xLights structures and parameter encodings live only in
  `seqtool/adapters/xlights/`.
- **New:** a prototype first. Licensing only needs to stay broadly
  FOSS-compatible for now and gets formalised later.

## 2. Architecture

```
            ┌───────────── input adapters ─────────────┐
 xlights_rgbeffects.xml ─► xlights-import ─┐
 prop questionnaire ─────► prop-wizard ────┼─► layout.json (seqtool.layout)
 (future) photos ────────► photo-estimate ─┘          │
                                                      ▼
 audio ─► analyze-music ─► music.json          analyze-models ─► models.json
               │                                      │
               ▼                                      │
          classify-music ─► music-profile.json        │
               └──────────────┬───────────────────────┘
                              ▼
                 match (pass 1..n, seed, prefs, feedback) ─► matchup.json
                              │                      ▲
                              ▼                      │ feedback
                          validate ─► validation.json┘
                              │
            ┌─────────────── output adapters ──────────────┐
            └► xlights-export (+ learned encoding) ─► .xsq
```

**Undo / redo** (0.17.2, `common/undo.py`): every command that changes the user's
settings files (preferences, songs.json - sections, pins, seeds, lyrics -, rules,
baselines) is one undo step, labelled with its command line; read-only commands
make none. The dispatcher snapshots those files around the command and keeps the
changed ones before and after (`seqtool-prefs/undo/steps.json`, 50 steps).
`undo [N]` / `redo [N]` / `undo --list`; afterwards the last run is repeated
quietly so the plan follows, and the change is shown. A new command clears the
redo steps. Not covered: the stored layout and the xLights training.

**A thin, extensible shell.** `./seqtool.py` (shebang launcher) or
`python3 -m seqtool`:
- With arguments, it runs one command and exits.
- With no arguments, on a terminal, it opens a simple prompt (`seqtool>`)
  that fits iterative sequencing: run, inspect, explain, adjust, run again.
  - The prompt has history (`seqtool-prefs/history.txt`) and tab completion of
    commands and file paths.
  - Globs are expanded (`layout ../show/*.xml`) and unique prefixes accepted.
  - `help [topic|cmd]`, `clear`, `trace` (full traceback of the last
    error), and `quit`/Ctrl-D.
  - Errors and Ctrl-C end the command, not the session.
- Without a terminal, it prints usage.

**Help is split into topics.** `help` shows usage, global options, the
pipeline commands, and the list of topics: `help setup`, `help stages`, and
`help commands` (inspect, explain, gui, test, clear, …). `help COMMAND`
shows one command's options.

**Missing required arguments are asked for** on a terminal (command line or
prompt), and the previous answer is offered as the default. So `explain`
alone asks "model?" then "time?". Without a terminal, the usual usage error
appears.

**Commands are discovered, not registered.** Each command lives in its own
module, which loads its own dependencies when run, and declares itself in a
header comment:

    # seqtool-command: name | function | section | help

The shell reads these tags without importing anything, so startup is instant
and adding a command means adding a module. `inspect` targets work the same
way (`# seqtool-inspect: name | function | help`) and live in the module that
knows about the subject. Shared code lives in `seqtool/common/`.

The pipeline commands (`demo` / `run`) print a banner as each stage starts:
`== n/7 <stage> -> <output file>   [seqtool <command>]`. Every message and
file can therefore be traced to the stage, and to the single-stage command
that would reproduce it. The stages are 1 music analysis, 2 music
classification, 3 layout, 4 model analysis, 5 matchup, 6 validation (5 and 6
repeat per feedback iteration), 7 summary, and 8 xLights export, which is
added (`n/8`) when the layout comes from xLights.

**Rules for every command, present and future** (the user's, 0.19.2):
- **Any file or folder argument accepts wildcards, like a shell** (`*`, `?`,
  `[..]`, and `~`): one match is used; several give a numbered choice on a
  terminal or in the GUI, or an error listing them; none leaves the text as typed,
  and the "not found" message names the folder seqtool is in. Use
  `paths.arg` (argparse type) or `paths.expand(text, "file"|"dir")` for words
  parsed by hand; never `Path(text)` directly (the 0.19.0 `face build` did, so a
  pattern was "not found"). Bash-style escaped spaces (`my\ faces/x.png`) work too.
- **Any song argument also accepts `--baseline [N]`**: song N of the baseline
  (no N: each song in turn). Commands that take the song themselves get it
  passed (`BASELINE_ARG` in `__main__.py` names the flag); commands that work on
  the current song make song N current first (`SWITCH`). A new command that
  takes a song, or works on the current one, is added to `BASELINE_ARG`.
- **Anything that can take more than a few seconds shows its progress** (the
  user's rule, 0.19.8): a percentage with the time so far and an estimate of the
  time left - one line rewritten in place on a terminal, a line every 10% in the
  GUI console - via `common/progress.Progress(total, label)` (`.step()` /
  `.at(done)`, `.done(note)`; silent for work done within 1.5 s). Say first what
  is being done and how much ("trying 96 combinations ... on 4 songs"). Has it:
  Whisper (both passes), the vocal stem (demucs), `sections tune`. A new long
  step - and any found without it - gets one.
- **A command whose results can surprise takes `--debug`** (the user's rule,
  0.19.5): it writes a plain-text log of what it saw and decided, next to the
  song's results (`<song>-seqtool/<song>.debug-<what>.txt`) or its own output, and
  prints the path (`common/debuglog.DebugLog`). So far: `lyrics transcribe`
  (every Whisper segment, the passages without words), `lyrics align` (each of
  your words, its status and the heard word it was paired with), `lyrics
  phonemes` (each word's source, sounds and mouths), `sections` (every candidate
  boundary, its evidence, kept or why dropped), `face build` (every feature, the
  eye pairs tried, the mouth candidates). (`--diagnose` became `--debug`.)
- **Completion** (0.19.5, `common/complete.py`, shared by the terminal prompt
  and the GUI console): commands, then each command's options and sub-commands -
  read from its own argparse parser, built without running the command (its
  parse_args stopped in that thread only) - then values: option choices, Whisper
  models, files and folders for path options (and anything typed like a path),
  props / groups / submodels, the current song's planned targets and sections
  (`@#3`), effects, presets, faces, tutorials, inspect targets, commands for
  `help`. Free-form positionals get their words from `COMMAND_WORDS`. Terminal:
  Tab, and a second Tab lists the choices with a hint each. GUI: a list opens as
  you type (`/api/complete`); Up/Down choose, Tab or Enter takes one, Esc closes;
  Enter without a choice runs the line as before.
- **History** (0.19.6, `common/history.py`): every command typed at the prompt or
  in the GUI console goes to one file (`seqtool-prefs/history.txt`, 1000 kept, saved
  as typed); `history [N | TEXT | -c]` lists, finds or forgets them, and `!!`,
  `!N`, `!-N`, `!TEXT` run one again (bash's forms; the line run is echoed).
  Up/Down in the GUI console walk the same list.
- **The start folder** (0.19.6): when seqtool starts in a folder it can't write to,
  or in a Windows system folder (a double-clicked .pyz starts in
  C:\Windows\System32), it works in `~/seqtool-files` instead and says so
  (`paths.ensure_work_dir`).
- **Results go in a subfolder, never beside an input** (the user's rule, 0.19.9):
  a song's results in `<song>-seqtool/`, a layout's in `<layout>-seqtool/`
  (`paths.seqtool_name`; `write_json` makes the folder). Single stages used to
  write `<song>-seqtool.music.json` beside the song, which `run` never updated, so
  they stayed stale; such files are still read (`paths.legacy_name`) and
  `status --clean` deletes them once newer results exist.
- **Completion never runs a command** (0.19.9): a command's options are read by
  calling it with a parse_args that stops at once - so a command that doesn't
  parse with argparse (pref, undo, cd, play ...) is not called at all (0.19.5-8
  did: typing 'pref ' printed the preference list on the terminal from the GUI's
  completion thread, and 'undo ' would have undone). Free-form words come from
  `COMMAND_WORDS` instead (pref files, folders for cd).
- **No local import shadows a name used above it** (0.19.9): a test parses the
  package and fails on a function that uses a name before importing it locally
  (Python then treats the name as local everywhere in it: 0.19.8's `run` raised
  UnboundLocalError on 'info').
- **`models`** (0.20.1): every prop of the stored layout - shape class, lights,
  controller, the groups it is in, sequenced or not and why (`models PATTERN`,
  `--unused`, `--submodels`); `layout` points to it and to `groups`.
- **Group reasons in general words** (0.20.1): an unused group sums up its
  members' reasons by kind with the names that matter ("its props share their
  channels with shadow model(s) wise3-2d, sequenced instead", "... in an excluded
  layout group (dev)") instead of one member's reason word for word; a shadow
  model's covered props say "its channels are covered by shadow model 'X', which
  is sequenced instead" (was "colour-order/channel helper", true only for the
  Manger helpers). Groups whose *sequenced* props are the same but whose members
  differ say so: "the same sequenced props as 6.NatFigures (6.NatFigures also
  holds 2 prop(s) that aren't sequenced (...))" - not "same props".
- **`pref NAME` says what it may be** (0.20.2): "valid values: ..." - the fixed
  choices (`prefcmd.CHOICES`, e.g. xlights.shadow_models, base.members,
  variation.aspect, sections.method / snap, group roles; setting another is
  refused with an example), else the kind of value (true | false, a number, a list,
  durations) - and "about:" with the sentences of the nearest description that
  name it. Completion goes one level per dot (`pref music.` -> music.sections. ...;
  after `=` the choices).
- **Shadow models: `skip_shadow` is the default** (the user, 0.20.2): a model with
  'Shadow Model For' set is left out ("a shadow model of 'X', which is sequenced
  instead") and the models it shadows are planned; `sequence_shadow` the other way.
  **Inactive models** (xLights' Active unticked, `Active="0"`) are never planned.
- **Models after a shadow model** (0.20.3, the user's rule): a model whose start
  channel follows a shadow model ('>Shadow:1' after it, '@Shadow:N' on it; chains
  followed) is asked about at `layout` ("treat it as a shadow model too? [Y/n]");
  the answer is kept in `xlights.shadow_followers` {name: true|false}; true = left
  out like the shadow model. Unattended, nothing is assumed: they are planned and
  the warning gives the pref command. '>Model:N' start channels are now resolved
  (after that model's last channel). Models without an Active attribute are active.
- **prop-wizard and the stored layout** (0.20.2): `prop-wizard` without a file adds
  props to the stored layout (origin `wizard`; asks first when the layout is from
  xLights, which won't know them); with a new file while an xLights layout is
  stored it asks too (the file is a separate layout for `run --layout`). `layout
  XML` then says which added props aren't in xLights and asks whether to keep them
  (re-reading a stale layout keeps them).
- Model analysis about twice as fast: the mirror-symmetry share is estimated on at
  most 400 points (a layout of 125 props took about a minute).
- **prop-wizard** is for a yard without an xLights layout (it asks about each
  prop and writes a seqtool layout .json); given an .xml or a show folder it says
  to use `layout` instead (0.20.1).
- **Commands affected by preferences say which** (the user's rule, 0.20.0): a
  "settings used:" note with the names and current values ("(yours)" where you
  changed them) - `prefcmd.uses(...)`. So far: `groups`, `layout`
  (xlights.exclude_controllers and the other import exclusions, umbrella names,
  shadow models, group roles), `sections` (music.sections.*), `run` (base pass,
  durations, variation, top sections). A new command reading preferences adds
  its line.
- **`status` covers the stored layout** (0.19.11): a line "layout: ok | STALE (why)"
  with the fix ('layout' re-reads it; `layout` with no argument now re-ingests a
  stale layout instead of only showing it). `layout.stale_reasons()` is the one
  check, used by `status` and by everything that loads the layout.
- **Props without a controller are planned** (0.19.11, the user's case: props
  defined but not wired yet): `xlights.exclude_controllers` is empty by default
  (it was ["No Controller"]); add it back to leave such props out.
- **Every help names the version** (0.19.10): `help`, `help TOPIC` and each
  command's `-h` start with "seqtool X.Y.Z".
- **The demo is not a stored layout** (stated for the user, 0.19.10): `demo` plans a
  built-in yard and a synthesized song into `seqtool-demo/`, and leaves your stored
  layout alone. Commands about the song (react, rules test without a stored
  layout, explain, pin ...) accept the layout the current song was planned with,
  whichever run made it (demo, `run --layout FILE`, the stored one) - no demo code
  there; commands about the show (layout, groups, face) use the stored layout.
  Demo-specific code is only: `demo` itself, the tutorials' "{rerun}" (demo
  again when the results are the demo's) and `seqtool-demo` as a last place to
  look for results.
- **New names in a map of your own** (0.19.10): `pref section_types.spoken =
  breakdown` (before: "no preference named ...") - a name not in the defaults is
  accepted where the path ends in a mapping (music.section_types), with the usual
  "new key - check the spelling" note.
- GUI monospace text names Linux fonts explicitly (DejaVu Sans Mono, Liberation
  Mono, Noto Sans Mono, Ubuntu Mono) before the generic family (0.19.10).
- Every problem message shows an example of what to type (below).

**Every problem comes with an example of what to type** (0.17): stale files
(`status`: "fix: 'run' rebuilds the stale files"), validator issues (a `fix`
per issue code, e.g. LOW_EFFECT_DIVERSITY -> 'reroll Roofline', or 'run
--candidates 5'), unknown names ("did you mean 'MegaTree'?", `common/suggest.py`),
bad arguments and missing files. New messages follow the same rule.

**Paths are shown from the file a command works on** (0.17, `paths.anchored`):
song commands (run, analyze-music, sections, pin, reroll, explain, status, ...)
show files in the song's folder or below relative to that folder
(`carol-seqtool/carol.summary.txt`); layout commands (layout, groups, rules,
xlights-import) relative to the show folder. The main file itself is shown from
the current folder, and paths inside example commands always are (`show(p,
typed=True)`), since those are typed where you are. The dispatcher picks the
anchor per command (`anchor_for` in `__main__.py`); `run` anchors on its song.

**Messages** give the important information clearly and briefly:
- Every command starts by printing `seqtool <version>` (hidden by `--quiet`),
  so later messages don't repeat it.
- Stale files read `music.json is stale (0.4.0; frame_interval 0.05 -> 0.1)`.
- Stage banners read as above, e.g. `== 1/7 music analysis -> song.music.json
  [seqtool analyze-music]`.
- Long lists are summarised as counts, with a pointer to the details.

**Commands** may be abbreviated to any unique start: `expl` = `explain`,
`stat` = `status`.

**Pipeline output** stays high-level: stage banners, then a short block of
results. It shows the headline (tempo, sections, styles) and the paths of
`<song>.summary.txt` (section table with repeat markers, plus what wasn't
planned and why), `<song>.explain-example.txt` (a worked `explain` command and
its output), and the browser timeline.

`layout` and `--rgbeffects` accept either the file or the show folder that
contains xlights_rgbeffects.xml.

**`explain music @TIME`** treats the audio as a virtual model. It shows:
- the section (type, length in bars, label confidence, repeats, and the
  strength of the transition into it);
- the bar and beat position;
- the measured values at that frame;
- the averaged features of the decision window the matchup scores;
- the effects with the best music fit there;
- the song's styles.

It teaches what the analysis heard, separate from prop-specific choices.

`run` with no `--audio` uses the most recently used song; it asks if there
isn't one. `status` starts with the last song and the last results folder.

**The current song** (`common/current.py`) is the last song any command
worked on: `run`, `demo`, `analyze-music`, `classify-music`, or `match`.
- Its results can live in two places:
  - the pipeline folder `<song>-seqtool/<song>.*.json`;
  - single-stage files beside the song, `<song>-seqtool.*.json`.
- For each kind (music, profile, plan), the newest file that belongs to the
  song wins. A music.json records its audio location under `run`, which is
  excluded from content hashes, so moving a song changes no hash.
- The GUI, `explain`, `gui`, `status`, and `sections` all use this resolver,
  so they always agree. `status` starts with "current song:", and with no
  folder argument lists that song's files from both places.

**Session memory:** the last song and output folder are remembered, so
`inspect audio` and `explain` work without arguments after a run.

**inspect** targets so far:
- `xlights`: learned versions, effects, assumed values, problems, and any
  training in progress.
- `layout`: the ingested source, dates, and model/group counts.
- `audio [file]`: file details plus the analysis (tempo, styles, sections).

**Prompts** go through one helper (`common/prompt.py`):
- The question goes on its own line and the input line is a short `> `, so
  line editing works normally. readline gives backspace, arrows, and history.
- Prompts always reach the real terminal, even when output is redirected.
- They return the default immediately when there is no terminal, or when
  `SEQTOOL_NONINTERACTIVE=1` (always set by the test runner), so nothing can
  block silently.
- **Asking is the default.** Questions whose answers persist start from the
  previous answer, so Enter repeats the last session's choice. Examples:
  group roles, the kit folder, the viewer choice, accepted channel overlaps.

**`pref`: see and change preferences** (text-based for now; a GUI editor
can use the same functions later):
- `pref` lists the preference files, with `*` marking those you have
  changed.
- `pref NAME` shows any node as an indented tree with the file's
  description. Your values are marked `* yours (default …)`.
- NAME can be `music.sections.min_bars`, `music/sections/min_bars`, or just a
  unique key (`min_bars`). Slash notation handles keys that contain dots
  (`models/targets/1.ALL/role`).
- `pref NAME = VALUE` sets a value. JSON is parsed (numbers, true/false,
  lists, objects); anything else is text. The type must match the default
  (`--force` overrides). New keys inside open groups (such as per-target
  settings) are allowed, with a spelling warning.
- `pref reset NAME` (any node, or a whole file) returns to the defaults.
  `pref changed` lists every value you've changed.
- `pref edit FILE` opens your file in `$VISUAL`/`$EDITOR` (or nano/vim/vi/
  notepad), checks the JSON afterwards, and offers to re-edit.
- `param_map` (the xLights parameter mapping: spans, rates, assumptions) is
  shown as its own preference file. Its defaults live in the adapter, and
  your values are stored in `xlights.json` under `param_map`.

**User preference folder.** Built-in defaults (`<repo>/preferences`) are
never written to. The user's folder (default `~/seqtool-prefs` since 0.22.3 - before, `./seqtool-prefs`
wherever seqtool started, which put one beside songs; or `--preferences DIR`, or `SEQTOOL_PREFS`, a
relative one taken from the start folder) holds only the keys the user
changed, and is deep-merged over the defaults. `answers.json` there
remembers interactive answers.

**Paths** inside the current directory are displayed relative to it, and
typed paths may be relative.
- **Glob patterns** are accepted wherever a file or folder is asked for:
  command arguments, prompted values, the kit folder, and inspect targets.
  One match is used; several give a numbered choice on a terminal, or an
  error listing them.
- `pwd` shows the working folder plus the folders seqtool uses
  (preferences, last song, last results, show layout, kit). `cd FOLDER`
  changes it at the prompt.
- The preferences folder and remembered paths are absolute, so `cd` doesn't
  move them.

**Default file names** follow one convention (0.18.4): a song's results go in
its results folder `<song folder>/<song>-seqtool/<song>.<kind>.json` when that
folder exists (`paths.stage_output`), and each stage names its output like its
input (`paths.sibling`: song.music.json -> song.music-profile.json). Only a song
never `run` gets single-stage files next to it, named `<base>-seqtool.<kind>.json`.
- `analyze-music song.mp3` (no results folder yet) → `song-seqtool.music.json`,
  then `song-seqtool.music-profile.json`, `.matchup.json`, and `.validation.json`;
  `xlights-import` → `xlights_rgbeffects-seqtool.layout.json`.
- Single stages chain with the fewest arguments. `match --music X` finds the
  profile next to it and uses the stored show layout. `validate --matchup X`
  finds the files the matchup was made from.
- `run` puts its results in `<song folder>/<song>-seqtool/`; the demo still
  uses `./seqtool-demo`.

**`doctor`** checks the setup in the order it is done: Python, numpy and
ffmpeg; the preferences folder (valid JSON); the stored layout (present,
unchanged); the xLights training (learned, complete); group roles (reviewed
for this layout - `groups` with no argument now uses the stored layout and
records the review); Demucs; the current song's files. Each line is ok, a note,
or a fix with its command, and it ends with the one command to type next.
Nothing is changed.

**`--baseline [N]` on commands that work on the current song** (0.19):
xlights-export, explain, pin, unpin, reroll, gui, status, inspect and play make
song N the current song first (its newest results; `run --audio SONG` becomes
the run that pin and reroll repeat), then run as usual; without N, each song in
turn. A song with no results yet is named with `run --baseline N`. The commands
that take a song themselves (analyze-music, classify-music, match, validate,
lyrics, sections) are given it, as in 0.18.4.

**`run --baseline [N]`** (0.17.4) runs every song of the baseline, or song N
(`baseline` numbers them); other options apply to each.

**`baseline`** is for tuning defaults on real songs. A baseline holds several
songs. Since 0.18.1 the verbs are `baseline add [SONG ...]` (no song: the current
one; a song already in it gets its plan replaced, said so), `baseline remove SONG|N`,
`baseline update [SONG|N ...]` (accept the current results, all songs or the ones
named; notes when the current song isn't in it) and `baseline diff`; `save`
still works (with songs = add, without = update). Before, `save` with no songs
re-saved the baseline's songs, so the user's 'run --audio new.mp3' then
'baseline save' didn't add the new song. Adding runs each song (`run`, non-interactive, reusing fresh analysis) and keeps a
snapshot: sections, the effects per target and section (as in the summary
table), the palette, seed and validation counts. After a settings change,
`baseline diff` runs the same songs again and lists only what changed
(`MegaTree  #3 chorus  spirals -> meteors`). When sections change, effects are
compared at the same moments, not by section number. `--name` keeps several. The current song and
the last run (for `reroll`) are restored afterwards.

**`memory`** shows available/total system memory and seqtool's resident
memory (current and peak), plus the change since the previous `memory` in
the session. Sizes of 1 GB or more are shown in GB, smaller ones in MB, with
one decimal and ".0" dropped.

**Tests:** `seqtool test` shows a single progress line rewritten in place
(`[12/42] Class.test`), so a hang shows exactly where it is. It forces
non-interactive settings: stale files are rebuilt and optional installs are
declined. `-v` gives the usual verbose listing. Each stage is also importable as a
function (`analyze()`, `classify()`, `run()` …) so a GUI (e.g. trackED) can
drive it.

## 2a. Where things are (source map)

| Area | Files |
|---|---|
| Shell, REPL, help, tests runner, colour install | `seqtool/__main__.py`, `seqtool.py`; `bootstrap.py` + `package.py` (the .pyz) |
| Common | `common/` - config, prompt, color, log, paths, songs, current, freshness, status, prefcmd, shellcmds, undo, history, deps (optional packages), fuzzy, args, `definitions.py` + `define_cmd.py` (named terms), `showfiles.py` (files into the show folder), `start_cmd.py`, `update.py` (newer versions), `bundle_cmd.py` |
| Music | `music/analyze.py`, `classify.py`, `laplacian.py`, `sections_cmd.py`, `lyrics.py` (+ `transcribe.py`, Whisper), `voices.py` ({VOICE} codes), `stems.py` (Demucs), `rhythm.py` (incl. `beat_numbers`), `phonemes.py` |
| Layout / models | `layout/store.py` (`layout` cmd), `adapters/xlights/import_layout.py` (incl. submodels), `models/analyze.py` (submodels, detail_members) |
| Matchup | `matchup/engine.py` (run, plan_target), `passes.py` (top/detail/enhance, rests, pin rows), `base.py` (whole-yard moments), `parts.py` (what every way of placing an effect shares), `reactive.py` + `keyframes.py` (presets), `choreo.py` (choreographies), `calls.py` + `calls_cmd.py` (call and response), `pins.py`, `place_cmd.py` (promote / demote), `cue_cmd.py`, `feel.py`, `palette_cmd.py`, `score_cmd.py` (the song's score), `batch_cmd.py`, `direct.py` (offline translator), `rules.py` / `rules_cmd.py`, `react_cmd.py`, `catalog.py` (`effects`, `presets`), `cli.py` + `explain.py`, `reroll.py`, `borrow.py` |
| Validation | `validate/validate.py` (later passes get only hard checks) |
| xLights | `adapters/xlights/kit.py` + `kit.json` (the training wizard, `--update`, `offer()`, `at_start`), `encoding.py` (learned settings, value curves `Curves`, rotation) + `param_map.json` + `effect_map.json`, `export_xsq.py` (timing tracks incl. lyrics, row order, submodel rows, glides, unlearned-effect fallback), `checks.py` (`xlights-export --checks`), `xsq.py` (reader), `angles_cmd.py` (`submodel angles`), `write_faces.py` (editing xlights_rgbeffects.xml as text) |
| GUI | `gui/server.py` (SSE, jobs, /api/help, /api/about, /api/explain), `gui/app.html`, `gui/thumbs.js` (previews + colour renderer, shared with the static timeline in `demo/view.py`) |
| Tutorials | `tutorial.py`, `tutorials.json` |
| Faces | `adapters/xlights/faces.py` (format learned from `faceInfo`, generic faces, snippet writer; shipped fallback `learned/faces-2025.13.1.json`), `faces/build.py` (detection, mouth shapes, sheet; Pillow), `faces/cmd.py` (`face build / list / format / use`, `inspect faces`) |
| Prefs | `preferences/` effects, scoring (incl. `passes`), models (group_roles, rules), presets, palettes, music (incl. `calls`), xlights, faces (mouth shapes), general (session_start, fuzzy, directions, check_updates, show_files), intents (`direct`) |
| Fixtures and tests | `tests/test_mvp.py`, `tests/fixtures/` (not in the shared package) |

## 3. Artifacts and conventions

| Schema | Producer | Knows about | Does not decide |
|---|---|---|---|
| seqtool.layout | adapters, wizard | props as generic shapes, groups | capabilities |
| seqtool.music | analyze-music | measurements | meaning |
| seqtool.music-profile | classify-music | styles, character, sections | effects |
| seqtool.models | analyze-models | geometry features, class, capabilities | what music calls for |
| seqtool.matchup | match | effect plan + parameters + explanations | external encoding |
| seqtool.validation | validate | errors, warnings, feedback | how the adapter encodes |

**Versioning.** These rules are unchanged from rev 1:
- Schemas use JSON Schema 2020-12 with MAJOR.MINOR versions.
- A consumer accepts any 1.x file, ignores unknown fields, and tolerates unknown vocabulary.
- A consumer rejects any other major version.
- Schemas live in `schemas/`.

**Time.** Seconds from the start of the audio, as floats. Frames are stored
columnar: frame i is at `start + i × frame_interval`.

**The frame interval is a setting, never a constant.** It comes from
`preferences/music.json` (`analysis.frame_interval`, currently 0.05 s) or
`--frame-interval`. It must be a multiple of the analyzer's internal 10 ms
hop. Every consumer reads `frame_interval` from the file it's given, and
nothing downstream assumes a value. Changing the setting makes existing
music.json files stale (§15), so they are rebuilt.

**Normalised and absolute values.** Fields named `*_norm` are normalised within
one song or layout (0–1, using the 5th–95th percentile for audio and the layout
extent for geometry). Examples: `energy_norm`, `brightness_norm`,
`bass_norm`, `onset_norm`, `bounds_norm`, `scale_norm`. Absolute fields carry
their units in the name: `rms_dbfs`, `brightness_hz`, `vocal_dbfs`,
`bounds` (layout units), and so on. Every summary includes both.

**Hashes and lineage.**
- `content_sha256` is computed over canonical JSON with transient keys
  (`created_utc`, `run`) removed, so it depends only on data.
- Every artifact carries `lineage`: the sha256 of the original source files
  (`audio`, `layout`, `preferences`). Lineage is merged forward stage by stage.
  A conflict, such as inputs derived from different audio files, is an error.
- `SOURCE_DATE_EPOCH` pins timestamps for byte-reproducible files.
- Every artifact records `producer.version`. Freshness checks use it together
  with lineage and content hashes (§15).

**Sections** carry:
- a sequential integer `index` (1..N) and an `id` (`S01`…);
- `frame_range` and `beat_range`, so any section dereferences straight back into music.json;
- `repeat_of` and `repeat_index`, which link repeated material.

## 4. Layout and prop characterisation

The core needs an approximate node point cloud **in wiring order** for every
prop. Exact pixel positions are not required. Shape and node order drive the
features, and size only matters relative to other props.

**Generic shapes** are defined in `seqtool/layout/shapes.py`. Each takes a few
parameters, such as size, node counts, and coverage degrees:
`line`, `polyline`, `arc`, `ring`, `grid`, `cone`, `flat_tree`, `radial`,
`star`, `volume`, `points`.

A single generator turns any description into points. Each prop record holds:
- **transform:** position, scale, and rotation;
- **semantic:** an optional hint;
- **controllable:** whether the generator can drive it;
- **origin:** opaque adapter data, carried through untouched.

Producers, in order of preference:
1. **xLights importer**, verified against a real (trimmed) show file.
   **Sizes and positions:**
   - "Boxed" models are centred on WorldPos. Their world size is the
     render-buffer size in nodes × Scale, so shapes are built in node units,
     centred (`transform.anchor: "center"`), then scaled.
   - Two-point models (Single Line, Icicles) run from WorldPos to
     WorldPos + (X2,Y2,Z2).
   - Poly Line vertices are WorldPos + PointData × Scale.

   **Shapes by model type:**
   - Custom models use the CustomModel grid: '|' separates depth layers,
     ';' rows, ',' cells, and each cell holds a node number (wiring order).
   - A Custom model with Depth > 1 gets the semantic hint `sculpture`, which
     becomes class FIGURE unless the geometry is clearly radial, ring, linear,
     arc, or cone.
   - "Tree NNN" supplies the coverage degrees, and TreeBottomTopRatio the taper.
   - A single-strand matrix is treated as a line.
   - Lines of 3 nodes or fewer (DMX single-pixel fixtures, floods) get the
     semantic `flood`, which becomes class FLOOD (wash and pulse only).

   **Size versus render buffer:** physical size (node grid × Scale, plus
   node size) only decides how big a prop looks in a preview. The node grid
   decides how effects render. The importer keeps both: physical size in
   shape + transform, the grid in `render_buffer` (columns × rows [× layers]),
   which the analyzer copies into models.json.

   **Exclusions** (`preferences/xlights.json`): `exclude_models`, dev/hide
   layout groups, "No Controller", placeholder/filler names, and DMX types.
   Excluded models are kept but marked not controllable, with a `skip_reason`.

   **Shadow models and channels:**
   - Each model's channel range is resolved from StartChannel
     (`!Controller:N`, `@Model:N`, or absolute) and its node count.
   - The model with "Shadow Model For" set is the one effects go on.
   - Models whose channel range it fully covers are colour-order or channel
     helpers and are skipped (e.g. a 3D figure is sequenced while its two
     colour-order helper models are skipped).
   - Any other set of models sharing channels is warned about. On a terminal
     the user is asked once whether to keep all of them (different props)
     or exclude some. "Keep" is remembered in answers.json; exclusions go to
     the user's xlights.json and trigger a re-import. The xLights preferences
     are part of the layout's lineage, so changing them makes the layout
     stale.

   **Groups:**
   - Nested groups are flattened to models.
   - "Model/Sub" submodel refs map to the parent model.
   - Empty entries are ignored, and unknown names are reported.
   - Each group gets a `structure.kind`:
     - `leaf`: members are whole models;
     - `umbrella`: contains other groups;
     - `submodel_view`: only submodels;
     - `single`: resolves to one model;
     - `empty`.
   - Each group also gets a `render_hint`, mapped from its xLights buffer
     layout: `as_one` (minimal grid and the like), `per_prop` (overlay/per
     model), or `stacked` (horizontal/vertical stack).

   **Views:** sequencer views, and the default one, are kept as generic `views`.
2. **Prop questionnaire** (`prop-wizard`). Asks for shape type, dimensions,
   node counts, position, and group. Answers can be scripted for repeatable
   test layouts. This is also how hand-built generic demo layouts are made.
3. **Photo-based estimate (future).** Three orthogonal photos can give an
   approximate envelope through silhouette intersection (a visual hull).
   Node positions along the strings can't be recovered from photos alone, so
   the practical version is: one front photo, then a traced or auto-detected
   outline, plus the node count and start corner. That yields a `points` shape.
   It is worth doing for irregular custom props only; the questionnaire covers
   standard props better.
4. **Fallback.** Re-implement xLights' node-placement logic per model type.
   This is accurate but costly, and couples us to xLights internals. It should
   only be done for types where 1–3 prove inadequate.

**The show layout is ingested once** (`seqtool layout xlights_rgbeffects.xml`,
or the first `run --rgbeffects`). The imported layout, its model analysis, and
the source path and checksum are kept in `seqtool-prefs/layout/`.
- `run` uses them when neither `--rgbeffects` nor `--layout` is given.
- If the source file or the xLights preferences change, the stored layout is
  stale and is re-ingested under the `--stale` policy.

## 5. Music analysis (`analyze-music`)

Decoding streams through ffmpeg into mono float32 at 24 kHz, in 10-second
chunks, so memory stays bounded. A stdlib `wave` fallback handles WAV without
ffmpeg.

The analyzer works at two resolutions:
- **10 ms (internal):** an onset envelope used for tempo and beats.
- **frame_interval (written out, default 0.05 s):** RMS, 24 log bands,
  spectral centroid, band shares, onset strength, and beat salience.

Whole-song algorithms run on these compact arrays, which is allowed:
- **Tempo:** autocorrelation with a log-normal prior centred on 120 BPM.
- **Beats:** dynamic-programming tracker.
- **Downbeats:** the beat phase with the most low-band onset energy.
- **Boundaries:** bar-synchronous self-similarity with checkerboard novelty,
  combined with weighted energy-step novelty. Verse-to-chorus lifts are often
  energy rather than timbre changes.

**Demucs progress** (0.17.2): Demucs draws its progress bar with carriage
returns, so its output is read in chunks and split on them; the terminal shows
one line rewritten in place (percent, time so far, time to go), the GUI console
a line every 10%.

**Vocals are optional.** A Demucs vocal stem, ported from lyric-track.py, adds
`vocal`/`vocal_dbfs` frames. Without it the field is omitted rather than
invented. Whisper transcription (0.18.0, `lyrics transcribe`) runs on the stem.

**The stem is checked like any other input** (0.15.1). The stem is saved next to
the song as `<song>-vocal_stem.wav`. music.json records its name and sha256
(`analysis.summary.vocal.stem_file` / `stem_sha256`). A cached music.json is
stale when:
- `--stems` is on but it was made without a stem, or the reverse;
- its stem file is missing or no longer matches the recorded checksum;
- it is from 0.15.0, which has no stem record.

`status` reports the same. The reuse line names the stem (`reusing
song.music.json (vocal stem: song-vocal_stem.wav)`), and Demucs prints its
progress. A stem is reused only while it is newer than the song and the same
length; an edited stem is re-measured, not replaced.

**Seeing the vocals** (0.15.2): `inspect audio` has a vocals line (the stem,
the share of the song with singing, or how to turn stems on), and the GUI and
timeline page draw the vocal level as a line over the waveform. If `--stems`
can't make a stem, the analysis says so in red and asks whether to continue
without vocal data (non-interactive runs continue).

**Drum, bass and other stems, and the melody** (0.22.0). `--stems` now keeps all four
htdemucs stems, in the song's results folder: `<song>-seqtool/stems/<song>.vocals.wav`,
`.drums.wav`, `.bass.wav`, `.other.wav` (results never beside an input; the 0.15-0.21
`<song>-vocal_stem.wav` beside the song is still read for the vocal level until the song
is separated again, which `--stems` does with a message - the old file can then be
deleted). One Demucs run makes all four (htdemucs computes them anyway; `--two-stems`
only summed three). `stem_problems` checks every stem's record (name, sha256, plus size
and mtime so an unchanged file isn't hashed again) and calls a vocal-only analysis stale
when stems are wanted. All of it is measurement (`music/stem_features.py`, numpy only):

| music.json | what |
|---|---|
| frames `drums`, `bassline`, `other` (+ `_dbfs`) | each part's level against the whole mix, 0..1 (as `vocal`, over 18 dB) |
| frames `melody_hz`, `melody_voiced`, `melody_norm` | the tune's pitch (0 = none), share of the frame with a clear pitch, how high it is 0..1 within the song's melodic range (5th-95th percentile), held through rests |
| events `kick`, `snare`, `hat` | drum hits: onsets in the drum stem's low (<150 Hz), mid (150 Hz-4 kHz) and high (>5 kHz) bands, merged within 30 ms and sorted by level against each band's loudest (kick: low within 12 dB, rising 6 dB; snare: mid and high within 10 dB; hat: high only). A hit can be a kick and a hat. |
| events `bass` | bass-stem onsets, with `midi` / `note` where YIN (30-300 Hz) finds a steady pitch 20-120 ms after the attack |
| events `melody` | notes: `time`, `end`, `midi`, `note`, `hz`, `height` (0..1), `source` (vocals / other); runs of steady pitch (a change must hold 30 ms), at least 80 ms |
| summary `stems` | per stem its record and counts; `melody`: notes, range, voiced share, share from the voice |

The melody is the voice where the vocal stem sings (YIN, 75-1100 Hz, with the
cumulative-mean-normalised difference under 0.35 and the hop within 30 dB of the stem's
loud level), otherwise the 'other' stem's leading pitch. 'Other' usually holds chords,
which YIN can't follow, so it uses a harmonic-sum salience (C3-C7 in 1/3 semitones, six
harmonics weighted 0.8^h) minus each pitch's mean over the surrounding 2 s: held chords
and pads cancel, the moving line stands out; no clear winner = no melody, not a guess.
The synthetic demo song tests it with perfect stems (`synth.write_stems`, and the test
Demucs's `SEQTOOL_FAKE_STEMS`): 128 kicks, 32 snares, the lead's 128 notes by name, the
bass roots.

Uses: reaction presets can be `on` kick / snare / hat / bass / melody (any event list in
music.json is a trigger; an event's own values - strength, midi, note, height, source -
can be tested in `when` and drive `params`; `colors: {"from": "height"}` picks a palette
colour by a value). Built-in presets kick, snare, hat-sparkle, bass-pulse, melody-fill
(a `fill` whose level follows the tune), melody-color. A preset whose trigger needs stems
on a song without them warns once with the command. Effect choice: window features
`drums` and `melody` (the voiced share) join music_fit (weights 0.6 / 0.4; ideals on
pulse, chase, bars ... and twinkle, meteors, fill ...), skipped without stems. `explain
music @T` shows the parts' levels, a drum hit and the bass / melody note there; `inspect
audio` a stems line; the GUI rows for drums (kick low, snare middle, hat high), bass and
melody (higher = higher note; click: the music here; the 'stems' box hides them), and the
magnifier the notes as a piano roll over the waveform with drum ticks on top.

## 6. Music classification (`classify-music`)

**Sections: detection, rules, and the user's edits.**
- **Two detectors** propose candidate boundaries:
  - **novelty:** changes in loudness and tone colour (checkerboard kernel on
    24 log bands, plus energy steps).
  - **Laplacian segmentation** (McFee & Ellis 2014, implemented in numpy in
    `music/laplacian.py`; no librosa needed):
    - beat-synchronous chroma (new in the analyzer) builds a mutual
      k-nearest-neighbour recurrence graph, diagonal-median filtered so
      repeated sequences stand out;
    - beat-synchronous timbre (cepstrum of the log bands) builds a path
      graph linking neighbouring beats;
    - the two graphs are balanced and combined; k-means on the first k
      eigenvectors of the normalised Laplacian (k from the eigengap, 2–6)
      gives a label per beat — the kind of material.
    - Boundaries are label changes, strength = how long the material lasts
      on both sides. The labels are stored too (`segmentation.laplacian` in
      music.json).
- `sections.method` (`preferences/music.json`) chooses between them:
  - `novelty`;
  - `laplacian` (its boundaries snap to the nearest bar line within half a
    bar);
  - **`combined`** (default): candidates from both. Where they agree, the
    stronger evidence counts in full; novelty-only candidates count 80%.
- Tested on two synthetic songs:
  - the demo song (loudness and instrumentation change): novelty and
    combined are exact;
  - a song whose sections differ only in harmony: novelty finds 4 of 6
    boundaries; Laplacian and combined find all 6, plus the exact repeat
    pattern A B A B C B.
- The Laplacian labels are also repeat evidence: sections made of the same
  material repeat each other at a lower similarity threshold.
- Classification keeps the strongest candidates that leave sections at least
  `sections.min_bars` bars long (default 8; the first and last sections may
  be half that). It ignores candidates below `sections.min_strength`. Both
  settings are in `preferences/music.json`.
- **Per-song edits override detection.** They are made with `sections merge`,
  `split`, `move`, `type`, `import` (Audacity labels), and `reset`, and stored
  in `seqtool-prefs/songs.json`, keyed by the audio's sha256.
  - User boundaries replace the detected ones.
  - User types are applied after labelling, with confidence 1.0; they are
    marked `*` in tables and `edited` in the profile.
  - Splits and moves use exactly the time given. The reply names the
    nearest beat and bar; `--snap beat|bar` aligns to them.
  - **Custom type names** are allowed (interlude, setup, instrumental, …).
    `music.section_types` maps each to a known type that effects should
    treat it like; the name itself is kept for display. Defaults cover common
    names (interlude→bridge, instrumental→solo, setup→build, hook→chorus,
    coda→outro, …). Unmapped names score neutrally, and `sections type`
    says how to map them.
  - **Edits are never overwritten by other commands.** Re-analysis, `run`,
    and changes to `min_bars` or `method` all apply edits on top of
    detection. Only `sections reset` and `sections import` replace them,
    and both ask first. Edits are keyed by the audio's content, so if the
    audio itself changes (re-mastered, trimmed), they don't carry over.
- **Scoring detection against your fixes** (0.17.2): `sections score` runs
  detection again without your fixes, for every song you fixed (found through
  your baselines, the current song, and the analysis path recorded with each fix),
  and compares: boundaries within one bar (at least 1 s; 0.17.4 - typed fixes
  are often whole seconds, 1-2 s off the bar line) count as right;
  precision, recall and F1 per song; and for the sections you typed yourself,
  whether detection types them the same on your boundaries. `sections tune`
  tries method x min_bars x min_strength x novelty_weight (180 combinations) on
  all of them, shows the best (ties go to the fewest changes from your
  settings) and asks before saving it. Fixed songs are found by the analysis
  path recorded with the fix, songs named on the command line (`sections score
  'path/*.mp3'`), and next to every song seqtool knows (baselines, the last song);
  any it can't find are named. `sections score --detail` lists, for each of your
  boundaries, the nearest detected one and how far off it is, and whether
  detection had a candidate there that the selection dropped (a settings
  problem) or none at all (a detector problem); a consistent offset and the
  tempo are reported too. `sections --audio SONG ...` works on another song.
  `sections snap [bar|beat]` moves your own boundaries to the nearest bar line
  (asks first). Since 0.17.5 `music.sections.snap` is `bar` by default: split,
  move and import align to the nearest bar line (the user's fixes are approximate);
  `sections` says so and how to change it.
- **Vocal entries as section candidates** (0.17.5, `sections.vocal_entry`, 0 =
  off): where singing starts after at least 2 bars without it (from the vocal
  stem, and from imported lyric lines), the nearest bar line becomes a candidate
  of that strength, or strengthens one already there. Off by default (it
  changed nothing on the tuning songs, addendum A1); `sections tune` tries
  0 / 0.6 / 0.8, so songs whose sections start with the singing decide.
- **Lyric repeats as section candidates** (0.17.6, `sections.lyrics`, 1.0 = on;
  0 / 1 in the tune grid; replaced in 0.18.0 by the word-level version below): with lyrics imported, a line where a repeated block of
  lines begins (another occurrence follows the same lines, but not the line
  before) is a candidate at the nearest bar line, strength 0.3 + 0.1 per
  repeated line (max 1). Lines are compared without punctuation and fillers
  (whoo, ha, oh ...), lines under 3 words are skipped, and a block that repeats
  the block just before it (a doubled chorus) is not a new section (results on
  the tuning songs: addendum A1).
- **Structure from the words** (0.18.0, `music/lyric_structure.py`, with
  `sections.lyrics` > 0 and lyrics of any kind). Works on the word sequence, so
  line splits don't matter (LRC vs Whisper segments); fillers and ad-lib lines
  under 3 words are left out; imported lines without word times are spread at
  most 0.5 s a word. A passage is repeated when 12+ words come back in the same
  order (a pause of 4 bars breaks a passage; copies back to back, A A A, are one
  section going on). Evidence: 'lyrics repeat' (a repeated passage begins),
  'lyrics end' (it ends: what follows is new), 'lyrics stop' (the singing stops
  for 4+ bars), strength 0.3 + 0.02 per repeated word (max 1), 0.5 for a stop.
  Boundaries backed by lyrics only need `sections.lyric_min_bars` (2) between
  them, so short passages the words mark off become sections (e.g. spoken
  lead-ins). Types (`lyric_structure.types`, recorded as `type_why`):
  sections sharing most words with others = chorus (the biggest group); short and
  before a chorus = pre_chorus; the one late stretch with words of its own =
  bridge; other own-words sections = verse; under 0.75 words a bar in the middle =
  breakdown (unless the sound says drop/solo/build); an intro / outro stays unless
  it is the chorus (results: addendum A1). `sections score --detail` lists the evidence
  kind per candidate and each typed section with the reason.
- **Scoring uses the newest analysis** (0.17.6): when several music.json files
  of a fixed song are found, `sections score` / `tune` use the newest seqtool
  version (with a vocal stem preferred), and name analyses from an older
  major.minor with the `run --audio SONG --stems` that refreshes them.
- **Real songs** (addendum A1 has the measurements): boundaries placed exactly
  are detected exactly; the misses are approximate fixes or sections shorter
  than min_bars, and the tune grid's defaults hold. Tried and dropped: moving each
  boundary to the bar line with the biggest before/after contrast, and choosing
  boundaries by dynamic programming with a section-length prior.
  `novelty_weight` (0.8) is the credit a
  novelty-only candidate gets in the combined method (was a fixed 0.8).
- The profile records the rules and an edits hash, so the pipeline rebuilds
  it when either changes.
- `classify-music` with no argument uses the most recently analysed song. It
  prints the section table and a hint showing how to fix sections.

**How style is used (currently).**
- Styles are scored by rules from absolute measurements: tempo, loudness,
  dynamic range, beat salience, spectral balance, brightness, and vocal
  level when present. These rules are crude and meant to be replaced.
- **Effects:** each effect has `style_affinity` scores in effects.json.
  `style_fit` is their average weighted by the song's style scores. It is
  10% of the static score, against 28% for music fit, 22% each for prop
  type and section fit, and 18% for geometry. So style nudges effect choice;
  it doesn't drive it.
- **Colours:** palettes.json lists palettes per style. Only the single
  highest-scoring style with a palette entry is used; there is no blending.
  The seed picks one of its palettes and a colour rotation. Segments with
  energy ≥ 0.75 use an accent palette: the first three colours plus white.
- **Character** scores (energy, danceability, dramatic, peaceful) are
  computed but not yet used by the matchup.

The classifier uses deterministic, replaceable rules.
- **Styles and character:** open-vocabulary 0–1 maps, computed from absolute
  summaries (loudness, dynamic range, tempo, beat salience, spectral balance,
  vocal level).
- **Sections:** built from the analyzer's boundaries.
- **Repetition:** cosine similarity of z-scored section feature vectors plus an
  energy check.
- **Labels:** the most energetic repeated cluster is the chorus; other repeated
  material is verse; the ends are intro and outro; a lower-energy section
  before a chorus is pre_chorus; other singletons are bridge, breakdown, or
  drop. Confidences are modest.
- **Incoming transition strength:** combines the boundary novelty, the energy
  jump, and whether the section type or repeat group changed.

## 7. xLights adapter

**Input:** `xlights-import` reads xlights_rgbeffects.xml and writes layout.json (§4).

**Output:** `xlights-export` writes matchup.json to .xsq (also stage 8 of
`run`). The XSQ encoding is **learned, not hand-coded**:
1. The user teaches seqtool their xLights version with the **live kit
   wizard** (`seqtool xlights-kit [--dir DIR] [--fresh]`). It uses **one
   training file** and gives immediate feedback after every save:
   - **Step 1:** the user creates an empty Animation sequence and saves it at
     the path the wizard shows. xLights' default length (30 s) is plenty,
     because the effects can all be edited in place. The folder is asked once and remembered; it
     may be the show folder. That first save reveals the xLights version and
     frame timing.
   - **Every further step** is one small edit in xLights followed by Save.
     The wizard polls the file (no extra packages), waits until the write
     settles, parses it, and checks the current step:
     - It prints ✓ and the next step, or ✗ with what's wrong (e.g. "the new
       effect is 'Bars', expected Color Wash", or "3 colour(s) enabled").
     - It then waits for the next save.
     - Keys while waiting: Enter = check now, `s` = skip, `b` = back,
       `a` = accept anyway, `q` = quit.
   - **Add steps** look for a new effect of the expected type, compared with
     the previous save. The name is matched loosely (it is stored as
     `SingleStrand`), and the stored name and default settings are recorded.
   - **Change steps** use the right-most effect of that type. The settings
     are compared with both the previous step and the effect's defaults, and
     the smaller non-empty difference is kept. So the user may keep editing
     the same effect, or add a fresh copy (continued or reset) each time.
     - Unchanged settings, or still at defaults, means "wait".
     - **Primary vs companion settings:** a key whose value changed is the
       primary change. Keys that only appear or disappear are companions:
       settings xLights adds or hides when an option enables extra controls
       (Bars "expand" adds `Bars_Center=0`; Meteors "Explode" adds X/Y
       offsets and FadeWithDistance). They are recorded with the primary
       change, and the exporter writes them alongside it, as xLights does.
       They never count as extra changes.
     - More than one primary change is reported by name; the user can undo
       the extra change and save again, or press `a`.
     - On a max/min step, a blank or non-numeric value is rejected, with a
       hint to use the highest value that still shows. (In 2025.13 the
       Color Wash Count field blanks out above 9.9.)
     - Wording: "set to its maximum"; "set to its minimum (or max negative)
       value"; "turn on, or set to its maximum" where a control may be a
       checkbox; "Direction/Effect" where the direction lives in an Effect
       list.
     - The user's real chase.xsq (reset style) replays cleanly in the tests.
   - **Structure steps:**
     - a Color Wash with exactly red, green, blue enabled;
     - two layers on one model;
     - an effect on a model group (verified against an
       xlights_rgbeffects.xml found near the file, otherwise accepted with a
       note);
     - **any new timing track** with at least 3 marks. The name doesn't
       matter, and a metronome track works. "New" means not present, or with
       fewer marks, when the file was created. If none is found, the message
       lists every timing track and its mark count.
   - Progress is saved after every check (`kit-session.json`); a later run
     offers to resume. `--fresh` (or deleting `kit-session.json`) starts
     again at step 1, and waits for a new save even if an old training file
     exists.
   - **At the end**, the observations are written to
     `seqtool-prefs/xlights-learned/<version>/observations.json`. For each
     effect they hold the stored name, the defaults, and the setting keys and
     values each parameter changes; they also hold the structure findings.
     The working file is kept as `reference.xsq`, a skeleton for the
     exporter. The wizard then offers to delete the working file and its
     .xbkp backups, and (0.19.4) the .fseq xLights rendered from it - next to it
     or in an fseq folder beside it or in the show folder.
   - Learned folders are per xLights version. Shipped ones live in
     `adapters/xlights/learned/<version>/`; the user's take priority. The
     exporter uses the exact version, or the nearest older one with a
     warning.
   - Without a terminal, the wizard prints the numbered step list.
   - An existing real sequence can serve as a second reference.
2. **Encoding** (`adapters/xlights/encoding.py`): the learned
   `observations.json` for the chosen xLights version (exact version, else
   the nearest older one, else the newest) supplies, per generic effect:
   - the stored effect name;
   - the default settings;
   - for each kit step, the primary key, its default and extreme values, and
     any companion settings.

   `param_map.json` says how each generic matchup parameter uses those
   steps:
   - **`scale`:** the value v (0..1) is placed between the default and the
     learned extreme. Checkbox-like 0/1 settings turn on at v ≥ 0.5.
   - **`span [a, b]`:** only that fraction of the default→extreme range is
     used. Kit extremes are slider limits, far beyond musical values (Chase
     Rotations max 50).
   - **`per_10s`:** for settings that count repetitions over the whole
     effect (Rotations, Cycles, Count), the value is computed for 10 s and
     scaled by the effect's real length, so speed stays consistent across
     segment lengths.
   - **`choice`:** generic value → kit step (e.g. chase reverse → "Chase
     Type: Right-Left"). Unlearned choices fall back to the default.
   - When a choice step and a scale parameter set the same numeric key, the
     choice only supplies the sign (Spirals Movement).
   - Companion settings are written with the primary change.
   - The palette string follows the learned palette format.
   - **`rate`** (replaces fixed limits for repetition counts such as
     Rotations, Cycles, and Count): the parameter picks a rate per `second`,
     `beat`, or `bar` from a range, and the setting is that rate times the
     effect's length in those units. A 2-bar chase and a 60 s sign border
     therefore move at the same musical speed. Defaults: chase 0.25–2
     rotations per bar, bars 0.125–1 cycles per bar, color wash 0.05–0.5 per
     bar, shimmer 0.5–4 per beat. Results above the learned slider maximum
     are clamped.
   - **`assume`:** values xLights doesn't store are supplied here. These are
     defaults it omits (Color Wash and On save nothing at defaults) and
     fields saved blank at maximum (Color Wash Count above 9.9, Fire Growth
     Cycles). `inspect xlights` lists every assumption.
   - Older kit files (v4: one `changes` map per step) are read by splitting
     them into primary and companion settings on load.
   - Users override spans, rates, assumptions, and mappings in
     `seqtool-prefs/xlights.json` under `param_map`.
3. **Writer** (`seqtool xlights-export`, and stage 8 of `run`/`demo` with
   `--rgbeffects` once a kit exists):
   - The training file (`reference.xsq`) is the template, keeping the root
     attributes, head fields, DataLayers, and the rest.
   - It sets the version, Media type, absolute media path, duration, and
     frame timing.
   - It rebuilds ColorPalettes and EffectDB (both de-duplicated),
     DisplayElements (timing tracks first, then targets in the user's default
     sequencer view order), and ElementEffects. Effects carry
     ref/name/id/startTime/endTime/palette, with every time snapped to the
     frame interval and no overlaps within a layer.
   - It adds timing tracks `seqtool-sections` (labelled "#3 chorus"),
     `seqtool-bars` (labelled with the bar number) and `seqtool-beats`
     (labelled with the beat number in the bar, 1-4, usable as states),
     for easy hand editing. Which ones is set by `xlights.timing_tracks` or
     `--timing sections,bars,beats|none`.
   - xLights only shows a timing track in a view that lists it. The tracks
     get the `views` list of the training file's timing track (so they
     appear wherever that one did); the export says which views, or reminds
     the user to add them to the Master View (View > Display Elements).
   - Layers: xLights draws the first EffectLayer on top, and the upper layer
     wins. Generic layer 0 (the normal plan) is written last, so higher
     generic layers (e.g. `react --over`) sit above it.
4. **Check:** the written file is read back. Every effect name must be
   learned, every effect must have settings, nothing may run past the song,
   every element must exist in the layout, and no layer may overlap.
   Problems are listed. Opening the file in xLights is the final check, and
   is done by the user.

## 7a. Seeds, rerolls, pins, continuity, presets, lyrics and name rules

(This section grew with each release; it holds the per-song controls and the
music-driven features. §8 has the scoring itself.)

All randomness in the matchup comes from named sub-seeds:
sha256(master seed + names) → 64 bits. There is no shared generator, so
adding a prop or effect never shifts any other decision. It is used in three
places:
- score jitter (±`random_amplitude`), named by target, section repeat group,
  and effect;
- choice parameters such as direction, named by target, effect, repeat
  group, and parameter;
- the palette pick and rotation, named by style.

Repeat groups are the unit, so repeated sections share their random choices.

**Per-song seeds** (`seqtool-prefs/songs.json`, keyed by the audio sha256):
- The default seed is derived from the audio, so songs differ but are
  reproducible. `--seed` on run/match/demo sets and remembers it.
- **Overrides** apply to one target, one section, or one target in one
  section: `MegaTree`, `@S03`, `MegaTree@S03`. The most specific wins.
- The seed and overrides appear in `inspect audio`, the summary file, the
  matchup settings, and the .xsq comment.

**`reroll [TARGET] [@#N|@TIME] [--seed N] [--undo]`:**
- It sets a new seed for that scope; a section also covers its repeats.
- It re-runs the last `run`/`demo` quietly, reusing the analysis.
- It prints what changed: effect changes per target and section, how many
  segments got new settings only, and whether the palette changed.
- `--undo` pops a per-song history.

**Pins** (0.16, `pin` / `unpin`; per song in songs.json):
- `pin TARGET @#N|@TIME [EFFECT] [--only]` keeps the current effect there (or
  forces EFFECT, including `dark` and `transparent`); `pin TARGET EFFECT` holds
  for the whole song; `pin` lists them; `unpin TARGET [@...]` / `unpin --all`.
- A pin records a moment of the song (the section's middle for `@#N`), not a
  section number, so it survives section edits; it covers the sections that
  repeat that one unless `--only`. A layer of a later pass is named as the
  timeline shows it: `pin "MegaTree (enhance)" @#3 dark`; `unpin MegaTree`
  removes the pins on all its layers.
- The matchup forces the pinned effect in those decision windows (every other
  choice gets -10 there), so pins survive rerolls, new seeds, feedback and
  re-analysis. Explanations, alternatives and the critic use the real scores.
  An effect that isn't possible there (gated, unknown) is reported, not forced.
- After a change the last run is repeated quietly and the change is shown.
  Pinned segments carry `pinned: true`; `explain` says so and how to unpin;
  the timeline marks them with a corner tag. Targets that now rest (e.g. while a
  top group plays) are summed up in one line per section.
- **Which layer a pin goes on** (0.19): the one the target is sequenced in.
  - A **top group** (`pin 1.ALL @1:08 color_wash`): pass `top`. The pinned
    moments are added to the sections the top group plays (intro / outro), so it
    takes over there and its members rest; a pinned `transparent` gives an intro
    or outro back to the members. Before 0.19 such a pin went to a pass the group
    isn't in and changed nothing ("no visible change").
  - A **prop that a group sequences** (`pin Tree @1:08 dark`, Tree being part of
    5.Tree+Star): pass `pin`, a row of the prop's own that plays only where
    pinned; the exporter writes these rows after the group rows, so they win in
    xLights (later rows win) - the rest of the group keeps playing. Such a pin
    needs an effect (`transparent` on that row would change nothing, so it is
    refused); for the whole group, pin the group. `explain Tree @T` outside the
    pins explains the group.
  - A segment pinned on a member keeps playing where a top group takes over.
  - Name a layer to choose it: `(main)`, `(top)`, `(pin)`, `(detail)`, `(enhance)`.
- A pin that ends up nowhere (its target isn't sequenced in that pass) is said,
  with the reason and `unpin`, instead of silently doing nothing.

**Best of several seeds** (0.16, `run --candidates N`, default
`scoring.critic.candidates` = 1). Each seed runs the full match/validate
rounds in memory; a show critic (`matchup/critic.py`) scores each final plan:
- fit (duration-weighted mean static score of lit main-pass segments);
- variety (per target, 1 - the largest share of its lit time one effect takes);
- repeats (repeated sections that repeat their first occurrence: exact 1, most
  targets 0.5);
- issues (validator warnings; errors count 3).

score = fit + 0.3 variety + 0.3 repeats - 0.02 issues (weights in
`scoring.critic`). All candidates are listed; the best is written and becomes
the song's seed (`reroll --undo` goes back). Seeds are the song's own plus
`sub_seed(seed, "candidate", k)`. Overrides and pins apply to every
candidate. Reruns by `reroll`/`pin` drop `--candidates`, so they keep their seed.

**Continuity weighted by musical contrast.** The cost of changing effect
falls where the music itself changes, not only at section boundaries.
- For each prop, a characteristic's importance is how differently its
  candidate effects respond to it (the spread of their ideal levels).
- The change between neighbouring decision windows is the importance-weighted
  feature difference, divided by this song's own large changes (the 90th
  percentile), so the song's biggest changes make switching nearly free.
- It is combined with the section-change strength as independent evidence:
  1 − (1 − section)(1 − contrast).
- `continuity.contrast_relief` (0 = off) and `contrast_reference` tune it.

In the user's example, a high-energy chorus after a verse now switches
effects where the better fit was previously lost to continuity.

**Music-reactive targets and presets** (`react TARGET PRESET[,PRESET...]
[--over] | off`). These targets get effects triggered by musical events
instead of effects chosen per section. What happens on each event is a
**preset** (`preferences/presets.json`; the user's own go in
`seqtool-prefs/presets.json`; `presets` lists them, `help presets` too):

| Key | Meaning |
|---|---|
| `on` | the trigger: `beat`, `downbeat`, `onset` (peaks of the onset curve), `section`, `lyric` (each line), `word` |
| `when` | conditions that must all hold at that moment: `{"section": ["chorus","drop"], "energy": ">=0.6", "downbeat": true, "beat": [1,3]}` |
| `every` | only every Nth matching event |
| `split` | divide each event into N equal steps (`on: downbeat` + `split: 8` = eighth notes in 4/4) |
| `keyframes` | CSS-style steps anywhere in the event, for syncopation (below) |
| `effect` | any generic effect (`effects` lists them) |
| `params` | per parameter: a constant, `{"from": "energy", "range": [lo, hi]}` (driven by the music), `{"if": {…}, "then": a, "else": b}`, `{"cycle": [a, b]}` (next value per event), or `{"step": [a, b, …]}` (by position in the bar: a step sequencer) |
| `palette`, `colors` | base/accent (or an `if`); `colors: "cycle"` = one palette colour per event |
| `max_length` | cap in seconds; otherwise an event lasts until the next one |

Values available to `when` and `from`: energy, energy_end, onset,
brightness (any analysed `*_norm` level), downbeat, beat (number in the
bar), bar, step (position in the bar in split steps), section, section_index,
time, index.

**Keyframes** (CSS `@keyframes` conventions). `split` divides events evenly;
syncopated rhythms need steps at uneven points, so a preset can instead give
`"keyframes": {"0%": {…}, "37.5%": {…}, "62.5%, 87.5%": {…}, "to": {…}}`.
Selectors are percentages of the event (in a 4/4 bar each beat is 25%),
`from`/`to`, or comma lists; declarations are parameter values (the same forms
as `params`) and carry over to later keyframes. A step lasts until the next
keyframe. `animation-timing-function` (per keyframe, or for the whole preset)
says how a step reaches the next keyframe's values: `linear`, `ease`,
`ease-in`, `ease-out`, `ease-in-out`, `cubic-bezier(x1, y1, x2, y2)`,
`steps(N)`, or the default `step-end` (hold). Unlike CSS, holding is the
default, because lighting cues usually snap. Glides become ramps
(`{"ramp": [a, b]}`); curved glides are split into three linear pieces. The
exporter writes each glide as a run of short effects stepping from a to b
(one per 0.1 s, at least a frame, at most 12 per piece). Value curves are not
used: they are specific to each setting, so one learned example doesn't carry
over, and keyframe easing covers what they would do here. `step` counts
keyframe steps. Examples: `tresillo` (3+3+2 hits) and `spoke-bounce` (a fill
level that drops on the downbeat and bounces through the bar).

`split` + `step` cover even patterns within a bar without scripting. Example: a
spinner spoke that is down on the downbeat and then moves up and down
through the bar would be `on: downbeat, split: 8, effect: fill,
params: {position: {"step": [0, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8]}}`,
targeted at the spoke submodel. Two pieces are still missing for that
example: submodels as targets (detail pass) and a level/position effect
(xLights Fill) in the kit; both are now built (rev 23), and `spoke-bounce`
does it with keyframes and glides.

A target can list several presets. This works like conditional formatting:
earlier presets win, so a later preset's event that starts inside an earlier
one's is dropped, and one that runs into it is cut short. Example:
`react Arches chorus-beat-chase,beat` gives beat chases in choruses and
drops, and plain beat flashes elsewhere.

Built-in presets: the original modes `beat`, `downbeat`, `onset`, `energy`
(all `pulse`, unchanged results), plus `beat-color`, `beat-chase`,
`downbeat-wipe`, `onset-sparkle`, `energy-speed` (speed follows loudness),
`energy-color` (accent palette when loud), `energy-density`, and
`chorus-beat-chase` (an example of `when`). So a reaction is not tied to a
flash: energy can drive speed, brightness, density, or colour.

- Without `--over` the reactive plan replaces the normal one. With `--over`
  it goes on generic layer 1, which the exporter writes as the top xLights
  layer.
- The validator doesn't apply the short-effect and change-rate checks to
  reactive plans. `explain` describes the presets, the one that fired at
  that moment and its parameter values, and whether a name rule set it.
- New generic effects (rev 23): `fill` (a level/position: xLights Fill) and
  `vu_meter` (xLights draws the audio itself: spectrogram, level bar,
  waveform - an EQ look). Both need `xlights-kit --update`. Piano is still
  out: it needs per-note pitch, beyond the chroma we have.
- Onsets on submodels: react on a submodel (or a group of them) works now.

**Lyrics** (`lyrics transcribe`, `lyrics align`, `lyrics import FILE`).
Since 0.18.0 lyrics can come from the singing: `lyrics transcribe` runs
faster-whisper (MIT; installed on demand, model downloaded once, `--model
tiny..large-v3`, default small, then the one used last, `--language`; a model not
downloaded yet is offered for download, an unknown name lists the valid ones and
the downloaded ones; `lyrics models` lists them with sizes; on the CPU (int8; the
GPU with float16 when CTranslate2 sees CUDA) a model needing more memory than is
free (`MEMORY_GB`) asks first, naming the largest one that fits; progress as
percent with time so far / to go, from the segment end times against the song
length - one line rewritten on a terminal, every 10% in the GUI) on the vocal stem when there is one
(else the whole mix), with word times; the transcript is kept in songs.json
(`transcript`) so it is made once. Transcription never replaces lyrics you gave.
`lyrics align FILE` takes your lyrics as plain text (blank lines and [Chorus]
headings dropped) and times them from the transcript (`music/transcribe.py`:
difflib on normalised words; matched words take their times, misheard ones the
time the transcript's words took, missing ones are spread between neighbours;
the share recognised is reported, a warning under 50%; see "Transcription
checks" below for 0.19.4); `lyrics align` alone
re-times the stored lines; `lyrics import` of a text without times aligns it.
Timed lyrics are also imported from an LRC file (`[mm:ss.xx]line`, enhanced `<mm:ss.xx>word`
timings, `[offset:±ms]`) or Audacity labels (one line per label, or one word
per label grouped into lines at pauses, `--as words|lines`). They are kept per
song (songs.json, keyed by the audio), and feed: the `seqtool-lyrics` timing
track (a phrase layer, plus a word layer when words are timed); presets with
`on: lyric|word` and conditions on the text (`{"lyric": "~(?i)merry"}`, ~ =
regular expression); and `explain music`. The matchup records the lyrics
hash.

**Transcription checks** (0.19.4, after the user saw Whisper `medium` drop whole
sung passages and `lyrics align` recognise under half of their own words):
- **Sung passages without words.** With the vocal stem analysed, `lyrics
  transcribe` knows where the singing is (vocals or mixed passages) and names
  every passage of 1.5 s or more that the first pass left without a word. The
  likely cause is the voice filter (Silero VAD, on in the first pass so the quiet
  parts don't fill with invented words): it is trained on speech and can cut
  singing it doesn't take for a voice, before Whisper hears it. Those passages are
  then transcribed again, each on its own (cut from the audio with
  faster-whisper's `decode_audio`, 0.5 s either side) and without the filter;
  segments Whisper itself rates as no speech (no_speech_prob > 0.8 and
  avg_logprob < -1) are dropped; the words are put back on the song's clock and
  marked `refilled`. `--no-refill` skips this, `--no-vad` turns the filter off
  for the first pass too.
- **`lyrics transcribe --diagnose`** writes `<song>-seqtool/<song>.whisper-log.txt`:
  every segment with avg_logprob, no_speech_prob, compression_ratio and
  temperature (refilled ones tagged), and the passages without words after the
  first pass and after the refill - so a drop can be told apart: no segment at
  all there (the filter cut it) or a segment rated no speech / unsure.
- **Long segments are split** (0.19.5): a Whisper segment can hold two sung lines
  20 s apart (the user's 0:17.8-0:39.3); a refilled passage then sat inside it and
  the phrases interleaved. Lines are now split wherever their words pause for
  more than 1.2 s, so lines never overlap (re-transcribe to apply it to a stored
  transcript).
- **Stretched words** (0.19.6, the user's 0.19.5 log against the LRC): pauses
  alone didn't split everything, because Whisper stretches a word over the music:
  'That melody ...' (sung at 2:19) started at 1:48 - its first word lasting 31 s
  - and a word inside 0:17.8-0:39.3 ran over the 15 s before 'I hear ...' (36.4).
  A word lasting more than max(3 s, 6x the song's median word) is shortened to a
  usual word's length: at its start when it opens a line or a phrase (a capital),
  else at its end (`unstretch`). This runs before the passages without words are
  looked for, so the refill now also gets what a stretched word hid.
- **Untangling** (0.19.6): after the refill all words of both passes go in time
  order and each line is a run of its own words (`untangle`): a refilled line
  inside a first-pass one cuts it in two, a word heard by both passes at the same
  moment is kept once, and no line overlaps the next. The refill shows its own
  progress ("Whisper, again"). The `--debug` log ends with the lines as kept,
  each word with its time.
- **Timed lyrics** (0.19.5): `lyrics align FILE` reads an .lrc (or Audacity
  labels) as lyrics - before, its `[00:01.12]` stamps were taken as words, which
  is why the user's LRC scored 55%. The file's line times then help twice: a word
  only pairs with a heard word within 8 s of where the file puts it (so a phrase
  sung six times pairs with the right repeat; the plain alignment is computed
  too and the one pairing more words is kept), and the first word of a line that
  wasn't recognised starts at the file's time instead of being spread between
  neighbours. Fillers (whoo, ha, oh ...) don't count against the share and aren't
  reported; 'ya' = 'yeah', 'all right' = 'alright' and a few such variants match.
- **Timing from the phrases** (0.19.7, the user's design; `music/lyric_timing.py`) -
  the default for lyrics with line times (`lyrics import FILE.lrc`, `lyrics align
  FILE.lrc`, `lyrics align` on lyrics imported so). Whisper isn't reliable through a
  whole song (the user's 0.19.6 logs: medium and large-v3-turbo alike put "I" of
  "I hear some more beats" 17 s before "hear"), while an LRC's line starts are. So:
  each line starts where the file says; it ends where the vocal stem shows the
  singing stop before the next line (breaths over 0.3 s kept; the end is the
  first pause over 1.5 s once half the words' natural length has been sung, and
  never more than max(3x, +3 s) that length: an instrumental with stem bleed is
  not sung); with hardly any singing found, or no stem, after the words' natural
  length (x1.3), never past the next line. The words' sounds (ARPAbet with stress,
  the same dictionaries as `lyrics phonemes`; `Dictionary.lookup_stressed`) share
  the sung time: each consonant its spoken length (stops 70 ms, fricatives 100 ms,
  nasals / liquids / glides 80 ms, CH 110 ms, HH 60 ms; scaled down when they would
  take over half the time), the vowels the rest by weight - stressed 1, unstressed
  0.5, diphthongs x1.2 - so a held note stretches its vowel; the time is laid only
  on the sung stretches, so nothing lands in a breath. Each word stores `sounds`
  [[ARPAbet, start, end], ...]; `phonemes.for_words` uses them as they are (one
  mark per mouth, merged when a mouth repeats, nothing shorter than a frame). No
  transcription is needed. `--times heard` keeps the Whisper-based alignment.
- **Dangling words** (0.19.7): when a Whisper line is split at a pause, a piece
  ending on a word a sung phrase doesn't end on ("I", "the", "to", "my", "gonna"
  ...; `DANGLING`) gives it to the next piece, just before it.
- **Whose times** (0.19.6, the user's question; 0.19.7: `--times heard`): with `--times heard` a
  recognised word keeps the time it was sung - Whisper's word times are closer
  than a lyrics site's line times - and the file's times place the rest (0.19.6's
  `--times file`, heard times inside the file's lines, became the phrase timing
  above in 0.19.7). A file early or late all through (another edit of the
  song) is shifted first: the median difference of the pairs, when it is 1 s or
  more, is said and applied. The plain (time-blind) alignment now wins only when
  it pairs 15% more words.
- **Alignment** (`music/transcribe.align`): words are compared without
  punctuation or apostrophes of any kind (a lyric site's curly ’ didn't match
  Whisper's '), hyphenated words count as separate words, and nearly-equal words
  (flappin / flapping) count; the words are aligned globally (Needleman-Wunsch)
  instead of difflib's greedy longest match, which a repeated chorus could pull
  out of order. After aligning, the stretches of your words that were not
  recognised are listed (always under 90%; all of them with `--report`) with
  their time, what was heard there, and why: heard differently, not heard (the
  transcript skips them), or nothing transcribed there (the transcription dropped
  that part - see above).
- **`lyrics phonemes`** says how many sung words came from where, then the
  different words it had to guess (one guessed word sung twice counts once) as
  lines to correct in a {copy} block, then the first lines word by word with
  each word's mouth shapes. Doubled consonants in a guess are one sound
  (flappy = F L AE P IY).

**Name rules** (`models.json` `rules`, the `rules` command). Settings by
naming convention: a regular expression searched in each model or group
name, with optional `kind` (model/group), and any target setting:
`effect_preferences` (multipliers), `allowed_effects`, `react`/`react_over`,
`role`, `enabled`, `drive_individually`.
- Every matching rule applies, in order. Preferences multiply; other
  settings are replaced by later rules. Settings for a target by name win.
- This gives default reactivity by naming convention (`rules add '(?i)^arch'
  kind=group react=beat-chase over=yes`) and affinity tweaks (`rules add
  '(?i)flood' prefer=color_wash*1.5`).
- Interference with matching: a preference multiplies the static score
  (the "x user preference" line in `explain`), so it biases the choice but
  leaves model fit, music fit, continuity, and the feedback loop working.
  Large multipliers effectively force an effect wherever it is allowed; 0
  excludes it (a hard gate). `rules test PATTERN` shows what a pattern
  matches before it is used.

## 8. Matchup and scoring (`match`)

For each target × decision window × candidate effect:
1. **Hard gates.** The effect is dropped if any of these fail: it's in the
   allowed list, it isn't disabled, it meets the `hard_min` capabilities, its
   preference is above 0, and the current layer permits it.
2. **Static score.** A weighted mean of `model_fit` (class table),
   `capability_fit` (geometric mean of requirement ratios), `music_fit`
   (similarity to ideal feature levels), `style_fit`, and `section_fit`
   (blended toward neutral by label confidence). The result is multiplied by
   the user preference, then seeded jitter of ±0.03 is added. Weights live in
   `preferences/scoring.json`.
3. **Temporal choice.** A Viterbi pass per target. Staying with an effect earns
   a small persistence bonus. Changing costs
   `penalty × inertia(prev) × family_factor × (1 − relief × transition_strength)`,
   so strong musical boundaries make change cheap.
4. **Motifs.** Repeated sections share emissions position by position. A
   second pass also adds a motif bonus for the effect the section's first
   occurrence used, so chorus 2 looks like chorus 1.
5. **Parameters.** Abstract parameters (`speed`, `direction`, `width`, …) are
   computed from window features. Seeded choices are keyed on the repeat root.
6. **Palettes.** Chosen deterministically from the dominant style. An accent
   palette is used for high-energy segments.

**Decision windows** are cut at every section boundary, then on downbeats,
toward roughly 4 s each (minimum 1.5 s, maximum 8 s).

**Groups are first-class targets.** Every group has a **role**:
- `top`: apply effects to the whole set first, as a top-down base layer.
- `unit`: sequence the group as one target in the main pass.
- `detail`: a collection (often of submodels) used to reshape or re-order
  props, handled in the per-prop detail pass.
- `unused`: not sequenced (called `off` before 0.17; old `off` roles are still read).

Defaults come by kind (`preferences/models.json` `group_roles`): leaf → unit,
single and empty → unused, and **umbrella and submodel_view → `auto`** (0.16): the
role is guessed from the layout when models.json is built (`role_guess`):
- an umbrella group with at least 90% of the yard's lights → top ("whole yard");
- an umbrella group with exactly the same props as a larger one → unused ("same
  props as 1.ALL"; real layouts often have such duplicates, e.g. 9.ALL-LAST);
- other umbrella groups → top ("part of the yard, N%"); the top pass uses the
  largest `max_groups`, and the top-down base pass (planned for 0.20, §13f) will
  use the rest;
- submodel groups → **unit** (0.20.5; detail before): the group is sequenced as
  one in place of the props its parts belong to (members are flattened to the
  parent props, so a prop is planned once - the user's floods 01-13 were getting
  effects of their own although groups of their submodels covered them). Set
  `pref group_roles.submodel_view = detail` for accents on top of the props instead.
- reasons say what the role does with the group, with its size (0.20.5; "part of
  the yard" said nothing - everything is): "the whole yard (N props in K groups,
  P% of the lights): takes over the intro and outro", "over N props ...: can take
  over whole sections in the top pass when it is the widest", "N props: sequenced
  as one, in place of the props themselves".
- `groups` prints a short guide to the roles before its numbered table, then asks
  "Change any roles?": groups are picked in any order by number, name, part of a
  name, `3,7` or `3-6`, each followed by t/u/d/n; Enter finishes (0.20.5, random
  access - before, every group was asked in turn). `groups NAME` shows one group:
  role and why, the groups in it, its parts, its props (not sequenced ones marked)
  and the groups it is inside. 0.20.6: every list in full (parts were cut at 12,
  props at 30), wrapped; part of a name shows every matching group (8 in full,
  the rest by name); a prop's name (`groups Flood01U`) shows the groups it is in
  and the groups its parts are in (a submodel with `PROP/PART`).
  0.20.7 (the user's rules): a prop's groups are listed **closest first** - "in:"
  the groups that list it (or its parts) themselves, then "inside those", "2
  levels up" ... (`containing_groups`, models/analyze.py, by `child_groups`; a
  group that reaches the prop through a group in it counts at that distance).
  Long lists stop at `models.json max_list` (default 8) with "... and N more";
  `groups NAME --all` (or max_list 0) shows everything.
- **Only the widest top group plays** (0.20.8, said in the `groups` guide and help,
  the umbrella reason, models.json `_doc`): the top pass takes the widest
  (coverage, then level, then size) and, with `scoring.passes.top.max_groups` 1
  (the default), no other. After the table, `groups` names the top pass's group and
  warns about each group made top by you or a name rule that it won't use - nested
  in it ("it is inside 1.ALL"), overlapping it, or past max_groups - with the
  command to make it a unit instead. Guessed (auto) umbrella tops get no warning:
  they are many, and they play as units for loose props. `rules add ... role=top`
  matching several groups says the same.
- **Patterns and names starting with '-'** (0.20.8, the user's report: `rules add
  '-all$' role=unit` was taken for an option): `common/args.dash_words` puts `--`
  before a word that starts with '-' but is no option of the command (or moves it
  after the options); used by `rules`, `groups` and `models`.
- **Loose props go to the closest umbrella** (0.20.7, the user's report: floods,
  spinners, sheep and wise men each got their own effect although groups held
  them - their groups were umbrella groups, role top, used only by the top pass).
  After the unit groups are chosen, props that no unit covers are planned
  through the smallest umbrella group (role top by guess, not set by you, not the
  whole-yard / top pass's group) whose sequenced props are all still loose; it
  plays as one in place of them. `models.json loose_props_to_umbrella` (default
  true) turns this off. The top pass skips a group already planned this way.
- **Why a prop plays on its own** (0.20.7): a prop planned on its own while
  groups hold it gets `why_target` on its plan, shown at the end of `explain
  PROP @T` (and the GUI's explanation): its groups, closest first, each with why
  it doesn't carry the prop ("top pass only; some of its props are already in
  X", "overlaps unit group X", "one prop: the prop itself", "role unused"), and
  how to make the closest group a unit. A fallback umbrella says it plays in
  place of its loose props. Props in no group get no note.
- a group with nothing seqtool can sequence → unused, with the reason in a few
  words (0.19.8, the user's wording rule - not "nothing usable"): "no props added
  to it", "only groups in it, used on their own", "its props are excluded",
  "only parts of props (submodels) and groups in it", "its props are marked not
  controllable" / "its props are POINT props, not sequenced yet", "one prop:
  sequenced as the prop itself", "a POINT group isn't sequenced as one yet; its
  props are, each on its own".

**Naming conventions** (0.17). A leading number in a group name ("1.ALL",
"5.Spinner-spokes") is the group's level, as xLights users number groups to
order them: a smaller number is a higher-level group. Groups with the same props
keep the lowest level (9.ALL-LAST is unused because 1.ALL exists), and the top
pass prefers the widest, then the lowest level. A flat group (made of props, not
groups) covering 90% of the lights is also the whole-yard top group, not one big
unit. A group named `...-all` (also `_all`, ` all`; preference
`xlights.umbrella_name_patterns`) is an umbrella group - over the others, planned
as part of the yard - even when xLights lists props rather than groups in it
(the user's convention, 0.19.9); a rule with `group_kind=` still decides.
**Name rules can say what kind a group is or what it is for:**
`rules add '(?i)-all$' kind=group group_kind=umbrella`, `rules add '^1\.'
kind=group role=top`; `groups` marks rule-set kinds with `*` and says "set by a
name rule". The role "off" is now **`unused`** (not sequenced), so "off" never
means two things; old `off` roles are still read.

A role set by the user (`targets.<group>.role`) always wins. `seqtool groups`
(the stored layout by default) lists every group, sorted by name (numbers as
numbers), with its role and why, then
asks once whether the roles are right; "n" goes through the umbrella and
submodel groups one by one (Enter keeps the shown role, `a` accepts the rest).
Answers are saved to the user folder; `--list` only prints the table; `explain
GROUP` shows the role and why.

Target selection for the main pass works in four steps:
1. Only groups with role `unit` are considered as units.
2. Candidate groups are taken largest first, skipping any that overlap a
   group already chosen, so no pixel is driven by two plans.
3. Members of a chosen group are not also driven individually unless the
   preferences ask for it.
4. Every other usable model gets its own plan.

Every skip is reported with a reason. Umbrella groups (whole-display) and
submodel views (spokes, rings) are natural targets for later passes (§9).

## 9. Passes and layers

All passes are built (rev 23). Each can be switched off and tuned in
`scoring.json` `passes`; `explain` labels every layer with its pass.

| Pass | Targets | What it does | Where it goes in xLights |
|---|---|---|---|
| **main** | role `unit` groups, standalone props | the section-level plan (§8) | layer 1 of the target's row |
| **top** | role `top` groups (e.g. an ALL group), largest first, `max_groups` (1) | in sections of `passes.top.sections` (intro, outro) the whole group gets one effect; every target made of its members is cut out of those sections (`rests` in the plan) | its own row, placed first |
| **detail** | role `detail` groups (groups of submodels, e.g. spokes or rings) and submodels you enable | accent effects only (effects whose `layers` include 1, plus transparent); `complement` (0.6) scales an effect of the same family as the parent shows at that moment; `rest` (1.2) favours transparent | groups: their own row, placed last; submodels: a submodel row inside the parent |
| **enhance** | the `focal_count` (2) largest standalone props, plus any with `enhance: true` | a second layer of accents, only where energy ≥ `min_energy` (0.6), complementing the prop's own main layer | layer 2 of the prop's row |
| reactive | `react` targets | §7a presets | replaces layer 1, or (`--over`) the layer above everything else |
| pin (0.19) | props a group sequences, where you pin them | only the pinned effect, only there (§7a) | the prop's own row, placed last, so it wins over the group |
| face (0.19.1) | props given a face (`face use PROP FACE`) | the Faces effect while the words are sung (§13f) | the top layer of the prop's row; a prop a group sequences gets its own row, placed last |
| **base** (0.20) | every prop the passes above light (not singing ones, not `base: false`) | a few whole-yard **moments**: unison hits, sweeps, call and response (below; `matchup/base.py`) | the prop's own row, placed last, above the layers it already has |

**Order** (0.20): main → top → detail → enhance → rests → **duration limits and
variations** (main and top) → **base** → pins → reactive → faces.

**Moments** (`matchup.moments`: id, type, start, end, section_index, reason,
targets, members; scoring.passes.base). Candidates come from the music:
- *unison* - every prop flashes at once (half a bar) on a section start whose
  incoming strength is ≥ `unison_min_strength` (0.6), and on drops (a window's
  energy ≥ `drop_energy_jump` (0.25) above the one before);
- *sweep* - in the bar before a section start of strength ≥ 0.5, the props flash
  one after another in yard order (`models.yard.x`, the centre of the prop's
  lights, 0 = left; new in 0.20), left to right or back (seeded);
- *call and response* - the first 8 bars of a section of `call_sections` (verse,
  bridge, breakdown, pre-chorus): the left half (by yard x) flashes the beats of
  2-bar phrases 1 and 3, the right half 2 and 4.
Scores: strength (+ the energy rise), times 1 + `escalation` (0.3) per earlier
repeat of the section - so chorus 3 gets moments before chorus 1. Chosen best
first, at most `per_minute` (1.5) a minute, `min_gap_s` (6) apart; a sweep that
lands on a unison hit is one moment in the budget. None inside the top pass's
sections. Fewer than `min_props` (3) props: none, said in the diagnostics.
The flash is `effect` (pulse) at full intensity, accent palette.
**members** (the user's option): `cut` (default) - every other plan on the
props, groups over them included, rests for the whole moment; `over` - they
keep playing, the moment on top; `under` - the moment shows only where the prop
otherwise rests. Per prop or group: `targets.NAME.base_members`; `targets.NAME.base
= false` leaves a prop out. `explain PROP @TIME` inside a moment says which,
why, with how many props and how the members behave; outside it explains the
prop's group as before. Summary and `run` list the moments.

**Duration limits and one-aspect variations** (`matchup/durations.py`;
scoring.durations, scoring.passes.variation; the user's requests). Limits in
seconds, "N bars" or "N beats"; most specific wins (effect, family, pass,
default); defaults: min 1 s, max 8 bars, colour washes 16 bars, the top pass 16
bars. Under the minimum, a segment is absorbed by its neighbour on the row (not
across a section start). Past the maximum it is divided every `every` (4) bars,
on bar lines, and each part changes exactly one aspect from the part before:
`auto` = direction, then colour, by turns (colour only for effects without a
direction), or `color` (the palette turned by one), `direction` (the next
direction choice), `effect` (the next best effect, colours kept, then back).
Nothing is random, so repeats vary alike. Each part says "variation 2 of 4
(direction only)". Pinned segments, reactive plans and moments are exempt. The
validator's EFFECT_TOO_SHORT became TOO_SHORT and TOO_LONG, checked against the
limits the plan was made with (stored in its settings, with the beat length).
**GUI: the pivot, the row filter, folded moments** (0.20.3). A two-state button
(▦ by effect / ☰ by prop) switches the lanes to one row per effect type with,
in each section's column (the same x as the timeline), how many groups (g) and
props (m) use it - shaded by count; rows sorted by use. Hover: the effect, the
settings the same for all of them, then each group / prop with the settings that
vary; click: the same in the panel, with the explain command to run. A filter box
(a regular expression, any case; Esc clears) keeps only matching rows, in both
views; "fold moments" (on by default) shows the base pass as one row "moments (N
props)" instead of one per prop. Both remembered per browser.
**Long tables** (0.20.4, as proposed): a group's props sit under it (▸ / ▾ opens
them; closed it says "(+4)"); rows sort by layout order, name, size (lights) or
left to right (`models.yard.x`); ☆ / ★ keeps a row at the top; a mini-map of the
whole sequence (bottom right, when the rows don't fit) shows where the view is -
click it to go there. Open groups, stars and the order are remembered per
browser. With a filter the list is flat (every match shows).
**Timeline layout** (0.20.4, the user's): the view controls (by effect / by prop,
fold moments, the filter, the order) sit at the top of the name column, above the
rows they change; the waveform's left label shows the song's length and the play
head ("1:22.5 long, at 0:31.2"); bar and beat colours label the tick row; the
effect-family colours (left) and the waveform's vocal colours (right) are a band
between the waveform and the sections. Pointing at a section heading says its
span, the change into it, its loudness and repeat; clicking explains the music
there (`explain music @T`) in the panel.

**Sections from an existing sequence** (0.20.3, the user's idea;
`music/xsq_sections.py`): `sections from-xsq Song.xsq [--layout SHOWFOLDER]
[--apply]` puts every effect of the .xsq on the props it lights (a group's on its
members, from the layout next to the .xsq or the stored one), takes the current
song's bars as the grid, finds bars where many props start a new effect and the
look changes (≥ 4 bars apart), compares passages bar by bar (the effect counts 80%,
colours and settings 20% - so variations still match) and gives alike passages
the same letter; the busiest repeated letter is the chorus, other repeated ones
verses, one-offs intro / outro / bridge / breakdown. It prints the table and how
many boundaries agree with the current sections; `--apply` makes them your
section fixes (as `sections import`).
**Borrowing from an .xsq** (0.20.4, as proposed; `matchup/borrow.py`).
`xsq-borrow Song.xsq` lists what it holds by section of the current song and row,
with ids (#3.2), marks rows not in your layout, and becomes the source; `borrow ROW
@#N`, `borrow #N.K`, `borrow @#N` (every row), `borrow ROW --all`, `borrow
@1:12-1:16` (a moment as a whole) copy those effects - xLights' own effect name,
EffectDB settings text and ColorPalette text as they are (`xsq.read` keeps them
raw), clipped to the span - into the song's record (songs.json `borrowed`), and the
last run is repeated. `borrow --map "OLD=NEW"` names a row your layout calls
otherwise (remembered for every sequence). In the plan they are pass `borrowed`:
on the row of that name, on the layer above its others (whose effects give way in
those spans), the row placed with pins, after its groups - so it wins; everything
else is planned around them as usual. The exporter writes them unchanged (and its
read-back check accepts their names); `explain` says "borrowed from Song.xsq: ... as
it is there"; the GUI hatches them ("borrowed" colour) and the pivot counts them.
`borrow` lists them, `unborrow ROW [@#N] | @#N | --all` gives them back. Effects on
another xLights layer of the same row are cut where they overlap (one layer).
**Not yet (0.20.x):** `vary TARGET @#N color|direction|effect` to ask for
variations by hand, pins on moments, a changes-per-minute budget shared with the
moments, a critic term for busy-ness.

- **Where a top group plays, everything on its members rests** (0.19): main,
  detail and enhance layers alike (detail and enhance are planned after the top
  pass, so they are cut out afterwards); pinned segments stay.
- **`transparent` and `dark`** (0.16; the user's terms). `transparent` = no
  effect from this pass, so lower layers and the base show through (the prop
  is dark only when nothing is underneath); it was called `off` up to 0.15.
  `dark` = the prop explicitly black: it masks lower layers and earlier rows
  (xLights' Off; confirmed by the user). `dark` is never chosen automatically
  (`"auto": false` in effects.json): only where pinned, or by a preset.
  Old `off` in preference files, rules and presets is read as `transparent`
  (`common/vocab.py`), and old plans with `off` still draw and export.
- **No effect is not a threshold:** `transparent` is scored like every other
  effect (it suits quiet, sparse music) and wins when nothing lit scores
  higher; later passes also favour it (`rest`, `min_energy`). Those segments
  are kept in the plan (not exported), so `explain` can show the scores; the
  GUI draws them as dashed outlines, `dark` as black blocks, and clicking an
  empty part of a lane explains that moment.
- **Overlaps:** one detail target per prop. Overlapping detail groups (rings
  vs spokes of the same spinner) are resolved largest first; the others are
  reported, and setting one's role to `unused` chooses (the message shows the
  `pref` command).
- **Precedence (confirmed by the user):** within a row, layers apply from the
  bottom up, so the uppermost layer wins - the exporter writes the highest
  generic layer first. Rows apply from the top of the Master View down, so a
  later row wins over an earlier one - the exporter writes top groups first
  and detail groups last. If you reorder rows in your Master View, that
  changes which wins. The top pass doesn't depend on row order: members are
  cut out where the top group plays.
- **Submodels** are imported with their node ranges (type "ranges"; seqtool
  names them `Model/Sub`, as xLights groups do). Their points are the
  parent's points in node order, which is an approximation (the parent's
  start corner and direction aren't modelled), but good enough for the
  geometry class and capabilities. A multi-row submodel (all spokes in one
  submodel) is one target; to drive a single spoke, make a submodel per spoke
  in xLights.
- **Available effects:** when the layout is from xLights and a kit is learned,
  `run` only offers the effects that kit knows (others are listed with a
  pointer to `xlights-kit --update`). The exporter also substitutes the best
  learned alternative for any unlearned effect and says so.

Group render modes are generic hints (`render_hint`: `per_prop`, `as_one`).
The adapter maps them onto xLights render styles.

**Explaining a decision**: `seqtool explain MODEL @TIME` answers "why does
MODEL show this effect at this moment of the song". Each factor line ends
with a short "based on" note:
- **prop type:** the geometry class in words, and the effect's rating for it;
- **geometry:** what the effect needs and what the prop has;
- **music:** "heard/ideal" pairs, the music's value against the effect's
  ideal;
- **style:** the song's top styles and the effect's affinity for each;
- **section:** the type (with any custom name and what it's treated as),
  label confidence, and affinity;
- **continuity:** the previous effect, the transition strength, and why it
  is that high (section change and music contrast).

A **colours** line gives the palette and why it was chosen: the style and
its score, which of the style's palettes, the rotation (all seed-picked),
and the accent rule for high-energy segments.
- **TIME:** seconds (`@37.5`), m:ss (`@0:37.5`), or a section (`@#3`, its
  middle).
- **MODEL:** case-insensitive; a unique prefix or fragment works (`tree`
  finds MegaTree).
- A prop sequenced through a group is explained via the group, with a note
  saying so. A prop that isn't planned at all gets the reason it isn't.
- The newest matchup in `./seqtool-out` or `./seqtool-demo` is used unless
  `--out` or `--matchup` is given.
- The demo ends by showing this command, then its output, as a worked
  example. `match --explain` remains for single-stage use.
The explanation shows:
- the section the moment falls in;
- each factor's value × weight = part, the weighted average, × preference,
  + random variation, + continuity = the final score;
- the parameters, alternatives, and reasons;
- a note when a higher-scoring alternative lost because switching would cost
  more than the difference.

## 10. Validator and feedback loop (`validate`)

The validator checks the whole plan, which per-target scoring cannot see.
- **Hard errors:** unknown target, negative duration, overlapping segments.
- **Quality warnings:** effect too short, excessive changes, unused model,
  duration mismatch, simultaneous changes at a weak transition.
- **Info:** low diversity, uniform section.

It also emits **feedback**: per-target change-penalty scaling and
per-section effect nudges (only the half of the targets with the smallest
score margin get nudged). The next run takes it with
`match --feedback validation.json`. Feedback accumulates across iterations.
The loop stops when `feedback.converged` is true; the demo needs 2–4
iterations. Diversity is reported but, by default, doesn't push the planner.

## 11. Effect vocabulary (generic → xLights)

| generic | xLights | family |
|---|---|---|
| transparent | (nothing written) | none |
| dark | Off (needs kit v8: `xlights-kit --update`) | none |
| color_wash | Color Wash | color |
| pulse | On (with ramp) | pulse |
| chase | Single Strand | motion |
| bars | Bars | motion |
| wipe | Curtain | motion |
| spirals | Spirals | radial |
| pinwheel | Pinwheel | radial |
| twinkle | Twinkle | sparkle |
| sparkles | Shimmer | sparkle |
| meteors | Meteors | particle |
| fire | Fire | organic |
| fill | Fill (level / position) | level |
| vu_meter | VU Meter (Volume Bars, Spectrogram or Waveform; 0.19) | audio |
| face | Faces (a face definition, the phoneme layer of seqtool-lyrics, eyes at xLights' default Auto; kit v11, 0.19.2) - only through `face use` | face |

fill and vu_meter need kit v6+ training (`xlights-kit --update`); until then
`run` doesn't plan them and the exporter substitutes the next-best learned
effect. `dark` needs kit v8 (the Off step); until then a dark segment is
left empty (transparent) with a note - never replaced by a lit effect. Directions: spirals `clockwise` = negative Movement (confirmed by the
user, rev 25). Glides (keyframe easing) are written as stepped effects, not
value curves (rev 24).

## 12. Dependencies

| Need | Packages |
|---|---|
| Required | Python ≥ 3.10, numpy |
| Optional system tool | ffmpeg (any audio format; WAV works without it) |
| Optional, installed on demand with a prompt | jsonschema (validation), demucs + torch (vocal stem), faster-whisper (lyrics transcription, 0.18.0), Pillow (singing-face images, 0.19; HPND licence, permissive) |
| Downloaded on first use, after asking | the CMU Pronouncing Dictionary (phonemes for singing faces, 0.19.1; BSD-style licence), from `faces.phonemes.cmudict_url` |

Optional packages install with a prompt (0.17: packages that run as their own
process, like Demucs, are only checked for, not imported into seqtool; if a
package installed while seqtool runs can't be loaded, seqtool offers to restart
itself with the same command line). Control it with
`--install=ask|yes|no` or `SEQTOOL_INSTALL`. In a non-interactive run, "ask"
declines instead of hanging.

## 12b. Packaging for others (`package`, 0.19.3)

`seqtool package [--out DIR] [--with-tests] [--exe]` builds `dist/seqtool-X.Y.Z.pyz`:
one file holding all of seqtool (a Python zip application: `__main__.py` is
`seqtool/bootstrap.py`, the files are under `payload/` with a manifest of their
sha256). Python 3.10+ is needed to run it, as for seqtool itself (seqtool installs
optional packages with pip, so a Python is needed anyway); numpy is offered for
installation when missing.
- **Linux:** `chmod +x seqtool-X.Y.Z.pyz; ./seqtool-X.Y.Z.pyz [seqtool arguments]`.
  **Windows:** double-click (the python.org installer links .pyz to Python), or
  `py seqtool-X.Y.Z.pyz`.
- **First run:** the files are unpacked next to it into `seqtool/` (else
  SEQTOOL_HOME, `--unpack-to DIR`, or the user data folder when that one isn't
  writable), then seqtool runs from there with the same arguments. The files stay
  for next time; a later run of the same version starts at once.
- **A new version** compares each file on disk with the manifest the previous
  version left (`seqtool/.seqtool-manifest.json`): unchanged files are replaced
  silently; a file that differs was changed by the user - if the new version
  changes it too, the user is asked once for all (keep all - the new version saved
  as FILE.new; replace all - theirs saved as FILE.old; or one by one; the default,
  and the answer without a terminal, is keep); if the new version doesn't change
  it, it is kept without a question. Files the new version drops are removed when
  unchanged, kept and named when changed. The new manifest always records the
  shipped hashes, so a file still customised is asked about again next version.
- Left out: caches, results and preference folders, `dist/`, HANDOFF.md (notes for
  continuing development), and `tests/` unless `--with-tests` (its fixtures hold
  parts of the user's own show); `--test` in a copy without tests says so.
- `--exe` (experimental, untested): wraps the same launcher as a stand-alone
  program with PyInstaller on the system it runs on (Windows for a .exe); it still
  runs seqtool with the computer's Python.
- Own options of the .pyz: `--unpack-only`, `--unpack-to DIR`, `--where`.

## 12a. Viewing results

The pipeline writes two kinds of view:
- `<stem>.labels-sections.txt` and `<stem>.labels-beats.txt`: Audacity label
  tracks. Section labels include repeat info.
- `<stem>.timeline.html`: a self-contained page with the waveform, section
  bands with repeat markers, beat ticks, one lane per target coloured by
  effect family, audio playback with a playhead, zoom, and hover details.
  **Clicking an effect** opens a panel with its full `seqtool explain`
  output (command line included). Clicking above the lanes seeks, and Esc
  closes the panel.

**Live browser GUI** (`seqtool gui`, or the global `--gui` option at
startup). A small local web server runs inside the seqtool process, using
only the standard library (`seqtool/gui/server.py`, page in `gui/app.html`).
- **Header:** current song (flagged if missing), results folder, seed and
  overrides, and a cache badge ("8 files ok" / "2 stale"). Clicking the badge
  shows each file's status with reasons, as `status` does.
- **Middle:** the timeline (waveform, sections with repeat markers, beats,
  effect lanes) with audio playback. The audio is served with HTTP Range
  support, so seeking works. Clicking an effect shows its explanation.
- **Bottom:** a console that behaves like the `seqtool>` prompt. Lines run as
  seqtool commands, and output streams into a scrollable area while the
  command runs. History (↑/↓) is kept by the browser, `clear` empties the
  pane, and a drag bar resizes it.
  - **Questions are asked in the console.** A GUI command runs with a
    per-thread "asker" installed, so `ask()` sends the question to the page
    and the command waits. The prompt switches to `answer>` with the
    remembered default; Enter answers, and Esc cancels the command (raised
    inside it as `Cancelled`).
  - Everything built on `ask()` therefore works from the GUI: missing
    arguments, glob choices, stale-file questions, channel overlaps, and the
    prop wizard. The kit wizard's live mode watches the terminal's keys and
    stays in the terminal; from the GUI it prints its step list.
- **One push channel, plain POSTs back.** Server-Sent Events
  (`/api/events`) carry everything the server sends:
  - `changed` (refresh the view);
  - `out` (sequence-numbered command output);
  - `ask` (a question);
  - `done`;
  - `busy` (which command is running, and from where).

  The browser sends commands, answers, and cancels as POSTs. When a command
  starts, the page also fetches the job's state once
  (`/api/job?from=N`) to close the race between starting and knowing its
  job id. Sequence numbers make output gap-free and duplicate-free, and the
  same fetch catches up after a reconnect. EventSource reconnects on its
  own. No polling remains in the browser.
- **Change detection:** commands run in this process push `changed` the
  moment they finish, from the GUI console or the terminal prompt. Changes
  made by another seqtool process (or an editor) are found by a light
  server-side check twice a second. It compares a fingerprint of which song
  is current, the times of all that song's result files (both places), the
  per-song settings, and the stored layout. The cache badge covers the same
  files.
- **Connecting first:** the page opens its event stream before loading any
  data, and the console accepts commands only once it is connected. It
  catches up on connect and when a command finishes. Catch-up returns
  numbered chunks, so output is never lost or shown twice. This fixes a
  first command whose output could vanish while the page was still loading.
- **Robust command completion:** a 'done' that arrives while a catch-up
  fetch is in flight is queued, not dropped. That was the cause of commands
  stuck at "running…". A `tick` event every 5 s also keeps the connection
  alive and re-checks a running command.
- **Keystrokes anywhere** go to the command line, and clicks return the
  focus to it unless text is being selected.
- Closed-connection errors from the browser are no longer printed.
- The output router provides everything Python's `input()` needs to keep
  using readline, so up-arrow history works at the terminal prompt while
  the GUI runs.
- **Waveform peaks** are decoded once per audio file version and cached in
  `seqtool-prefs/cache/`, so page loads are fast even for long songs.
- **One command at a time:** the GUI console and the terminal prompt share
  a lock that records who holds it. Whoever has to wait says so: "(waiting
  for the GUI command 'run' to finish ...)" in the terminal, and the same
  for the terminal's commands in the GUI console.
- **Output is routed per thread.** Once the GUI runs, sys.stdout and
  sys.stderr are thread routers. A GUI command's thread writes into its
  job; every other thread (the terminal prompt, the server) keeps the real
  terminal. Without this, a GUI command waiting for an answer would swallow
  the terminal's output.
- **Security:** only 127.0.0.1 is served, and every API request needs a
  random per-session token, so other web pages can't run commands.
- **`--gui` behaviour:**
  - `seqtool --gui` opens the browser plus the terminal prompt; the GUI
    stops when the prompt is left.
  - `seqtool --gui run ...` runs the command, then keeps serving until
    Ctrl-C.
  - Without a terminal, it serves until Ctrl-C.
- Each run removes leftover iteration files from earlier runs, and the GUI
  shows the run's recorded final plan.

**Player commands** (0.17.2, `gui/player.py`): `play [#N | TYPE [K] | @TIME]`
(from the play head by default; `play chorus 2` = the second chorus), `pause`,
`seek -5 | +5 | 0 | @TIME | #N`, `volume [N | +N | -N]`, `speed [x | N%]`. They
work at the seqtool> prompt and in the GUI console and drive the page's player
through a 'player' event; the page reports its state back (`/api/player`), so
`volume` and `speed` alone say what they are. Volume and speed are remembered by
the browser. With no GUI open they say how to open it. Next to the player:
to-the-start, back 5 s and forward 5 s buttons, and the speed when it isn't 1x.
Tooltips sit 60 px right of the pointer (room for large pointers).

**GUI additions (0.17):**
- **Menu bar** (from the command sections: Pipeline, Refine, Setup, Single
  stages, Other commands, Help), with submenus of common variants (run: current
  song / best of 5 seeds / with vocal stems / another song ...; inspect; sections;
  pin; reroll; baseline; pref; groups; rules; xlights-kit ...). Complete commands
  run at once (echoed in the console); entries ending in "..." put the start of
  the command in the console to complete. `/api/menu`, `MENU_EXTRA` in server.py.
- **On an effect:** hovering shows a push-pin and a die at its top right. The pin
  pins that effect in its section, or unpins it; a pinned effect always shows a
  solid pin. **Ctrl+click** (0.19.2) opens a list of effects to choose from for that
  moment (`pin TARGET @T EFFECT`): first "auto - seqtool chooses" (removes your
  choice: `unpin`), then the effects that suit the prop's type best (model fit
  0.6 or more, best first), a separator, and the rest (dark and transparent
  last). Only effects the xLights kit has learned are offered; `face` is not (it
  is set with `face use`). The list comes with the timeline data
  (`effect_menu`, `demo/view.effect_menus`). Not on react or face lanes. The die rerolls that target in that
  section. Both run the command in the console ('pin MegaTree @37.49 spirals',
  'unpin "MegaTree (main)" @37.49', 'reroll MegaTree @37.49'). Not on react lanes.
- **Where the singing is** (0.17.4, `music/vocals.py`): two questions per frame
  instead of one ratio. Singing? The stem's own level against a gate: 'auto' =
  10 dB above the stem's quiet level between vocal lines (its 10th percentile;
  kept 12-18 dB below the loudest singing (its 95th percentile; 30 before 0.18.0 -
  too low where the stem is silent between lines, addendum A2), or
  `music.display.vocal_gate_db`;
  gaps between words up to `vocal_gap` (1 s since 0.17.7; was 0.8) are bridged by a closing (widen,
  shrink back), so where singing starts and stops doesn't move. The voice leads? The
  stem within `vocal_lead_db` (-6 dB) of the whole mix = vocals, quieter =
  mixed; not singing = instrumental. Before, a single stem/mix ratio called
  singing under a loud band "instrumental". `inspect vocals` shows the stem's
  levels as a histogram with the gate, the shares and the passages, with the
  prefs to change; `explain music @T` says what it is at that moment.
- **Vocal sliders** (0.17.5): a "vocals" button next to the player opens
  sliders for the singing gate (or auto), how close to the mix the voice leads,
  the longest gap bridged, and the shortest passage. The page redoes the passages
  itself from the stem and mix levels (`vocals.gui_levels`, 0.1 s steps;
  `vocalRegions` in thumbs.js, the same rules as music/vocals.py), so the
  waveform recolours while dragging and the shares are shown. "save" runs the
  `pref` commands (one undo step each); "reset" returns to the saved values.
- **The playhead stays in view** (0.17.7): while playing, or after a seek
  (buttons, `play`/`seek` commands), a zoomed timeline scrolls so the playhead
  is visible again when it leaves the view (a page turn, as in xLights), in the
  GUI and the static page. Scrolling by hand while paused is left alone. Since
  0.18.0 it scrolls half a page (the playhead lands in the middle, so where it
  came from stays in view); Space plays / pauses (not while typing).
- **Easier to read** (0.19): the song's name in the header is coloured (and its
  folder shown after it, dimmed); bar ticks are orange, 2 px and taller, beat
  ticks light grey (dark grey in the light theme), so they stand out from the
  blue / green / teal waveform, in the GUI and on the static page.
- **Waveform coloured like trackED** when a vocal stem was used: vocals (dark)
  green, instrumental (dark) blue, mixed (bright) teal. Passages come from the
  vocal level per analysis frame (`music.display.vocal_min` 0.7 /
  `instrumental_max` 0.3); any passage shorter than `music.display.min_region`
  (1 s since 0.17.7, from the user's slider trials, addendum A2; was 2 s) is merged into its longer neighbour, shortest first, so the colours mark
  passages rather than flicker (`view.vocal_regions`). Same on the static page.
- **An open explanation follows the results** (0.17.1): when results change (a
  command in the GUI or at the seqtool> prompt), the panel is redone for the same
  prop, layer and moment.
- **Quitting closes the GUI** (0.17.1): quit/exit at the prompt stops the GUI
  server (also one opened with `gui`); the page closes its tab where the browser
  allows it (a tab opened by seqtool, Chrome), and otherwise says seqtool was
  closed. Pinned effects can be rerolled: the effect stays and only its settings
  (direction, speed ...) are new; `reroll` and the die's tooltip say so.
- The explanation's close button is red. Clicking an effect explains that layer
  first. Commands run from the GUI don't suggest the `gui` command.

**`seqtool gui [browser|audacity]`** opens these for the last song (or
`--out DIR`). It works any time after the music analysis: without a matchup
it shows the waveform and sections only, so the user can look before the end
of the pipeline. The pipeline itself ends by pointing at `gui`; `--view`
remains for scripted use. With Audacity, it opens the song and says which
label files to import.

The text summary marks repeated material under each section heading:
- `= #2 verse`: every target's effects repeat section #2 exactly.
- `~ #1 intro 18/24`: most targets repeat it.

**Effect thumbnails** (built in rev 23, §13b): a small animated preview next
to each target name plays the lane's effect with its palette and parameters on
the prop's own points. The same renderer could later drive a whole-yard preview
(on hold, §13e).

## 13. Relationship to trackED

The projects are separate for now. seqtool reuses logic from trackED and
lyric-track.py (Demucs runner, logging style). The timeline viewer (§12a) is the part trackED is most likely to take
over first: a waveform editor that also shows and edits sections and plans. The likely end state is trackED
as a GUI over these stages: waveform, sections, matchup explanations, and
iteration control.

## 13a. MVP scorecard (against the original acceptance test, §27 of the MVP design)

| # | Acceptance item | Status | % |
|---|---|---|---|
| 1 | Analyze one real song without excessive memory | streamed decoding; used on the user's songs | 100 |
| 2 | Beats, tempo, energy, vocal activity, sections | all done; sections also editable + Laplacian + words; the Demucs vocal stem runs on the user's songs | 100 |
| 3 | Parse a real xLights layout, derive geometry/capabilities | verified on the user's layout | 100 |
| 4 | Honour per-model allowed-effect lists | | 100 |
| 5 | Keep model fit separate from music fit | | 100 |
| 6 | Capability fit and temporal continuity in scoring | | 100 |
| 7 | Section transitions can override continuity | plus music contrast (rev 20) | 100 |
| 8 | Deterministic results from a fixed seed | byte-identical; per-song seeds | 100 |
| 9 | A valid XSQ that xLights can open | opened in xLights 2025.13.1 by the user; effects show correctly | 100 |
| 10 | Validate, distinguishing errors from warnings | generic + xLights-specific checks | 100 |
| 11 | Preserve all intermediate files | | 100 |

Every acceptance item is met. What remains is tuning defaults on the user's
real songs (the 4-song baseline: sections, effect choices, speeds) rather than
adding features.

The hold on non-MVP features was lifted by the user after rev 22 (backlog
§13b items 1-6 built). Added on request, beyond the MVP: the live GUI, reroll,
reactive presets, name rules, the `pref` editor, and Laplacian segmentation.

## 13b. Backlog (held back until the MVP was done)

| # | Item | Status |
|---|---|---|
| 1 | Submodels as targets; the detail pass | done (rev 23) |
| 2 | More learned effects (Fill, VU Meter) | done (rev 23); value curves dropped for keyframe easing (rev 24); Piano still out (needs pitch) |
| 3 | Pass 2 layers (enhance) | done (rev 23) |
| 4 | Top-down pass | done (rev 23) |
| 5 | Effect thumbnails in the GUI | done (rev 23) |
| 6 | Lyrics | import of LRC / Audacity labels (rev 23); transcription and alignment (0.18.0) |
| 7 | Photo-based props | not now |
| 8 | WebSocket GUI channel, trackED as a GUI, licensing review | not now |

**Effect thumbnails** (GUI and timeline page): a small live preview next to
each lane name, drawn on the prop's own points (front view, node order,
≤140 points, from layout.json) with the segment's colours and parameters,
for the segment under the playhead. While paused it loops that segment, so
you see the effect running. It is a generic sketch of what seqtool means
(gui/thumbs.js), not an xLights render.

## 13c. Console text, tutorials and training prompts (rev 24)

**Colour codes** are written inline in strings (common/color.py), never by
calling colour functions on fragments:

| Code | Colour | For |
|---|---|---|
| `{err}` | red | errors |
| `{warn}` | yellow | warnings, stale files |
| `{ok}` | green | successful outcomes |
| `{do}` | pink | something for the user to do: commands, wizard and tutorial steps |
| `{note}` | blue | background / debug information |
| `{head}` | teal | headings, summaries, high-level results |
| `{b}` | bold | emphasis |
| `{/}` | | back to the enclosing colour (codes nest) |

Colour names work too. Example commands quoted in any message
(`'sections merge 3 4'`, `'seqtool xlights-kit'`) and `$ seqtool ...` lines are
highlighted as `{do}` automatically, from the list of command names, so
messages don't need codes for that. One renderer per destination: the terminal stream
(ANSI; plain when NO_COLOR or not a terminal), the GUI (coloured spans in the
console, explanation panel and help, kept open across output chunks), and
files on disk (plain). Used in help and command `-h` headings, stage banners,
explain, status, validation results, presets / effects listings, the
training wizard and the tutorials.

**Tutorials** (`tutorial [NAME]`): guided walk-throughs in the style of the
training wizard (tutorials.json): basics, your-song, sections, react, rules,
faces (0.19.3: the end-to-end lyrics and singing-face test - kit update with the
breakdown note, lyrics transcribe, lyrics phonemes, face build, paste, layout,
face use, run, explain, xLights; placeholders {faceprop} and {face}, checks words,
dictionary, face_built, face_in_layout, faces_used),
presets, lyrics, xlights. Each step says what to do and suggests a command
(Enter runs it; any other command can be typed); a check confirms the step
(e.g. a rule exists, lyrics are imported, an .xsq was written) before moving
on. Progress is remembered; `s`/`b`/`q` skip, go back, stop. A tutorial with
skipped steps ends "incomplete" and is listed so ("step(s) 2, 4 skipped"), not
done (0.19.9). Placeholders ({prop}, {chorus}) are filled from your current
results - after `demo` the demo's props, which `react` therefore accepts too
(a name from the stored layout or from the layout the current song was planned
with). `react` and `rules ... react=` are the same setting at two scales (one
name / a name pattern); `react` wins where both apply. `help rules` is the help
(only effects and presets show their listing as help). Works in the
terminal and the GUI console.

**Training prompts:** when the xLights training is missing or incomplete,
`layout` (after storing an xLights layout) and the export (`xlights-export`,
and the last stage of `run`) ask whether to run the wizard now (it runs in
the terminal; elsewhere they say how). Saying no continues with what was
learned.

**Larger previews:** pointing at a lane's small preview shows a 300x180
version next to the pointer; the explanation panel (click an effect, a name
or a preview) shows the effect large above the text.

## 13d. State and what still needs checking (rev 44)

**Verified by the user in xLights 2025.13.1:** the .xsq opens and effects
show correctly (rev 20); timing tracks (needed adding to the Master View -
the export now copies the training file's views or says so); layer and row
precedence (uppermost layer wins, later rows win); spirals direction; `dark`
(Off) blanking lower layers and earlier rows. Demucs (subprocess) and
faster-whisper run on the user's machine.

**The verification sequence** (0.18.6, `xlights-export --checks`,
`adapters/xlights/checks.py`): one .xsq for the stored layout with a 6 s slot
per feature, a 1 s pause between slots, and a `seqtool-checks` timing track
naming each slot. The command prints what each slot should show:
1. Fill: the prop lit to half;
2. Glide: the prop filling up, written as a run of short Fill effects;
3. VU Meter: Volume Bars rising and falling with the music all through the slot
   (media: `--audio SONG`, else the current song; with a song the slots start at
   its first chorus, 0.19). Before 0.19 it used Level Bar with a high Sensitivity:
   xLights' Sensitivity is a trigger threshold (the effect runs only while the
   music is louder), so the bar moved only at the loudest moments - what the user
   saw. Kit v9 adds the Volume Bars and Spectrogram types (`xlights-kit --update`);
   the automatic VU Meter choices are now Volume Bars, Spectrogram and Waveform,
   with Sensitivity near its default;
4. Submodel row: only one submodel lit, its effect on the submodel row;
5. Top group: the whole top group lit, its row first;
6. Dark: the group lit except the prop, whose Off wins over the group row.

`seqtool-lyrics` (one line and its words per slot) checks the phrase and word
layers. The prop, group and submodel are picked like the passes pick them (the
top group, its biggest prop, a submodel of that prop or else any); `--prop`,
`--group`, `--submodel` choose others. Effects the kit hasn't learned yet are
named first with `'xlights-kit --update'`, and their slots stay empty. It is
written to the kit folder (else the current folder), `-o` elsewhere.

**Still to check in xLights** (with the sequence above, after `xlights-kit
--update`): kit v7-v8 steps (Fill, VU Meter, Off, submodel row); Fill and VU
Meter output; submodel rows; glide steps; top/detail row order; the
seqtool-lyrics track. In a real song: the top pass in intro/outro (members
transparent while 1.ALL plays) - a taste call.

**Known limitations:** submodel points approximate the parent's node order
(start corner / direction not modelled); multi-row submodels are one target;
effect previews are generic sketches; Piano effect needs per-note pitch; the
kit wizard runs only in a terminal; detail groups overlapping on one prop are
resolved largest-first (others reported).

## 13e. Agreed roadmap (2026-10-15)

Revised with the user after reviewing 0.18.5. The display season has started
(Halloween, then Christmas), so singing faces move ahead of the base pass.

| Release | Contents |
|---|---|
| 0.15-0.18 | done: stem cache, baseline, doctor (0.15); pins, candidates + critic, guessed roles, dark/transparent (0.16); fix-it examples, group levels and name rules, GUI menu, trackED-style waveform (0.17); lyric transcription and alignment, sections from the words (0.18) |
| 0.18.6 | done: design clean-up, the verification sequence (`xlights-export --checks`), a test that depended on the terminal |
| **0.19** | **singing faces** (§13f). 0.19.0: the face format learned from the layout, `face build` for Matrix (image) faces with the `faceInfo` XML snippet, `face list` / `face format`. 0.19.1: the phoneme layer (CMUdict by default, other dictionaries by preference), the Faces effect in the kit (v10), `face use PROP FACE` - props sing the lyric lines. Next: node-range faces; shapes calibrated on the user's faces; a GUI preview |
| **0.20** | 0.20.0 done: whole-yard base pass (moments) with the members option, **one-aspect variations** and **effect duration limits** (§9). 0.20.x: `vary`, pins on moments, a shared changes budget |
| 0.21 | (moved up by the user, 2026-10-18) **all Demucs stems** - drums (kick / snare hits), bass, other - and the **melody** (basic-pitch) |
| 0.22 | style training wizard (`style-training`) and style profiles; section types learned from the user's own labels as its first slice |
| 0.23 | kit wizard in the GUI, lyrics drawn under the waveform, change highlighting, playlist runs; node-range faces (not needed for Halloween - the user) |

**Action list** (agreed, not yet scheduled; fitted in where they help):
- **All Demucs stems:** drums (kick / snare onsets for tighter beat hits), bass
  (floods, pulses) and other, beside the vocal stem Demucs already makes.
- **Melody pitch** (basic-pitch, Apache-2.0) on the "other" or vocal stem: the
  Piano effect and sweeps that follow the melody.
- **Lyric keyword cues:** words such as star, snow, bells or "merry" suggest pins
  on matching props through name rules (opt-in; `on: lyric` presets already
  match text).
- **Group suggestions:** propose missing groups the base pass needs (left / right
  halves, height bands), written as an XML snippet like the faces.
- **Batch intake and a playlist critic:** a folder of songs analysed, stemmed,
  transcribed and run in one go (overnight); a show-level critic so consecutive
  songs don't share a palette or look.
- **States effect:** layouts with `stateInfo` (the user's has beats, Masks,
  NatScenes, …) get a learned States effect.
- **Render automation:** check what xLights' automation interface (command line /
  HTTP) supports in 2025.13 for opening, rendering and saving the .fseq for FPP.

**On hold** (the user's decision): round trip of hand edits made in xLights
(re-import an edited .xsq as pins and overrides), whole-yard preview.
**Not now:** photo-based props, WebSocket GUI, trackED as a GUI.

**dark vs transparent** (user's wording): `dark` = the prop explicitly black,
written as xLights' Off effect; confirmed by the user: Off on a prop's row
blanks effects from lower layers and earlier rows. `transparent` = no effect
from this pass, so lower layers and the base show through (the old `off`).
Old `off` in preferences reads as `transparent`. `dark` needs a kit step.

**Style training** (decided): each user trains their own style; nothing ships
pre-trained. Third-party sequences are fine when they are the wanted style.
Examples may come from different layouts: what is learned is expressed in
generic terms (prop class, size rank, position, group role, section type,
energy), each example's props described from its own layout. Per-name
preferences are learned only from examples on the user's own layout. Wizard
steps: profile name; add an example `.xsq` (audio from its media path, layout
from its show folder, asking only when missing); a read-back table and counts
to confirm, with rows to exclude; repeat; finish with changes vs defaults and a
leave-one-out agreement score. Prompt-only, so it works in the GUI console.
No third-party audio or sequences go into the package or tests.

## 13f. Design notes for 0.19 and 0.20

### Singing faces (0.19)

**What xLights needs.** A face definition on the model (`faceInfo`: the mouths
AI, E, etc, FV, L, MBP, O, U, WQ and rest, with eyes open / closed; node-range
faces also an outline) and a Faces effect that reads a lyrics timing track with
three layers: phrases, words and phonemes. Real layouts mix node-range faces
(custom props) and image faces (matrices, trees); the developer's: addendum A3.

**1. The face format is learned from the layout** (0.19.0,
`adapters/xlights/faces.py`). The import reads every `faceInfo` and learns,
without assuming xLights' names:
- the type key (fewest values) and the name key (most values) among the
  attributes every face has;
- per type, whether it holds image paths or node ranges, and the key template:
  the keys holding images are split on '-', the part with the most values is the
  mouth, a second varying part the eye state (`Mouth-{mouth}-{eyes}`, mouths AI ...
  rest, eyes `EyesOpen` / `EyesClosed`; the state every mouth has is "open");
- the attribute order, settings most faces of the type set, the path style
  (absolute, '/'), and how image files are named (`<base>_<mouth>_<eo|ec>`).

It is kept with the stored layout (`adapter.xlights.face_format`); each prop's
faces are stored generically (`faces`: name, kind images / nodes, mouths x eyes).
A layout without image faces falls back to the format learned from the user's
2025.13.1 layout, shipped as `learned/faces-2025.13.1.json`, with a warning. A
later xLights that renames the keys is followed as soon as one face made in it
is in the layout ('layout' again). `face format` shows what was learned, `face
list` the faces per prop, `inspect faces` both.

**2. Face builder** (0.19.0, `face build MODEL IMAGE [--name] [--mouth x,y,w,h]
[--eyes x,y,w,h/x,y,w,h] [--out DIR]`; generic code in `seqtool/faces/build.py`,
Pillow installed on demand):
- The image is put on the prop's grid (render buffer, e.g. 150x50): scaled to fit
  and centred, nearest-neighbour for pixel art.
- Detection: background = the corner colour (or transparent); skin = the face's
  most common colour; features = blobs of other colours inside the face. The
  mouth is the widest blob in the lower half; the eyes the best matching pair
  above it. Both can be given in grid pixels; what was found is printed with the
  options to change it.
- The mouth is painted over with skin, then each mouth shape is drawn from a
  table (`preferences/faces.json` `mouth_shapes`: width and opening as fractions
  of the face's own mouth width, round, teeth top / both, tongue, FV teeth on the
  lip, MBP thicker lips). Openings drop mostly downwards (the jaw). Eyes closed =
  each eye painted over and a line at its lower third, in the eye colour.
- Every mouth with eyes open and closed (20 images), named as the learned format
  does, in `<name>-face/` next to the image; a contact sheet `<name>-sheet.png`;
  mouths that came out identical at that size are named, with `--mouth`.
- The face definition is written as the learned `faceInfo` line
  (`<name>.faceInfo.xml`, also printed) with the images' absolute paths, plus the
  steps to paste it into the model in xlights_rgbeffects.xml (xLights closed, a
  copy kept), as the user chose (no patched rgbeffects yet).

**3. Phonemes** (0.19.1, `music/phonemes.py`, `preferences/faces.json` `phonemes`).
Each timed word is looked up, its ARPAbet sounds mapped to the 10 mouths (the
usual Papagayo-style table, `phonemes.mapping`) and spread over the word: vowels
get twice a consonant's share; a word shorter than its sounds' frames drops
consonants first, so every mouth lasts at least a frame. Dictionaries, tried in
order (`phonemes.dictionaries`, the user's choice): `cmudict` by default - the
CMU Pronouncing Dictionary (BSD-style), downloaded once on first use after asking
(`phonemes.cmudict_url`, kept in seqtool-prefs/cache/) - or paths to files in the
same format (xLights' own standard_dictionary / user_dictionary, or the user's).
**The user's own pronunciations** (0.19.2) are an add-on dictionary in the same
format, checked first: `seqtool-prefs/pronunciations.dict` (made with a short
how-to header the first time a dictionary is needed; edited in any editor; read
again whenever it changes), or the file given with `--dictionary FILE` on
`lyrics`, `run`, `demo` and `xlights-export` - remembered (answers.json
`dictionary`) until another `--dictionary`; `--dictionary default` goes back to
pronunciations.dict. (0.19.1's `phonemes.words` preference is gone.) Words found
nowhere are guessed from their spelling and listed, each as a ready line
(`sleigh  S L EY`) to correct and paste into the add-on dictionary. The export writes them as the third layer of `seqtool-lyrics` (phrases,
words, phonemes) whenever the lyrics have word times and a dictionary is there
(without one it says so rather than guessing every word); `lyrics phonemes` shows
where the sounds came from and the first lines' mouths.

**4. Singing** (0.19.1). Kit v11 (0.19.2) learns xLights' Faces effect: its face
definition and timing-track settings (taken as text: the encoder's new `text`
kind writes the face's name and `seqtool-lyrics` into the learned keys). The
timing-track step says how to make a track xLights will list there (it must be
broken down: Breakdown Phrases, then Breakdown Words). Kit v10's "Eyes: Auto"
step is gone: Auto is already the default, so the step could never see a change
(the user was stuck at "no change since the previous step"); the eyes keep the
default. `face use PROP FACE [--over]` (`face use PROP off`; `face use` lists them)
sets `targets.PROP.face`. Such a prop sings each lyric line, from `sing.lead`
(0.15 s) before to `sing.tail` (0.25 s) after, lines closer than `sing.join` (1 s)
joined; `sing.mode` `alone` (default) rests the prop's other layers there, `over`
(--over) keeps them under the face. The face plan is the prop's top layer; a prop
that a group sequences gets its own row, written after the group's so it wins.
It is not limited by the top pass (a face keeps singing while a top group plays).
No lyrics, lyrics without word times, an unknown face name or an unusable prop are
said in the run summary (`diagnostics.faces`). `explain PROP @T` says when and
with which face it sings; the GUI shows a pink face lane with a face sketch.

**5. Seeing and pasting a face** (0.19.2).
- **Detection** (0.19.4): the background is everything reachable from the
  image's edges through transparent pixels or the edges' own colours (so a
  painted background behind the face is not taken for skin); features are blobs
  of other colours surrounded mostly by skin (so a hat or a body is not a
  feature); the eyes are found first (a pair of similar blobs side by side in the
  upper face), then the mouth: the widest blob below the eyes, roughly between
  them. An image bigger than the grid is searched at its own size and the boxes
  are moved onto the grid, so small features survive the scaling. Without a
  mouth, one is placed below the eyes (said, "guessed").
- **`<name>-boxes.png`** (0.19.4): the image as put on the grid, enlarged, with a
  pixel ruler (and a faint pixel grid when large enough) and boxes where the
  mouth (red) and eyes (cyan) are, labelled with their x,y,w,h - the numbers
  `--mouth` / `--eyes` take. (0.20.7: `face show` shows the base image first,
  then the face without eyes and mouth, then this one.)
- `face build` saves the image as put on the grid (`<name>-base.png`) and
  remembers the build (answers.json `built_faces`). Its output ends with the face
  definition in a `{copy}` block: the GUI console shows it in a box with a
  **Copy** button; at a terminal it is also put on the clipboard when a
  clipboard tool is there (wl-copy, xclip, xsel, pbcopy, clip;
  `shellcmds.to_clipboard`) and said so. Step 4 now reads "back here, type
  'layout' so seqtool reads the changed xlights_rgbeffects.xml: then 'face list'
  shows it and 'face use PROP NAME' makes PROP sing with it".
- **Reading the coordinates** (0.19.5): the boxes picture has larger labels on a
  dark backing, and its geometry is saved beside it (`<name>-boxes.json`). In the
  face viewer the pointer's grid pixel shows next to the title ("x 8, y 6"), and
  over a box its label ("eye 8,6,2,2") shows there and as a tooltip - on the
  boxes picture and on every mouth image alike.
- **Marking boxes** (0.19.6): drag a rectangle on any picture in the viewer; it
  shows as x,y,w,h, and "mouth" / "eye" (twice, sorted left to right) build the
  whole command - `face build PROP IMAGE --mouth ... --eyes .../...` from the
  build's own `<name>-build.json` - with Copy and "To the console" (into the
  console line, Enter runs it).
- **Fill colours** (0.19.6, the user's rules): a closed eye is filled with the
  average colour just outside the eye's box (2 pixels round it; the pupils inside
  were wrong), and the old mouth is painted over with the average just outside the
  mouth box. In the mouth box (pixels unlike the surround) the darkest third,
  averaged, is the lips and tongue, the lightest third the teeth when clearly
  lighter (else white). `--debug` lists the colours.
- `face show NAME [--prop PROP]` (also `inspect face NAME`): with the GUI open, a
  panel shows the face's images one at a time - the base image, then each mouth
  with eyes open and closed - flipped with < > or the arrow keys (Esc closes);
  the images are served by `/api/image?i=N`, only the files `face show` listed.
  Without the GUI it lists the files. A face just built is shown from its folder,
  one in the layout from its image paths; node-range faces not yet. `face build`
  opens the panel by itself when the GUI is connected.
- Viewer, 0.20.5: zoom with the mouse wheel, `-` `fit` `+` or the + / - keys (the
  picture scrolls; boxes stay on their pixels). Each eye has its own box: drag one,
  then **left eye** or **right eye** (left and right as the picture shows them;
  `--eyes LEFT/RIGHT`); the marked mouth and eyes stay drawn, labelled, in colour.
  **Colour touch-up** without an image editor: a click on one pixel picks its
  colour; darker / lighter / a colour chooser give the new one; "this picture" or
  "all of the face" replaces exactly that colour (POST `/api/face-recolor`, only on
  the images `face show` listed, never the base or boxes pictures). "All" is
  recorded in `<name>-build.json` `recolor` [[from, to], ...] and `face build`
  re-applies it after building, so a rebuild keeps the touch-ups.
- **Marking pixels instead of boxes** (0.20.7, the user's design - boxes kept too
  much or too little of the colours round the features). The viewer's tools:
  *touch up* (above), *mouth*, *left eye*, *right eye* (click or drag over the
  pixels; each pixel belongs to one feature), *rub out*, *boxes* (the 0.19/0.20.5
  rectangles). Colours: *lips, tongue, teeth, eyelid, eyeball, pupil* - pick one,
  click a pixel; right-click unsets; unset ones come from the marked pixels as
  before (darkest third lips/tongue, lightest teeth, eye's darkest the lashes).
  *save marks* writes `<name>-marks.json` beside the face's pictures
  ({mouth: [[x,y]...], eyes: [left, right], colors, grid}; POST `/api/face-marks`)
  and the command becomes `face build PROP IMAGE --name N --marks FILE`.
  Building from marks (`build.face_from_marks`, `build_marked`): the marked pixels
  are filled from the colours round them - rings peeled in from the edge, then
  smoothed (40 passes of the 4-neighbour average) into a gradient - giving
  `<name>-blank.png`, the face with no eyes or mouth; every mouth shape is drawn
  on it in the marked mouth's bounding box; open eyes are eyeball with a round
  pupil (a third of the eye) when those colours are picked, else the marked pixels
  as they were; closed eyes are the eyelid colour (else the fill) with a lash line
  two thirds down each column. Marks made on another grid size are refused.
  Marked pixels are drawn as coloured borders (0.21: tinted fills hid the pixel's
  real colour); the eye labels sit above the
  eyes, the mouth's below the mouth (they hid the mouth before). The command
  line uses the console's monospace font; the panel's x is red like the
  explain panel's.
- **Marks kept in the picture** (0.20.8, the user's idea - no extra file on the
  command line). *save marks* writes the marks into the face's own source picture
  (the IMAGE of `face build`, from `<name>-build.json`) when it is a PNG: one
  `tEXt` chunk, keyword `seqtool-marks`, JSON, inserted before IEND; the other
  chunks and the pixel data are copied byte for byte (faces/marks.py; written to a
  temporary file, then renamed). `face build PROP IMAGE` uses marks found there by
  itself (unless `--mouth` / `--eyes` / `--no-marks`); marks made on another grid
  size are ignored with a warning. `--marks FILE` still takes a PNG holding marks
  or a `<name>-marks.json`, which is where other picture types (JPEG ...) keep
  them. This is the one place seqtool writes into an input file, as asked; the
  picture itself is unchanged.
- New colour code `{copy}` (common/color.py): text to copy; plain in the
  terminal and in files.

**Still to do:**
- **Node-range faces:** the same shapes mapped to node numbers through the
  CustomModel grid, written as ranges (`26-33,40`).
- **Calibration:** mouth proportions measured on the user's node-range faces
  (bounding box per mouth, relative to AI) blended into the shape table.
- A lyric line animated with its phonemes in the face viewer; several faces
  sharing lines by singer or section.

### Base pass, variations and duration limits (0.20)

**Moments** become a first-class generic list in the matchup (type, span,
groups, reason), so `explain`, `pin` and the critic handle them like segments:
unison hits (the song's strongest downbeats / onsets at section starts and
drops), sweeps (props ordered by layout x or height, stepped across the yard
over a bar or two), call and response (halves by x, alternating on 2-bar
phrases), escalation (by `repeat_index`: chorus 3 involves more groups than
chorus 1). A per-minute budget keeps them from looking gimmicky.

**What member props do during a moment** is a user option (the user: "it could
go either way"): `passes.base.members` = `cut` (members transparent while the
moment plays, as the top pass does now), `over` (members keep playing; the moment
is written as a top layer on their rows, like `react --over`), or `under` (members
keep playing and win; the moment shows only where they are transparent). Per
group: `targets.<group>.base_members`. Note the row rule: a group row comes
first, so `over` cannot be done on the group's own row.

**One-aspect variations** (the user's idea). A long segment is divided on
phrase lines (2 or 4 bars) and each part changes exactly one aspect: the colours
(palette rotation), the direction, or the effect itself (keeping colours and
settings). Automatic: `passes.variation` (`aspect: auto|color|direction|effect`,
`every` in bars), used where a segment would otherwise run past the maximum
length; seeded, repeats share it. Explicit: `vary TARGET @#N color|direction|
effect [--every 2]`, or `vary @#N ...` for every row in a section; kept per song
by moment, like pins; `explain` says "variation 2 of 4 (colour only)".

**Effect duration limits** (the user's request): `scoring.durations` min / max
per effect (seconds or bars; per family, effect and pass), enforced rather than
only warned about:
- under the minimum, the Viterbi pass may not change effect except at a strong
  section boundary (the validator's short-effect warning becomes a rule);
- past the maximum, a growing cost makes a change - a one-aspect variation first,
  a new effect if that is not enough;
- across the yard, a changes-per-minute budget shared with the moments budget,
  and a critic term, so the sequence doesn't look busy or machine-made;
- reactive plans are exempt (their events set the rhythm), as now;
- validator issues TOO_LONG / TOO_SHORT come with fix commands (`vary`, `pin`,
  `pref scoring.durations...`).


### Promote and demote (0.21)

The user's design: deciding in advance (roles, rules) which groups carry effects is
hard to picture, so the plan you see is changed directly.

- `promote TARGET... @#N|@TIME [--up N | --to GROUP] [--effect E] [--only]`: the
  effect the targets show there (the most common when they differ; `--effect`
  picks) moves to a group holding them all - the closest by default
  (`place_cmd.groups_over`: groups holding every selected prop, smallest first,
  then by distance in the layout's nesting; duplicates like 9.ALL-LAST and
  one-prop groups are skipped), `--up N` that many groups up, `--to` a named one.
  Promoting again (`promote GROUP @#N`) goes further up.
- `demote GROUP @#N|@TIME [--down N | --to props | --to TARGET...]`: the group's
  effect there is handed to what is in it one level down (`place_cmd.children`:
  its groups, and props listed in it directly; a one-prop or unusable group gives
  its props), `--down N` levels, or every prop. The group itself rests there: its
  placed effect is removed, or its own layer gets a 'transparent' pin.
- Both write pins of pass **place** (`how` says where they came from: `pin` lists
  them; `unpin TARGET @#N` undoes one). Promoting replaces effects placed inside
  the group in that section and a 'demoted' transparent pin on it.
- `passes.place_rows` (after pin_rows): each placed target plays its pinned
  effect there (its own parameters and colours); every layer of what is inside it
  - props, smaller groups, detail and enhance layers, its own other layers - rests
  there (faces and borrowed effects stay). Wider targets (1.ALL) are not cut: the
  placed row is written later (exporter rank 2, like pin rows) and wins on its own
  props. Placed targets are planned largest first, so a smaller one placed inside a
  larger one shows over it. Lanes and diffs call the layer "(placed)".
- GUI: Shift+click effects to select several (a yellow dashed outline; a bar says
  how many, with *clear*); Ctrl+click one: the menu starts with "promote ... to"
  (the groups above, closest first, from `GET /api/place?ids=`) and, on a group,
  "demote" one, two, three levels down or to every prop; then the effect choices.
- Explain (0.21): the first line says who carries a prop - "X is sequenced as part
  of group G" or, for a prop on its own, its groups closest first and why none
  carries it (`why_target`; worked out from the layout's analysis for plans made
  before 0.20.7).
- 0.21.1 (the user's review):
  - **Whole rows**: `promote TARGET --all [--to G]` / `demote GROUP --all`: every
    section's effect, each pinned in its own section (no repeats); sections where
    the row shows nothing are skipped. GUI: Ctrl+click a row's name.
  - **Candidates**: every group holding the selection is offered, closest first
    (0.21.2: also a group holding nothing but the selected prop, and twins of a
    closer group - 6.Wise-all was still missing; only a selected group's twins that
    aren't its parents are left out; up to 12 in the GUI menu);
    groups that hold the selection but can't be used are listed, dimmed, with why.
    A selected group's parents come first (`containing_groups` takes groups).
  - **Unpin**: a pin is found from any section it covers - its own, a repeat (unless
    --only), or the whole song (`pins.covers`); `unpin X (placed) @T` falls back to
    any layer of X; when nothing matches, X's own pins are listed. The pins removed
    are listed.
  - **GUI**: tooltips on effects and row names say what click, Ctrl+click and
    Shift+click do; with two effects selected, *compare* lists effect, settings,
    colours and pinned side by side, differences marked *; *hide empty* (beside
    *fold*, as "fold moments" is now called) hides rows with no lit effect of their own.
  - **Section headings**: each goes on the first of three rows free at its start;
    headings that fit their section keep the top row; one with no room is left to
    the hover text (narrow sections overwrote each other).
- 0.21.3 (the user's review):
  - `promote TARGET --list` and the GUI menu list every group the target is in
    (closest first, as `groups` shows them) with why it isn't offered: unusable
    (its reason), doesn't hold all of the selection, or the selected group itself.
    The list says which models file it reads - the one the song's last run used.
  - A placed effect the target can't play (pinned, but not possible) was dropped
    silently: it is now said after the command ("can't play on it ... promote again
    with --effect").
  - History: `seqtool-prefs/history.txt` (renamed from `history`); each session
    (the prompt, or the GUI started on its own) begins with a `# session started
    DATE TIME (prompt|gui)` line; '#' lines are not commands.
  - `songs` (common/songs_cmd.py): the songs with kept settings (pins, section edits,
    seeds, borrowed, reactions ...) and the current one; `songs forget N|NAME`
    (asks; undo brings it back) and `songs forget --current`. Baselines are only a
    list of songs to compare: `baseline remove` says the settings and the current
    song are kept.
- `layout --forget` (0.21.2): the stored layout is moved aside to
  `seqtool-prefs/layout-forgotten-DATE/`, so seqtool has none until the next `layout
  PATH`; `layout OTHER` simply replaces it. `help layout` says both, and that roles,
  rules, pins and preferences stay in seqtool-prefs/ and apply by name.
- `models` (0.21.1): the column is "nodes"; groups closest first (`containing_groups`);
  `models PATTERN --disable` / `--enable` sets `targets.NAME.enabled` for every
  matching prop (not sequenced: "disabled by you"); the layout-level way is
  `pref xlights.exclude_models`.

### Reactions per song and per section (0.21.4)

The user's request. `react TARGET PRESET` (preferences, every song) stays; added:
- `react TARGET PRESET --song` - this song only; `react TARGET PRESET @#N|@TIME
  [--only]` - this song, that section and (unless --only) its repeats; `react TARGET
  off @#N` / `off --song` - no reaction there / none for this song. Kept in songs.json
  `react` [{target, at, preset, over, repeats}], like pins (undo covers them; `songs`
  counts them). `react` alone lists this song's, then the preferences'.
- Engine: per target, the settings in order - preferences, then the song's - each
  with its spans (whole song, or the section's); later ones win where they overlap.
  Each lit setting's reactive plan is cut to its spans; without --over the normal
  effects give way only there. The parts are merged into one react row per layer
  (`react_parts` [{spans, react, scope}]); explain names the setting that applies at
  the time ("this song, these sections: ...").
- GUI: the Ctrl+click effect menu has "react to the music": every preset, each with
  *here* (this section and its repeats; a click on the name does the same) and *song*;
  *no reaction* on react rows.
- The exporter writes the plans that share a layer of a row in one time order
  (several plans on layer 0 were written one after the other).

### GUI and session details (0.21.4, 0.21.5)

- 0.21.6: `groups ` completes group names (then props), `models ` prop names - unused
  ones too; a path typed (./, /, ~) completes files. A second "groups" key in
  COMMAND_WORDS had silently replaced the first: a static test now forbids a key
  written twice in one dict literal anywhere in seqtool.
- 0.21.5 (the user's review):
  - Folders are shown with a trailing '/' (`paths.show`, `pwd`, `cd`), so they are
    clearly not files.
  - An effect has one small icon: the pin when it is pinned, else '...' on the hovered
    effect; either opens the effect's menu, which now starts with pin / unpin and
    reroll (the die on short effects hid their text). The row's own pin and die, in
    the name column, stay.
  - A prop with effects you placed, pinned or made react keeps a row of its own at
    the top level; it was under its group's closed triangle (Wise1R-3D).
  - Reactions no longer erase placed, pinned, face or borrowed rows of the same
    target: they are cut where those play (a song reaction emptied Wise1R-3D's
    placed row - "pin ... (place) not used").

- Legend tooltips: each colour lists its effects and, in parentheses, the xLights
  effect each is written as (from the learned kit; "not learned yet" otherwise) -
  `family_effects` in the timeline data.
- `xlights-export`: the audio is looked for beside the results, in the song's folder
  (the parent of `<song>-seqtool/`), the working folder, and then the song as it was
  given ('last_audio', or the same file in a folder songs were used from, same
  checksum) - it said "audio file not found" for results in the subfolder.
- Completion: nothing chosen when the list opens; the first Up chooses the first
  item, the first Down the last (the user's rule), no wrapping. Files, props and
  groups are listed alphabetically, any case, numbers in order.
- Working folder: an interactive session (the prompt, or the GUI on its own) works in
  the current song's folder - relative paths and completion start there - and moves to
  a new current song's folder after the command that made it current (never during a
  command). The preference folder is fixed when seqtool starts and doesn't move.

### The GUI workflow (0.21.7 -, the user's design)

Steps: 1. Layout, 2. Faces, 3. Song (or an .xsq), 4. Lyrics, 5. Effects, 6. Export,
any of them again at any time. Rule: every GUI action is an ordinary command run in
the console (history, undo, and you see what a click does).

Phase A (0.21.7):
- **Step bar** under the menu bar (`gui/steps.py`, GET `/api/steps`): each step with a
  dot (done / to do / out of date), a short line, a click that does or repeats it, and
  a menu (▾) for the rest. Layout: read it again (`layout PATH`), another one, groups,
  props, forget. Faces: build one from an image (then the prop), show one. Song:
  analyse and plan again (`run --audio`), another song, open an .xsq. Lyrics: show,
  transcribe (only when you ask - it can take minutes), import a file. Effects: plan
  again (`run`), or with an .xsq opened as it is `open-xsq --fill`; reroll, pins,
  reactions, undo. Export: `xlights-export`; out of date when the plan is newer.
  Reloaded after every command and every change.
- **File picker** (GET `/api/browse?dir=&kind=`): seqtool lists the folders itself (a
  page can't see file paths) - sub-folders ('/') and files of the kind, alphabetically,
  hidden ones left out, starting in the working folder (the current song's), with up,
  home, recent folders, a path box, and "use this folder" for a show folder.
- **Dropped files** (POST `/api/upload?name=`, raw body): kept in
  `seqtool-uploads/` in the working folder, then opened by their kind - layout (.xml;
  said to be a copy that doesn't follow later xLights changes), song, .xsq, face image,
  lyrics. The browser gives the content, not the path, so the picker is the way that
  follows the original file.
- **`open-xsq Song.xsq [--audio SONG]`** (matchup/borrow.py): the audio the .xsq names
  (its mediaFile, the same name beside it or in a folder songs were used from) is
  analysed with `run`, then every row of the .xsq is borrowed for the whole song and
  `borrowed.only` is set: the engine keeps only pinned / placed / reacting / face /
  borrowed effects - nothing of seqtool's own. `open-xsq --fill` lets seqtool plan
  the rest, `--as-is` goes back. The song's own pins and reactions stay (said).
- Exporter: plans that share a layer are written in one time order (0.21.4).

## 13g. What seqtool does now (0.21.8 - 0.24.58)

The current state of what was added since 0.21.7, by topic; how and why each came about, release by
release, is in REVISIONS.md.

- **GUI**: a step bar (load, song, plan, export), panels for layout, palette, feel and preferences,
  a console that runs ordinary commands, a magnifier for words, phrases, sections, cues and voice
  marks. Every change is recorded at once and the plan is made in a child process a few seconds
  after the last one (`general.replan_after`); `CMD --later` and `replan` do the same anywhere.
- **Session**: `start` runs `general.session_start` (doctor, sections, feel, `xlights-kit --update`
  when the training lacks steps) quietly; a command module may say `at_start()`. Progress lines
  rewrite one line. Missing packages are one line with their fix. Windows consoles get their
  virtual-terminal mode switched on for colours.
- **Input forms**: `@#N`, `@TIME`, `@vocals`, `@WORD[#n]`; near spellings of names, sections and
  words are taken (`general.fuzzy`); quoted words stay words; seqtool's own options work before or
  after the command. `batch` runs several commands as one change and one undo step.
- **Music**: Demucs stems give kick, snare, hat, bass and melody events; lyrics come from LRC
  (`[0:12.5]` or `0:12.5` lines), Audacity labels or plain text timed by Whisper; `{VOICE}` codes
  (inside words too) give each word its voice.
- **Faces**: singing is the reaction preset `sing`; `face use` puts a face over the prop's other
  effects (`--no-over`: they rest); several faces on one prop with `--area`.
- **Creative controls**: `feel` (busy, intensity, warmth, unison - per section too), `palette`
  (the music's style, a pick, a hue, or your own colours and accent), `cue` (your trigger marks;
  tagged `call` / `response` they are call-and-response marks instead).
- **Pins**: settings by name (`density=dense`, choices, levels, text, `area`, `render`), glides
  (`a..b`, over the pin's whole span), `rotation`, `from=` / `until=` (part of a section).
  `adjust` puts settings over whatever plays (faces and reactions too) without choosing the effect.
- **The picture effect**: pinned only; a file outside the show folder is copied into it.
- **Definitions** (`define`): named terms at show / song / section level, for kinds of props,
  groups or props, with an optional machine form.
- **Choreographies** (`choreo`): a definition's steps played on the props inside the pinned target
  (matchup/choreo.py): effects, motifs, reactions, per events (words, beats, onsets, cues, calls),
  every / count / only, spread each / cycle / pitch, order, colours, keyframes, generators, and
  submodels relative to each prop (`/seqtool-10oclock`, from `submodel angles`).
- **Call and response** (matchup/calls.py): from tagged cues, continued through the section and
  its repeats; events call, response, call_phrase, response_phrase, pair.
- **The song's score** (`score`): the song's settings and directions as a batch file; `score apply`
  makes the song so again; written beside every export.
- **xLights**: the kit also learns Render Style, Pictures, value curves (ramp and custom, from
  what changes between three saves) and Roto-Zoom rotation (steps labelled by effect or area;
  `status` reports a training that lacks steps); the exporter writes value curves for
  glides, rotation on any effect, per-model render style, absolute channels from
  xlights_networks.xml; `fseqdump.py` reads a rendered .fseq.
- **Sharing**: `bundle` / `bundle --open` carry a show's and song's working files; `demo --bundle`;
  `update` (and a daily check at start, `general.check_updates`) gets newer versions from the
  project's GitHub page (the master branch for now).
- **Shared building blocks** (matchup/parts.py): one segment builder, one settings reader, one
  duration reader and one keyframe collapse for pins, reactions, choreographies and moments.
- **Claude**: the seqtool-direction skill (skills/) translates plain-language direction; `direct`
  is seqtool's own small offline translator (preferences/intents.json).

## 14. Milestones (revised)

| # | Milestone | Status |
|---|---|---|
| 1 | Schemas, conventions, CLI, tests | done |
| 2 | Music analyzer + classifier (synthetic ground-truth tests) | done; tuning on the user's 4-song baseline |
| 3 | Generic layout, wizard, model analyzer, xLights import | done; verified on the user's full layout |
| 4–5 | Static + temporal matchup, motifs, feedback loop | done |
| 6 | xLights live kit wizard + encoding + exporter | done; kit v11 (Faces, 0.19.2) |
| 7 | Full pipeline to .xsq that opens in xLights | done (opened in 2025.13.1) |
| 8 | Passes (top/detail/enhance), presets, rules, lyrics, GUI previews | done (rev 21-25, 0.18); xLights checks via `xlights-export --checks` (§13d) |
| 9 | Singing faces; base pass with variations and duration limits; style training | next (§13e, §13f) |
| 10 | Round trip of xLights edits; whole-yard preview | on hold |
| 11 | Photo-based props; WebSocket GUI; trackED as a GUI | not now |

## 15. Versions and stale data

**Versioning.**
- The tool version lives in the top-level `VERSION` file (also in
  `seqtool/__init__.py` and `pyproject.toml`; the title of this file names it).
- **Bump MINOR after every major update**: anything that changes analysis,
  scoring, or output behaviour. Bump PATCH for fixes that don't change results.
  Bump MAJOR for breaking CLI or file-layout changes.
- Schema versions (§3) are independent of the tool version.
- `seqtool --version` prints the version.
- **Doc revisions:** this file's revision number moves with each design change
  (rev 3 = seqtool 0.2.0, rev 4 = 0.3.0, rev 5 = 0.4.0, rev 6 = 0.5.0).

**Learned xLights training is versioned separately.** Every
observations.json records the kit_version it was made with. kit.json holds
the current kit_version (bumped whenever the steps change) and
`min_compatible`, the oldest version whose results are still usable as-is.
- **Older but compatible** (e.g. v4 under v5: only wording changed, and the
  data format is converted on load): used as-is, with a note in `inspect
  xlights` and export.
- **Older than min_compatible:** export refuses and asks for a re-run of
  `xlights-kit`.

These checks are separate from the artifact staleness checks below, which
cover the pipeline's own files.

**What makes an artifact stale.**
- It was made by a different MAJOR.MINOR of seqtool.
- A source file in its `lineage` changed (audio, layout, rgbeffects, preferences).
- The intermediate file it was built from no longer has the recorded content hash.
- A recorded setting differs from the current one (e.g. `frame_interval`, stems on or off).
- A derived file it was measured from is missing or changed (the vocal stem).

**What the toolchain does about it.**
- **Pipeline (`run` / `demo`):** music, profile, layout, and models files are
  reused when fresh. When stale, the policy applies, set by `--stale` or
  `SEQTOOL_STALE`:
  - `ask` (default): prompt to rebuild; rebuild when non-interactive.
  - `rebuild`: always rebuild.
  - `warn`: report and reuse anyway.
  Matchup and validation are cheap and are always recomputed.
- **Single stages:** a stage warns when an input was made by another version,
  or was built from a different upstream file than the one supplied. The
  validator also records this as a `STALE_INPUT` warning.
- **`seqtool status [DIR…]`:** lists every artifact as ok or STALE, with
  reasons, and exits 1 if any are stale.
