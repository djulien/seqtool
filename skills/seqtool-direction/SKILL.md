---
name: "seqtool-direction"
description: "(seqtool 0.24.56) Help with seqtool, which turns a song and an xLights layout into an xLights sequence (.xsq): getting started and how to use it, and turning creative direction (\"bigger chorus\", \"calmer intro\", \"flash on 'star'\") into seqtool commands, running them, checking the result and exporting. Use whenever the user mentions seqtool, or sequencing a song for an xLights light show."
---

# Directing a seqtool sequence

seqtool turns a song plus an xLights layout into an .xsq. It plans effects itself; this skill
steers it from plain-language direction. **The tool does the work; you translate intent into
its commands, run them, verify, and report.** Never edit seqtool's JSON files or the .xsq by
hand - every change goes through a command, so it can be undone and survives re-runs.

**Never present a guess as fact.** A prop, time, section, term or setting you assumed is said as
assumed ("I took 'the columns' as Columns"), and something you didn't check is not
reported as done.

**Your role: the user's guide to using seqtool, not its developer.** Explain, translate, run and
report. When seqtool fails or misbehaves, say in plain words what happened and what the user can
do now (the workaround, or what to install); if it looks like a bug in seqtool, say so in one
line and offer the details for its developer. Don't read or patch seqtool's source, or design
changes to it, unless the user asks you to.

**Know only what you were told.** Use prop names, song parts, terms and effects that the user
gave you or that seqtool showed you in this session - nothing from examples or elsewhere.

**Unclear directions - ask or decide?** At the start, read `pref general.directions`. Empty (not
chosen yet, or seqtool older than 0.24.54): ask the user once, with your first questions -
"When a direction is unclear, should I always ask first, or decide and tell you what I took?" -
and store the answer: `pref general.directions = ask` (or `decide`); a later "from now on ..."
changes it the same way. Then follow it: **ask** - ask before running anything you would have to
guess at; **decide** - take the most reasonable reading, say which, and do it (still ask when a
wrong guess would be expensive to undo: writing into the user's xLights files, deleting).

Written for **seqtool 0.24.56** (this copy comes in that version's download, beside seqtool.py;
it works with later versions too).

## Running it

- Command form: `python seqtool.py CMD ...` (or `./seqtool-X.Y.Z.pyz CMD ...`), run in the show's
  working folder (`pwd` says which; `cd FOLDER` changes it).
- **Check the version first:** `seqtool --version`. If seqtool says a newer version is available,
  tell the user (on their computer, seqtool's `update` command gets it); don't fetch one here unless
  they ask. Older than 0.24.56: no `update`; older than 0.24.55: lyrics times written
  `0:12.50 words` (no brackets) aren't read - use `[0:12.50] words`; older than 0.24.54: no `general.directions`
  (ask the user's preference anyway, and keep it in mind for the session); older than 0.24.53: no `"react"` steps; older than 0.24.50: no `score`; older than 0.24.49: no `calls`, cue tags,
  `submodel angles`, `"only"`, `spread: pitch`; older than 0.24.48: no glides (`a..b`),
  `rotation=` or choreography `keyframes`; older than 0.24.47: no `choreo`, and a
  face's other effects rest unless `--over`; older than 0.24.46: no `define`, no
  `picture` effect, no `palette colors`; older than 0.24.37: no `onset=` / `offset=`
  (`from=` / `until=`) on pins - split the section instead; older than 0.24.36: no pin settings
  (`NAME=VALUE`), no `render=`, no `demo --bundle`; older than 0.24.34: no `start`, `bundle`,
  `@WORD` times, and seqtool's own options (`--stale=...`) only before the command name; older
  than 0.24.33: no `direct`; older than 0.24.32: `models` has no absolute
  channels; older than 0.24.31: no `fseqdump.py`; older than 0.24.30: no `feel`; older
  than 0.24.29: no `batch` (run commands one by one); older than 0.24.25: no `@vocals`, `palette`,
  `react ... --on` - say what can't be done and suggest updating. Newer: fine.
- Unattended: set `SEQTOOL_NONINTERACTIVE=1` and pass `--stale=rebuild` so nothing waits for an
  answer - it is seqtool's own option: `seqtool --stale=rebuild batch "..."` (0.24.34 and later
  also take it after the command). If a command would ask a question, that is a decision for the
  user - stop and ask.
- Every change command re-plans by itself (the analysis is reused; 10 s or more on a big show).
  **One direction = one `batch`**: `batch "feel intensity high @#5; react Arches beat --over"` (or a
  file, one command per line, `#` comments; `--dry-run` lists them) - one re-plan at the end, one
  undo step. If a command fails the batch stops and nothing of it is kept; fix it and run it again.
  `run`, `gui`, `undo`, `redo` and `batch` can't be inside a batch. (`CMD --later` records a
  change without a new plan; `replan` makes it - the GUI does that for every change, and makes the plan a few seconds after the last one.) **After a `sections split` /
  `merge` in the same batch, refer to moments by time (`@2`, `@6.5`), not `@#N`**: the section
  numbers change only when the batch's plan is made.
- **Which show?** Before changing anything, make sure you work on the user's own show, not the
  demo: `status` / `layout` show the song and the layout's file (`demo-song`, `seqtool-demo/` =
  the demo). If the session isn't linked to the user's computer, ask them to run `seqtool bundle`
  there and upload the .zip; then `seqtool bundle --open FILE.zip` and work in the folder it
  prints (`cd .../song`, with `SEQTOOL_PREFS=.../prefs` on every command). Several bundles
  (uploaded or already opened): use the one the user names ("using My_Song" - the closest
  file or folder name; ask if two fit equally), else the newest, and say which. Only the demo at hand:
  say so in your first line, and that the result is a try-out, not their show. (The demo as a
  show of its own, to try the skill on: `seqtool demo --bundle`, then `bundle --open` it.)
- **First time - a new user** (no bundle, no layout yet; `status` says so). Keep it simple and
  in order, one step at a time, and offer more detail rather than giving all of it:
  1. **Where seqtool runs** - ask, with your first questions: on their own computer (you give
     each command, they run it and paste back what it printed), or here in the chat with files
     they upload (you run it). Their computer is needed anyway for learning their xLights
     version (step 4); here, optional parts may not install (Whisper for timing lyrics, Demucs
     for drum / bass / melody stems) - say so if one is needed.
  2. **Getting seqtool going on their computer**: Python 3.10 or newer (`python --version`;
     python.org if not); unzip the download into a folder (or keep the .pyz as it is - one file,
     nothing to unzip); open a terminal in that folder; start seqtool with `python seqtool.py`
     (or `python seqtool-X.Y.Z.pyz`) - it shows the `seqtool>` prompt, where the commands are
     typed (`python seqtool.py gui` opens the browser view instead, with the same commands).
     Say "start seqtool, then type ...", not just the command.
  3. **What seqtool needs**, in one message: the show's `xlights_rgbeffects.xml` (in their
     xLights show folder; `xlights_networks.xml` beside it gives channel numbers) and the song
     (MP3 or WAV). When asking for the song here, say the file stays with this chat: seqtool
     analyses it here and it isn't shared anywhere else. Lyrics are optional: only if they want
     the words to drive effects (singing faces, flashes on a word) - without them seqtool works
     from the music alone. Then `layout FILE`, `run --audio SONG`, and report what it found
     (props, groups, the song's parts).
  4. **Writing the .xsq** needs seqtool to learn their xLights version once: seqtool's
     `xlights-kit` command, on their computer beside xLights (it gives short steps in xLights and
     checks each save). Say so, and offer to plan and explain meanwhile; afterwards a `bundle`
     from their computer brings the training here.
- **Talking about commands**: the first time you mention one, say what it is - "seqtool's
  `doctor` command (it checks the setup)", "seqtool's `start` command" - not just "doctor".
- Start each session with `start` (runs the user's start commands quietly - only problems show;
  `start --no-quiet` everything. By default `doctor`, is
  everything in place; `sections`, the song's parts; `feel`, its creative controls; and
  `xlights-kit --update` when the xLights training lacks steps - it needs the user at the
  seqtool> prompt or the GUI's console: if `start` reports it, tell them; older versions: run
  the first three). Refer to parts as `@#3` (section 3 and its repeats; `--only` for
  just that one), `@1:05.2` / `@65.2` (a moment), `@vocals` (where the singing starts; `@vocals-0.5`), `@star` (where the word 'star' is sung;
  `@star#2` its second time; 0.24.34).
- **Dry run:** when the user says "dry run" (or `--dry-run`) with a direction, translate it and
  show the commands without running them: `batch "CMD; CMD" --dry-run` (and `direct "TEXT"
  --dry-run` if they want seqtool's own reading too). Nothing changes; say what it *would* do.
- **Typos:** read obvious slips the way they were meant ("chrous" = chorus) and say which reading
  you took. seqtool itself takes a near spelling of a name, section or sung word when it is close
  (`general.fuzzy`) and says so; when it is unsure it stops and shows the most likely one - pass
  that on, don't guess further.

## Vocabulary - what you can turn

Start broad, then specific: a `feel` control before many pins.

| Intent | Commands |
|---|---|
| **Broad feel** (0..1, 0.5 = neutral) | `feel busy V` (how often effects change), `feel intensity V [@#3]` (calm ... intense effects; per section too), `feel warmth V` (cool ... warm colours), `feel unison V` (each prop its own ... whole-yard moments); `feel NAME reset`, `feel reset`; values also `low` / `neutral` / `high` |
| A specific effect somewhere | `pin PROP @#3 EFFECT`; whole song: `pin PROP EFFECT`; keep what's there: `pin PROP @#3`; black out: `pin PROP @#3 dark`; undo: `unpin PROP [@#3]` |
| ... for part of the section | `onset=2b` / `offset=25%` / `from=@0:03` / `until=@vocals` with the pin |
| ... with settings ("dense twinkle", "medium-fast exploding meteors") | `pin PROP @#3 twinkle density=dense`, `pin Matrix @#1 meteors direction=explode speed=medium-fast` - `effects EFFECT` lists its settings; values 0-1, 0-100%, or low / medium-slow / medium / medium-fast / fast / dense / max; choices by name. Your values use xLights' whole scale |
| A group's effect on each of its props ("each spinner explodes", "in unison but each on its own") vs one picture across the group | `pin GROUP @#3 meteors render=per-model` (or `render=default`: the group's own layout in xLights); for all of its effects: `pref models.targets.GROUP.render = per_model` (`auto`: seqtool picks the better - each effect has its own affinity either way). Writing it needs the kit's Render Style step: if export says so, `xlights-kit --update` |
| A setting that changes over the effect ("speeds up through the chorus") | `pin PROP @#3 bars speed=0.2..0.9` (`a..b..c` evenly spaced) - an xLights value curve once the kit has learned them (`xlights-kit --update`), else short steps |
| Turned / rotated ("the spoke at 10 o'clock") | `rotation=10oclock` (12 = 0, clockwise), `90deg`, or a share of a turn; `rotation=10oclock..7oclock..10oclock` sweeps - on a pin or in a choreography step |
| Different random choices | `reroll [PROP] [@#3]` (pins keep their effect) |
| What a prop likes / avoids | `prefer PROP twinkle=like fire=avoid` (or a weight, e.g. `color_wash=1.5`); by name pattern: `rules add '(?i)flood' prefer=color_wash*1.5` |
| Follow the music | `react PROP PRESET [@#3 \| --song] [--over]` (`presets` lists them: beat, downbeat, onset, energy, beat-chase, onset-sparkle, word-flash, lyric-color, kick/snare/bass/melody with stems ...); off: `react PROP off [@#3 \| --song]` |
| A preset's look on another event, or only on some words | `react PROP LOOK --on EVENT --words w1,w2 --over` (events: beat, downbeat, onset, word, lyric, section, cue, kick, snare, hat, bass, melody) - stored as `LOOK@EVENT[w1\|w2]` |
| A one-off hit (crash, accent) | `cue add @1:05.2 [--for PROP,...] [--len 0.5]` (extra hit for reacting props); a prop that only hits on cues: `react PROP cue-flash --over` |
| Unison / whole-yard moments | `feel unison high`; or by hand `promote PROP... @#3 [--to GROUP]` (the group carries one effect), `demote GROUP @#3` |
| Section boundaries | `sections split 1 @vocals`, `sections merge 3 4`, `sections move 3 @30.2`, `sections type 3 chorus` |
| A section longer / shorter ("enlarge the chorus by 2 bars") | `sections move N+1 @T` - the next section's start later (longer) or earlier (shorter); the last section: its own start; `sections` shows the times (a bar = 4 beats; `move` snaps to the bar) |
| Colours | `feel warmth V`; `palette` (show), `palette STYLE [N] [--hue DEG]`, your own for this song: `palette colors green,purple,orange --accent blue` (names or #RRGGBB); `palette auto` |
| A picture or animated GIF | `pin PROP @#2 picture file=pumpkin.gif [loop=yes] [scale=fit] [transparent=yes] [area=x,y,w,h]` - never chosen by seqtool; the file in the show folder (or a full path: a file outside the show folder is copied into `seqtool-files` beside the song, Enter = yes, and the copy used). Writing it needs the kit's Pictures step (`xlights-kit --update`) |
| Singing faces | `face use PROP FACE [--voice NAME]` - over the prop's other effects, which show behind it (`--no-over`: they rest while it sings); per section `react PROP sing @#3` |
| A choreography (named moves on several props: "both arms wave", "call and response") | `pin TARGET @#3 choreo name="both arms wave"` - plays the definition of that name (its `--data`, see below) on the props inside TARGET, on a layer of their own; TARGET itself shows nothing of its own there |
| Leave a prop out | `models PROP --exact --disable` (its groups still light it - to keep it dark: `pin PROP dark`) |
| Keep a section from an existing sequence | `borrow PROP @#3` (needs `open-xsq` / `xsq-borrow` first) |

## Definitions - the user's terms

The user's own terms ("left arm wave", "the slow phrase", "the call pattern") are kept with
`define`, at levels: the whole show (`--show`), a kind of prop / group / prop (`--for X`), this
song (the default), a section (`@#N`, `--only`). The most specific one that applies wins.

- **Before translating**, read the song's score - `score` (everything already set for this song:
  sections, colours, feel, terms, cues, pins, reactions, earlier directions) - and what applies:
  `define dump [@#N] [--for PROP] --json` (or `define get NAME --for PROP @TIME`). Use those
  instead of guessing or asking again, and don't redo what is already there.
- **Record each direction** you carry out, in the same batch: `score note "the user's words"
  --commands "the commands it became"` - the score is the song's record (written beside each
  exported .xsq; `score apply FILE` makes the song so again).
- **When the user defines terms** (a DEFINITIONS block, "by X I mean ..."), store each one at the
  level it belongs to - props' motifs for the show (`define set "left arm wave" --show --for
  spinners ...`), song-only terms for the song - and say where. Put text with apostrophes or
  quotes in double quotes (`define set "slow phrase" "the last 'Sing it all night long.'"`).
- A definition's text is for reading; `--data JSON` is the machine form a `choreo` pin plays:
  keep it to what was said. Give each kind of prop its own version (`--for spinners`, `--for
  Matrix`, `--for LeftColumn`): a choreography on a group plays each prop's version; one
  without `--for` is their defaults (or plays on the target when none is for anything).

## Choreographies - the machine form

`--data` is one step or `{"steps": [...]}`. A step: `"effect"` (+ `"settings": {...}` as `pin`
takes them), or `"motif": "other name"` / `"steps": [...]` (played inside this step's time);
`"target"` (a prop, group or submodel `Parent/Sub`); `"at"` / `"length"` (`0.5`, `"1b"`,
`"2beats"`, `"25%"`); `"per"` (word, last_word, first_word, lyric, beat, downbeat, onset, cue, or
an analysis event) with `"words": [...]`; `"every": "1b"` or `"count": 5`; `"spread"`: `"each"`
(every prop inside at once) / `"cycle"` (one prop per time, in turn); `"color": "blue"` or
`"colors": [...]` (one per time); `"generator": "file.py:fn"` (the user's Python);
`"react": "beat-chase"` (a reaction preset, its events inside the step's time - `presets` lists
them); `"keyframes": {"0%": {"rotation": "10oclock"}, "50%": {"rotation": "7oclock"}, "100%":
{"rotation": "10oclock"}}` (settings glide between them; `"easing"`: linear by default,
`ease-in-out`, `step-end` holds).
`"only": [1, -1]` / `"last"` / `"odd"` picks which of the times; `"spread": "pitch"` puts each
time on a prop by how high it sounds (low = left); `"order": "right_to_left"`; `"target":
"/seqtool-10oclock"` = that submodel of each prop (make them: `submodel angles GROUP --write`,
with xLights closed - ask the user first). A step with `"colors"` around `"steps"` gives the
parts inside one colour per time.

**Call and response**: the user marks the first pair or two with cues and tags them (`cue tag
call @#3`; a phrase tagged `response` says which it is, else phrases take turns); `calls`
shows the pairs seqtool finds in the rest of the section and its repeats. Steps then use
`"per": "call"` (each note), `"response"`, `"call_phrase"`, `"response_phrase"`, `"pair"`.
Tagged cues are no extra hits for reacting props. **Inside a section**: `"per": "lyric",
"only": [-1]` (the last line) with steps per word inside it. E.g. five
flaps on five words: `{"motif": "both arms wave", "per": "word"}`, pinned with `from=` the
phrase's first word.
Store with single quotes around the JSON (`--data '{"effect": "wipe", "length": "1beat"}'`);
`explain PROP @TIME` names the choreography and step of each part; problems are in the plan's
pin notes (`status`).

## Lists of directions

When the user gives several directions at once (a numbered list, one per line, or "and" between
them), make them **one batch**: one re-plan for all, one undo step.

1. Translate every item first. Unclear items: with `ask`, ask about them all in one message before
   running anything; with `decide`, take the most reasonable reading of each and say which.
2. With "dry run": show the whole batch (`batch "...; ..." --dry-run`) and the reading of each
   item, change nothing, and wait for "go".
3. If the user grouped the list ("batch A: 1-3, batch B: 4-6") - or wants to undo parts
   separately - make one batch per group, in order.
4. Within one batch, after a `sections split` / `merge` refer to moments by time, not `@#N`.
5. Put a `score note "ITEM" --commands "..."` in the batch for each item.
6. If the batch stops on an item (nothing of it is kept), fix or drop that item, say which and
   why, and run the batch again. Report per item: done / changed to ... / not possible (and what
   seqtool would need).

## Translating direction

Handle unclear directions as `general.directions` says (top of this skill). Typical mappings:

- **"Enlarge / reduce X by N (bars, beats, s)"**: timing - X longer or shorter (`sections move`),
  every repeat of X unless one is named ("the second chorus"). Without "by ...", "enlarge" /
  "reduce" lean to size or intensity: treat as bigger / calmer, and say so.
- **"Bigger / more energy" (a section)**: `feel intensity high @#N`; reactions on the main props
  `react PROP beat-chase @#N --over` or `onset-sparkle`; `reroll @#N` if still dull.
- **"Calmer / gentler"**: `feel intensity low [@#N]`, `feel busy low`; `react PROP off @#N`.
- **"Too busy / too jumpy"**: `feel busy 0.3`. **"Static / boring"**: `feel busy 0.7`.
- **"More together / more coordinated"**: `feel unison high`. **"More variety"**: `feel unison low`.
- **"Warmer / cooler"**: `feel warmth 0.75` / `0.25`; a different look: `palette STYLE N --hue DEG`.
- **"Build up to the chorus"**: `sections split` a build before it (`sections type N build`), then
  `feel intensity high @#N` and energy-following reactions there (`energy`, `energy-density`).
- **"Dark until the vocals"**: `pin PROP dark until=@vocals` (the sections before it: `pin PROP @#N --only dark`).
- **Part of a section** ("meteors until the singing", "start 2 bars in", "stop for the last quarter"):
  `pin PROP EFFECT until=@vocals` (with an @TIME the section can be left out - the time says it;
  a word sung more than once is asked about, or `@#N` takes the one sung there), `onset=2b`,
  `offset=25%` (s, b = bars, beats, % of the section, or `@TIME`) - don't split a section just for that; the rest of the section: nothing
  from the pin (what is underneath shows).
- **"X does a move" with the user's own word for the move** ("both arms wave on the last word"):
  `define get "both arms wave"`; with a machine form, `pin TARGET @#N choreo name="..."` (a
  wrapper definition, e.g. `{"motif": "both arms wave", "per": "last_word"}`, for the timing);
  without one, write it from the text (`define set ... --data`) and say what you wrote.
- **"Flash on the word 'star'"**: `react PROP word-flash --words star --over`.
- **"The spinners bounce on the words"**: `react Spinners spoke-bounce --on word --over`.
- **"Hit the cymbal crash at 1:05"**: `cue add @1:05` (+ a reaction on the props that should hit).

Prefer the smallest change that does it: a feel control before many pins, one section before the
whole song, a pin before a preference, a preference before a rule.

## Verify before reporting

1. Read the batch's output: it lists what changed per section (and colours), and warns when
   something didn't take ("pin ... not used: ...", "no visible change", a prop that doesn't react).
2. Check the intent landed: `explain PROP @TIME`, `explain music @TIME`, `feel`, `pin`, `react`,
   `cue`, `palette`.
3. If something didn't take, fix it or say plainly what couldn't be done and why.
   **When seqtool can't do it at all**, say so in one line and then, in one or two more, what
   would be needed in seqtool's terms - the command or option, and the setting it would write in
   xLights (e.g. "seqtool would need a per-effect render style on group effects - xLights' 'Per
   Model Default' buffer style - so one meteors burst plays on each spinner"). Don't design it
   further; offer it as a change for seqtool, and suggest the xLights way meanwhile.
4. A re-plan doesn't write the .xsq. When the user wants it in xLights: `xlights-export`. If it
   reports settings it couldn't write ("left as xLights' default"), pass that on with its fix
   (e.g. `xlights-kit --redo EFFECT.STEP`).
5. **What xLights actually rendered** (after the user renders and saves in xLights, or through
   xlDo): the stand-alone `python fseqdump.py Song.fseq` (beside seqtool.py; what it holds),
   `python fseqdump.py Song.fseq --start CH --count N --from T --to T`
   (channels as hex, 3 per RGB pixel; `--json` for data; zstd files need the `zstandard` package -
   on a terminal fseqdump offers to install it). Use it to confirm e.g. a prop is dark in a section
   or flashes at a word. A prop's channels: `models PROP --exact` (the channels column is absolute
   when xlights_networks.xml is beside xlights_rgbeffects.xml; it prints the fseqdump command).

## Reporting

Tell the user in a few lines what you changed (in their words, then the commands), what you
checked, and anything that didn't work. Mention `undo` (the whole batch). They can look and
fine-tune in the GUI (`gui`; 2. Song > feel has the controls as sliders).

## seqtool's own offline translator: `direct`

`direct "make the chorus bigger"` does a small version of this skill without Claude: it matches
the text against a list of intents (`direct --list`; preferences/intents.json) and runs the
commands after asking. The user may use it when offline. You don't need it - translate yourself -
but when asked how well it works, or to improve it:

1. Translate each line of `direct-cases.txt` (beside this file) yourself, *without* looking at
   `direct`'s output, and write `TEXT => CMD; CMD` lines (one direction per line) to a file in
   the show folder, e.g. `direct-cases-claude.txt`.
2. `direct --eval direct-cases-claude.txt` says which come out the same (`--json` for data,
   `direct "TEXT" --dry-run --debug` shows its scores for one).
3. Report the differences: where `direct` is wrong, suggest the phrase or intent to add in
   seqtool-prefs/intents.json (same form as preferences/intents.json); where yours differs only in
   a value or form (0.8 vs high, `--song`), say so - both work.

## Use xLights where it is better

- Phoneme (mouth) timing: xLights' Breakdown Words on the seqtool-lyrics track gives livelier mouths.
- Anything seqtool doesn't model (custom models, moving heads, hand-drawn value curves):
  say so and suggest doing it in xLights after export.