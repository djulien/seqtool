# seqtool - revisions

How seqtool got where it is: the notes written with each release (newest first from 0.24.59 down,
then 0.21.8 - 0.21.10), and the revision log of DESIGN.md. DESIGN.md describes seqtool as it is now.

## Release notes

0.21.8 (the user's review of phase A, and phase B):
- Step bar: a green check for done steps, arrows between the steps (the usual order),
  only a few words on a button ("24 faces", "none", "as the .xsq", "out of date") - the
  names and paths are in the tooltip and menu. The Effects menu says what reroll does:
  every choice that isn't pinned (pinned effects keep their effect, get new settings).
- Under the waveform: "@ 0:12.3 / 3:45.0". A row name's tooltip starts with the whole
  name (the column cuts it).
- `groups`: generic words of a reason ("sequenced as one, in place of the props
  themselves", "widest top group takes over ...") are left out when said in the last
  four rows, and said again every dozen rows; the row's own part stays.
- **Timing tracks** of the .xsq a song was opened from or borrows from are rows at the
  top of the timeline (⏱ NAME, one per row of the track: phrases, words, phonemes). A
  mark's menu: split the section there, move the nearest section start there, start
  sections at every mark of the track in this section, or in the whole song - `sections
  from-timing TRACK [@#N | @FROM-TO] [--layer N]` (the boundaries outside the span stay;
  music.sections.snap applies). `open-xsq` says which tracks there are.
- **Layout panel** (phase B; step 1's menu "groups and props ..."): an overlay with the
  layout's tree - groups as the layout nests them (a duplicate such as 9.ALL-LAST doesn't
  hide 1.ALL), the props each lists directly, then props in no group; filter, expand,
  collapse. Per group: role (auto = the guess, or top / unit / detail / unused: `groups
  NAME --role R`), likes / avoids, reaction. Per prop: sequenced (`models NAME --exact
  --enable|--disable`; unusable ones say why), likes / avoids, reaction (`react NAME
  PRESET|off`). Likes / avoids: the **effect wheel** - the effects round a circle in their
  families' colours; a click goes like -> avoid -> neutral (`prefer NAME EFFECT=like|avoid|
  neutral`, a new command: effect_preferences 1.6 / 0.3, neutral removes it -
  `config.unset`). Reloaded after every command. GET `/api/layout-tree` (gui/steps.py).

0.21.9 (the user's review of phase B, and phases C and D):
- **Preferences window** (⚙ Preferences, right of the step bar; GET `/api/prefs?file=`):
  a tab per preference file; its description; every node (folded when a file is long)
  with its description, every value with what it may be and does (`prefcmd.about`), the
  default, and an editor - a list for choices, a tick for true/false, else the value as
  JSON or text. A change runs `pref FILE/PATH = 'VALUE'`; ✕ runs `pref reset`; filter,
  "yours only".
- Layout panel: each role and reaction in the menus has a short explanation (tooltip).
- **Effect wheel as a pie** (the user's design): a wedge per effect in its family's
  colour; the bright inner part of a wedge is the weight - centre 0.05, the dashed ring
  1 (neutral), the rim 3 - set by clicking anywhere in the wedge (right-click: neutral).
  `prefer TARGET EFFECT=WEIGHT` takes the number (0.05-3; ~1 = neutral).
- The Effects step's menu no longer has 'undo' (it is the ordinary command, for
  everything).
- **Magnifier** (phase C; the 🔍 button by the player): a pane over the console with a
  few seconds of the song in detail - the waveform from a fine envelope (GET
  `/api/peaks?from=&to=&n=`, 200 values a second, made once per song), beats and bars,
  section starts, the lyric lines and their words, the timing tracks; the main waveform
  shows the region. Drag to pan, wheel to zoom, follow the play head, play from the
  view's start. Edits, each a command: drag a section line (`sections move N @T`), a
  line's or a word's edges or the whole of it (`lyrics time L[.W] START END` - a line's
  words move and stretch with it), double-click a word to retype it (`lyrics word L.W
  TEXT`), click a timing mark for its menu; right-click (phase D): split here, merge with
  the section before / after, or set the type. Overlapping boxes: the nearest edge, else
  the latest started. `lyrics` lists lines numbered.

0.21.10 (the user's review, and phase E):
- The effect wheel draws a click at once and sends the command behind it: `actQ` runs a
  command now, or after the one running; a later command with the same key (target and
  effect) replaces the waiting one, so fast clicks send only the last weight. The panel
  reloads after the last queued change.
- **Undo / redo**: buttons beside ⚙ Preferences, and Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) when
  not typing in a box (an empty console line counts as not typing).
- Magnifier: speed (0.25x-1.5x, pitch kept) and volume; "play here" pauses when playing;
  its region on the main waveform can be dragged.
- **Shifting lyrics**: `lyrics shift SECONDS [@FROM]` moves every line from FROM on (the
  line being sung then included; no @: all) and their words; the line before is cut to
  where the moved one starts. The magnifier: Shift+drag a line or word moves it and
  everything after; right-click on the lyrics: -0.5 ... +0.5 s from that line on.
- Face viewer: the buttons stay at the top of its bar; the picture's size in pixels.
- **Phase E, lyrics from an .xsq**: `lyrics from-xsq [TRACK]` - a timing track of the
  song's .xsq (opened or borrowed from): phrases (layer 1) become lines, words (layer 2)
  their words by time; only words: lines at pauses over 0.8 s; no name: the track that
  looks most like lyrics (named "lyric...", else the most labels with letters).
  `open-xsq` says so when the song has no lyrics; step 4's menu and a timing mark's menu
  offer it.

0.24.59 (the user's first real song on Windows):
- `effects picture` (and `effects choreo`) no longer fail: settings that are a file name, text or a
  plain 0-1 value are listed as such.
- `run` no longer says choreo is "not learned by the xLights kit": effects that are only ever
  pinned (choreo, picture) aren't kit steps of their own.
- Windows prompt: seqtool has its own line editor (Tab completion, history with Up / Down,
  Left / Right / Home / End, Esc clears) at the seqtool> prompt and at questions; pyreadline3 is
  no longer loaded (it closed seqtool at start on newer Pythons) and a broken readline anywhere
  falls back to plain input.
- Kit: a step that needs another one first is preceded by it in an update (Pictures: the file is
  chosen again before Scaling, Loop GIF, Transparent Black and Frame Rate) - kit v18; a change
  step's text no longer repeats the effect (the header has it); the Scaling step says what to do.
  `xlights-kit --list` numbers every step with its name and marks the ones not learned;
  `--redo` takes a number, Effect.setting, a whole effect or a structure step (timing, rotation ...).
- GUI: each command in the console has a copy button (the command and all it printed - a batch's
  whole output); zoomed in and scrolled sideways, the row names and the player's controls stay in
  view (and answer clicks).
- `dir` (also `ls`): the files in a folder or matching a pattern, folders first, with size and
  date; `--kind audio|xsq|layout|image|bundle|lyrics|json`, `-r` for the folders below; an audio
  file found gives the `run --audio ...` to type.
- `seqtool.pyz`: a launcher, built with every package, that starts the newest seqtool-X.Y.Z.pyz,
  unpacked seqtool or update folder beside it (`--which` says which).
- The skill asks for a bundle first, and knows `dir` and the launcher.

0.24.58 (the second new-user test, on Windows):
- Paths: `layout c:\documents\show\` works without quotes (backslashes are kept on Windows
  and in drive-letter paths). A pattern that matches nothing, a file that isn't there and a
  name Windows refuses (WinError 123) now say so in one line, with the working folder for a
  relative path; a whole command typed where a file name was asked for is pointed out.
- Layout: the density measure no longer overflows on props with many points in one place.
- Kit: steps are labelled by what they train ("Twinkle [35/79]", "Layer Settings [3/79]"); each
  step shows its keys (save · s skip · b back · a accept · q quit); the working folder is said
  at the start; the tick is a plain √ in the old Windows console. The Faces "add" step says to use
  a model with a singing face; the layers step says above or below doesn't matter; the VU Meter
  wording no longer says "setting it back". The timing step takes the new track with the most
  marks. Pictures: choosing the file also switches Scaling to Scale To Fit - that is now taken as
  a related setting of the file step (and written with it); the Scaling step learns No Scaling
  instead (kit v17). "No change" names the effect compared (model and time). The end of the kit
  and `xlights-kit` name the steps still to learn; `status` has an xLights kit line.
- Shell: Tab completes `--audio=FILE` and patterns (`bat*`); without pyreadline3 on Windows the
  prompt says how to get Tab completion. argparse's own colours (Python 3.14) are off, so help
  shows no raw codes.
- GUI and demo pages have the lightbench favicon. Release notes moved from DESIGN.md to this
  file; the README starts with the single-file download.

0.24.57 (the user's review):
- 'adjust' (matchup/adjust_cmd.py): settings over whatever plays on a target - its own effects,
  reactions, singing faces, choreography parts - without choosing the effect (songs.json
  'adjust'; applied in engine.run after the choreographies). Only the settings any effect takes
  (parts.EXTRA_SPECS: rotation, area, render); glides get 'over' (the adjustment's span) so each
  cut part keeps its share. --on picks one layer (face or a face's name, react, choreo, a pass).
  Span: a section and its repeats; with from= / until= (pins' onset / offset forms) that section
  only. Made for the face upside down in an intro, turning upright: xLights' Faces effect has no
  rotation, but every effect's Layer Settings do (Roto-Zoom Z; 50 = half a turn, as the user
  confirmed). The score lists adjustments; score apply clears them.
- angle_value: 360deg is a whole turn (1.0), not 0; past a turn it wraps.
- update: UPDATE_FROM = "master" - that branch's VERSION (and its .zip) first, GitHub releases
  next (the user publishes master as the latest for now).
- Windows consoles: colour codes need the console's virtual-terminal mode, which conhost (a
  double-clicked .pyz) doesn't have switched on - color._windows_vt switches it on per stream
  (SetConsoleMode, ENABLE_VIRTUAL_TERMINAL_PROCESSING); where it can't, colours and line
  rewriting are off, with one note on how to start seqtool in Windows Terminal.
- DESIGN gains §0 (overview) and §2a (source map), moved from HANDOFF.md, which isn't shipped.

0.24.56 (the user's request): checking for updates (common/update.py, 'update').
- REPO / REPO_URL constants (https://github.com/djulien/seqtool). latest(): the newest GitHub
  release (tag_name; a .pyz asset, a .zip asset or the zipball), else the VERSION file of the main
  (or master) branch with the branch's .zip; None when nothing can be reached (4 s timeout).
- general.check_updates (default true; SEQTOOL_CHECK_UPDATES=0 overrides for a shell - the tests
  set it): at the seqtool> prompt's start a newer version is offered (download? then how to use
  it, and an offer to restart with it); the GUI and 'start' say so in one line. At most once a day
  (answers update_check), never in the way of starting (any failure is silent).
- Getting it: a .pyz release into a .pyz-installed folder (it has .seqtool-manifest.json) runs
  the new .pyz with --unpack-to ROOT --unpack-only - the bootstrap's own upgrade, keeping and asking
  about changed files; otherwise the .zip is unpacked into its own folder beside the current one,
  seqtool-X.Y.Z (a GitHub archive's single top folder is looked through for seqtool.py).
  Preferences, songs and results live outside the seqtool folder, so they carry over. Restart:
  os.execv with the new seqtool.py and the same arguments, after asking.

0.24.55 (the first new-user test):
- Lyrics: a line written '0:12.50 the words' (no brackets; trackED and others write it) is read
  as a timed line; a file mostly of such lines is read as LRC. A file with text but no times it
  can read, with no one to ask and faster-whisper not installed, stops with both ways out
  (install it, or give the times in either form) instead of going on to Whisper.
- A missing package (MissingDependency) is one line with its fix, not a Python traceback.
- Shipped text (help, examples, preferences, the skill, this file) uses generic names - no props,
  songs or files of the developer's own show (they belong in DESIGN-addendum.md); a test keeps
  it so.
- The seqtool-direction skill: the role (the user's guide, not seqtool's developer - a bug is
  said in a line and offered to the developer, not fixed in the session), 'know only what you
  were told', a step-by-step first-time flow (where seqtool runs; Python, unzip or the .pyz,
  start seqtool then type; what it needs - lyrics optional, the song stays with the chat; the
  kit on their computer), commands named as 'seqtool's X command' the first time; a broader
  description so it is used without being called by name.

0.24.53 (plan step 7: the special cases onto the shared structure, where it simplifies):
- matchup/parts.py holds what every way of placing an effect shares: segment() (pins'
  choreography parts, reactions and whole-yard moments build their segments with it),
  setting_specs() / read_settings() (an effect's settings plus render / area / rotation, read as
  you give them, glides too - pins and choreography steps), duration() ('2b', '3beats', '25%' -
  a pin's onset / offset and a step's at / length / every), effect_name() (seqtool's or xLights'
  name) and glide_runs() (keyframe steps -> one effect per run of glides with a curve per
  setting - choreography keyframes and now reaction presets: spoke-bounce is one effect per bar
  with a value curve once the kit has them; presets whose settings use 'step' keep a part per
  keyframe step).
- Reactions are a kind of choreography step: {"react": PRESET} plays the preset's events inside
  the step's time on its target (colours from the step), so a definition can hold reactions and
  a choreography can mix them with effects.
- Left as they are, on purpose: promote / demote (whole-section layer placement and the rests
  it causes are a planning rule, not timed parts); singing faces (the sing reaction carries the
  face, voice and phoneme timing that only _sing sets up); the base pass's moments (chosen
  from the whole song's music before any plan exists; their sweep and unison are a few lines
  each, and the call-and-response moment splits the yard by halves, which steps don't need);
  cues (already one trigger among the others, used by reactions and choreography alike).

0.24.51 (the user's first real value-curve save, xLights 2025.13.1):
- What it showed: 'E_VALUECURVE_Fan_Start_Angle=Active=TRUE|Id=ID_VALUECURVE_Fan_Start_Angle|
  Type=Ramp|Min=0.00|Max=360.00|P2=360.00|RV=TRUE|' - a field at its default is left out (the
  start, P1=0), the slider's own setting (E_SLIDER_Fan_Start_Angle) is dropped while the curve is
  on, and the effect may carry other curves already (Fan's End_Radius).
- The kit: a curve counts when it is new or changed since the step began (the snapshot) and since
  this step's earlier saves (vc_seen); 2 numbers are enough; the slider is the setting that went
  (slider_dropped). Several new ones: 'multi' - a takes one, n the next (Session.next_choice). The
  ramp down: a field that comes or goes counts as changed.
- Curves: the field order merges the three saves (a left-out field is written where it belongs,
  the start before the end); the start is the swapped field highest in the ramp down; the high
  limit is the field equal to the highest value (real values); written curves always carry start
  and end; when xLights drops the slider, the export does too.

0.24.50 (plan step 6: a per-song score):
- 'score' (matchup/score_cmd.py): the song's settings as the commands that make them - a batch
  file with '# ==' headings: sections set (every boundary, =TYPE), palette, feel, define set
  (song and section level; JSON shell-quoted), cue add (grouped by tag / for / len), pin
  (pass as the timeline suffix, settings as NAME=VALUE with glides a..b, --only, a hidden --how
  for promote/demote), react, reroll --seed (master and per target/section), score note (the
  directions given, with the commands they became). Show-level things (show definitions,
  preference reactions / faces) are listed as notes, not replayed; lyrics and borrowed effects
  are not touched.
- 'score write' (and every xlights-export, beside the .xsq) writes <song>.score.txt; 'score
  apply FILE' clears the song's pins, reactions, cues, palette, feel, definitions, section fixes,
  seed overrides and directions, then runs the file as a batch - one undo step; on a failing
  line everything is put back. On the user's bundle copy, write + apply gave the same settings
  (no visible change in the plan).
- New command forms for it: 'sections set @T1 @T2=TYPE ...'; 'pin ... --how'.
- The seqtool-direction skill reads 'score' before translating and records each direction
  ('score note ... --commands ...') in the same batch.

0.24.49 (plan step 5: timing inside sections, call and response, spread by pitch, angle submodels):
- Call and response (matchup/calls.py, 'calls'): cues tagged 'call' / 'response' ('cue tag
  call @#3', 'cue add --tag') are split into phrases at pauses over music.calls.gap_beats (2);
  with only 'call' tags they take turns. Pairs give the offset (response after call) and the
  cycle (call to call), medians snapped to whole beats (one pair: cycle = 2 x offset). The
  section is continued after the last marked pair - a call every cycle, its notes the onsets
  heard (music.calls.onset), the response the call's timing one offset later (or
  music.calls.response = onsets) - and so are its repeats that have no marks, from the same
  beat into them. Events call / response (notes; each lasts to the next, a beat at most),
  call_phrase / response_phrase, pair, each with its pair number and 'derived'. _Music.times()
  gives them as triggers. Tagged cues are no reaction hits (engine filters them).
- Choreography steps: "only" (which times: indexes, negatives from the end, first / last /
  odd / even); "tag" (with per cue); "spread": "pitch" (pitch_bins: the time's pitch - the
  melody note with stems, else brightness_hz - ranked onto the props ordered left to right);
  "order" left_to_right / right_to_left (yard x); "/NAME" targets (that submodel of each prop);
  colors on a motif / steps pass one colour per time to the parts inside; xLights effect names
  ('On') are taken as their seqtool effect.
- 'submodel angles TARGET [--count 12] [--width DEG] [--write] [--remove]': clock-position
  submodels (seqtool-12oclock ...) on round props from their node positions (layout points,
  custom models): nodes within width/2 of the direction (12 = up, clockwise) plus the hub,
  ordered from the centre out, rising runs joined into ranges. The XML form is learned from a
  'ranges' submodel already in the file (its attributes; name and one line changed).
  write_faces.put_children edits the file as text (replacing seqtool- children; removal gives
  the file back byte for byte), backup first, layout read again.
- The top pass and the base pass don't treat a pinned choreo as the top group taking over.

0.24.48 (plan step 4: keyframes, value curves, rotation):
- The kit learns value curves (kit_version 16): three steps on one slider's curve - a ramp
  lowest -> highest, the same swapped, then Type Custom with one point dragged to the top - and
  Layer Settings > Rotation at its highest. encoding.Curves takes from them, assuming only
  'name=value' fields joined by one separator: the curve's key (the slider's with its second word
  changed), names of it in the text, the start / end (the two numbers that swapped), the limits
  (numbers that stayed, equal to the lowest / highest -> real values; else shares), the points
  field (x:y pairs; separators, x scale, y real or a share) and the type words.
- Glides are {"ramp": [a, b]} or {"curve": [[t, y], ...]} (t 0..1 of the effect). Encoding.effect
  writes a value curve for a scale setting (not rate or checkbox-like) and for rotation; the
  exporter's glides() keeps such an effect whole, splits a curve at its points into ramps when
  only ramps were learned, and steps the rest as before (GLIDE_STEP).
- Pins: 'NAME=a..b' / 'a..b..c' (parameters.glide_value) and rotation= (angle_value: 90deg,
  3oclock with 12 = 0 clockwise - xlights.rotation_clockwise - or a share of a turn). A pinned
  glide carries "over": [t0, t1], its run of segments (engine._glides_over), and each part
  exported gets its share of it (encoding.curve_points(v, start, end)).
- Choreography steps: settings take glides and rotation; "keyframes" (CSS, keyframes.py;
  "easing" linear by default here) become one segment per run of glides with a curve per
  setting; a jump (hold, a choice) starts the next.

0.24.47 (the user's review; plan step 3):
- The 'choreo' effect (matchup/choreo.py): pinned like any effect ('pin TARGET @#3 choreo
  name=NAME'), never chosen by the scores, not lit (the target shows nothing of its own there; the
  export writes nothing for it). After the reactions, engine.run expands each pinned choreo
  segment into the parts it plays: the definition NAME's machine form, read at the segment's
  middle. Where: the entries that apply are keyed by their 'for' - none: the target; a kind: each
  prop of that kind inside the target; a group or prop: that one, when it is the target or inside
  it. When any are keyed, the entries for nothing are defaults merged under each key (level
  order, then all < kind < group < prop); else they play on the target. Data: one step or
  {"steps": [...]}; a step is an effect (+ settings, parsed as pin settings and marked as yours),
  a motif (another definition, recursive to depth 6) or inline steps; target (prop, group,
  submodel), spread each|cycle, at/length (s, b, beats, %), per (word, last_word, first_word,
  lyric, beat, downbeat, onset, cue, section, analysis events; words filter), every / count,
  color / colors (one per time), generator 'file.py:fn' (the user's Python, in the show folder
  or seqtool-prefs: fn(window, target, music, step) -> steps with start/end). Parts become plans
  of pass 'choreo', one per overlapping lane, on layers above the target's other plans; the
  exporter writes their rows over their groups (rank 2). Reasons and why name the choreography
  and step; problems go to the pin notes; 'explain PROP @TIME' on a part shows its choreography,
  settings and colours (no scores). A choreo pinned on a top group doesn't make it take over:
  its members keep their own effects there (top_pass / apply_rests leave choreo spans out).
- batch: a long command list is never tried as a file name (OSError: File name too long).
- Files outside the show folder (common/showfiles.py): a setting that names a file
  (effects.json "file": true - a picture's file) outside the xLights show folder is offered to be
  copied into general.show_files.folder ('seqtool-files') beside the audio file, or in the show
  folder when the audio isn't inside it (Enter / no one to ask = yes; same content reused, a
  different one renamed bat-2.gif), at 'pin' and again at export (picture_path; the pins naming
  it are changed to the copy).
- start: general.session_start gains 'xlights-kit --update'. A command's module can say
  at_start(argv) -> ('skip', why) | ('ask', what): the kit skips with no layout or a complete
  training, and otherwise runs uncaptured where someone can answer (the prompt, the GUI console),
  else is reported as a problem line.
- 'face use': --over is the default (backgrounds show behind a face; --no-over: they rest).
- Kit: the group_render step asks for an effect on any group; the delete question says 'and its
  fseq'.

0.24.46 (the user's design session):
- Plan, agreed with the user: (1) own palette colours and a picture effect; (2) definitions at
  levels; (3) a 'choreo' effect - pinned, layered, timed and shown like any effect, expanded when
  the plan is made into real child effects (on members, submodels, other props) on a layer of its
  own: declarative steps (effect, motif, per word/onset/beat/cue, repeat every N s, spread) with an
  optional Python generator for what data can't say; (4) keyframes and value curves on settings
  (the kit learns xLights' value-curve format once) and rotation; (5) timing inside sections
  (lyric lines, cue ranges, call/response derived from cues), spread=cycle|pitch, angle
  submodels; (6) a per-song score (the song's definitions and directions in one place);
  (7) a refactor moving existing special cases (reaction presets and keyframes, faces, pin
  settings and onset/offset, promote/demote, cues, base moments) onto that structure where it
  simplifies.
- Own colours per song: 'palette colors C1,C2,... [--accent C,...]' (names or #RRGGBB) - used as
  given (no rotation); the accent colours (default palettes.high_energy_accent) are added for loud
  parts; --hue and feel warmth still apply.
- 'picture' effect (xLights Pictures): never chosen by the scores (auto false), pinned with its
  settings - file= (text: a file in the show folder, found by name below it, or a full path; the
  export writes the full path and says when it isn't there), scale=fit|none, loop=yes|no,
  transparent=yes|no (black shows what is underneath), speed, area=x,y,w,h. The kit learns it
  (Pictures step, kit_version 15). Until it has, pinned pictures are planned (seen in the GUI,
  explain) and the export skips them with a note - no stand-in. Pin settings take text and area
  values; parameters with a default and no range are their default unless given.
- Definitions (common/definitions.py, 'define'): named text containers with an optional machine
  form (data, JSON). Levels: show (seqtool-prefs/definitions.json), song, section (anchored to a
  time, repeats unless --only) - each optionally --for a kind of prop (spinner, matrix ...), a
  group (everything in it) or a prop. get / dump merge every entry that applies, most general
  first (show < song < section; within a level: all < kind < group < prop): the text listed with
  where it came from, the data merged per key (deeply), the more specific winning. JSON output for
  skills. The skill reads them before translating and stores the user's DEFINITIONS.

0.24.45 (the user's review):
- A word with codes at both ends ('{BACK1}whoo{LEAD}'): the one at the start is its voice, the
  one at the end the voice from the next word on - each code where it was typed. Before, only the
  last code counted, as the word's own voice.

0.24.44 (the user's review):
- 'lyrics word L.W TEXT': the word's voice codes are the ones in TEXT - a code it had before
  goes (typed without one, it has none); the other words keep theirs (the line's text is made
  again from the words with their codes, voices.line_text). Before, the old mark stayed too:
  'right.{LEAD}' over '{LEAD} right.' gave '{LEAD} right.{LEAD}'.

0.24.43 (the user's review):
- A {VOICE} code at the end of a word ('right.{LEAD}') stays there: the word keeps its voice and
  carries "voice_after" - the voice changes from the next word on (in the next line too); the
  line's text writes it back after the word. At the start of a word: from that word (as before);
  inside: the word is split there (0.24.42). A code in the line's text over a word whose own
  text has the code is left to the word (it marked the next word as well before).
- The magnifier shows where a voice changes: a flag in the voice's colour (a hue per voice, not
  the words' yellow) with its name at that edge of the word.
- Note: a split word gives the line one more word, so 'lyrics word L.W' numbers after it move on.

0.24.42 (the user's review):
- A {VOICE} code inside a word stays where it was typed ('flap{BOB}pin''): the word is split
  there into two timed words (the time shared by letters; voices.split_at), the second starts
  the voice and is 'joined' - no space before it when a line's text is made from its words
  (voices.join_text). Codes in a line's text are placed by their position in the text without
  codes, so one inside a word splits that word, and one between words marks the next word. The
  word's own text works the same ('d{ALL}o'). Normalising again changes nothing.
- The skill: 'Lists of directions' - one batch for a list (one re-plan, one undo step), per-group
  batches when asked, dry run first when asked, per-item report.

0.24.41 (the user's question):
- What the GUI shows at once, before the plan: tapped and dragged cues, dragged words and lines
  in the magnifier (lyrics commands don't make a plan at all), the palette wheel's choice. The
  palette panel's colours and the timeline follow once the plan is made (the panel reloads then).
- Fixed: dropping a green tap mark (with its word) in the magnifier moved the word on the page
  only - its 'lyrics time' command had ended up inside a comment.

0.24.40 (the user's request):
- Every change from the GUI - menus, panels, sliders, the console line - is recorded at once and
  planned later: the server runs GUI commands with '--later' (except those that make or need the
  plan themselves: run, demo, batch, undo, redo, replan, start, xlights-export, bundle, xlights-kit
  ...), its 'done' event says a plan is waiting, and the page restarts its timer (general.
  replan_after); then 'replan --if-pending' runs in a child process. The change says "the plan
  follows a few seconds after your last change". Commands that read the plan (xlights-export,
  bundle, explain, inspect, status) make a waiting plan first, at the terminal too; a plan made
  any way (rerun, run) clears the waiting flag.

0.24.39 (the user's review):
- GUI: the effect menu (ctrl+click) has '<effect> only from ... until ...': two boxes (2b, 3s,
  25%, 3beats or @TIME) and a pin button - it runs 'pin TARGET @MID EFFECT from=... until=...'.
  A from= / until= @TIME outside the section named is refused (with where it is).
- Responsive cue taps: '--later' (a seqtool option, before or after the command) records a
  change without making the plan (as inside a batch; answers.json replan_pending); 'replan
  [--if-pending]' makes it. The page draws a tapped or dragged cue at once, sends it with
  --later (taps 0.3 s apart go together), and restarts a timer on each change: general.
  replan_after (3 s) after the last one it queues 'replan --if-pending'. The GUI runs replan in a
  child process at a lower priority (server._in_child; SEQTOOL_TAGS=1 keeps its colour codes and
  one-line progress), so the page and the sound it plays aren't held up while the plan is made.

0.24.38 (the user's review):
- A pin's from= / until= (onset= / offset=) given as @TIME says the section: '@#N' can be left
  out ('pin Matrix meteors until=@vocals'). A sung word that is sung more than once is asked about
  (its times and sections listed; with no one to ask, the list and '@WORD#N'), or with @#N the one
  sung in that section is taken; the pin keeps '@WORD#N'. until= at a section's start means the
  section before. A pin with an @time is for that section only (the time is in one place).
- '@vocals' without lyrics measures the singing's rise in the song (about a second to decode
  it): kept with the stems, <song>-seqtool/stems/<song>.vocal-edges.json, made again when the
  file it came from changes. With lyrics it is the first sung word (nothing to measure).

0.24.37 (the user's review):
- Part of a section, without splitting it: a pin's onset= / offset= (from= / until=) - 2s,
  1.5b (bars), 3beats, 25% of the section, or @TIME (any time form, worked out again each plan).
  In each section the pin covers, its segments are cut at section start + onset and section end
  - offset (engine.trim_pinned - the cutting the exporter does for glides); the parts outside
  are transparent: nothing from the pin, what is underneath shows (the group, lower layers;
  in a top-pass section the top group's effect). The reasons say it ("plays 0.00-4.73 s into
  its section (offset=@ah)"). direct's "dark until the vocals" uses until=@vocals.
- start: quiet by default - each command's output is captured (log.captured: per thread in
  the GUI) and only problems are shown (doctor's 'fix' lines, error lines, a failed command),
  then one line; --no-quiet shows everything. With --gui the start commands run in the GUI's
  console (the first page asks for them, Server.start_pending), not on the terminal.
- explain on a reaction says why it is many short effects: the setting that changes from one to
  the next ('rotation_speed follows the energy'), keyframe steps, and glides written as 0.1 s
  steps. 'rests' is said once, and not while a pinned layer plays.

0.24.36 (the user's review and direction):
- Pin settings: 'pin TARGET [@...] EFFECT NAME=VALUE ...' - any of the effect's parameters
  (effects.json), a choice by name or a level (0-1, 0-100%, low / medium-slow / medium /
  medium-fast / fast / dense / max ...; parameters.user_value). Stored with the pin, applied to
  the pinned segments (seg.parameters, seg.yours); the exporter puts your values on xLights'
  whole scale, not the span seqtool keeps its own choices in.
- Render styles: an effect on a group xLights draws as one picture ('as_one' layouts) can be
  drawn as one ('default': the group's own layout) or on each prop ('per_model': xLights' Per
  Model Default render style). Each variant has its own affinity: model_fit for the group's
  whole shape or the mean over its props' shapes (models.analyze render_classes), times the
  effect's 'render' weights (effects.json; 1.0 when not given). scoring.render_fit takes the
  better unless the group's 'render' preference (models.targets.G.render = default | per_model
  | auto) or a pin's render= says. The style goes in seg.parameters.render; the exporter writes
  the learned key/value for per_model (kit structure step 'group_render', kit_version 14 -
  'xlights-kit --update' learns it; until then said, and drawn as one). Only these two of
  xLights' styles for now. The prop analysis has a version (ANALYSIS_VERSION 2): older stored
  analyses are made again.
- The demo as a show: demo/xlights_files.py writes the demo yard as xlights_rgbeffects.xml
  (the same shapes and light counts come back) and xlights_networks.xml (one generic Ethernet
  controller, DDP). 'demo --bundle' makes the demo show in a scratch folder with its own
  settings (your kit training copied), runs it and packs it like 'bundle'.
- Arguments: words after an option ('pin X @2 --only twinkle') are taken - argparse's
  intermixed parse when the plain one leaves non-option words over (common/args).
- batch: a failed batch that already split sections makes the plan again after taking the
  settings back (the sections were left split before).
- bundle stays with the current song and layout.

0.24.35 (the user's first bundle):
- A stored layout ingested before 0.24.32 never read xlights_networks.xml (no absolute channels):
  it is stale now when the file is there ("xlights_networks.xml not read yet") and re-ingested.
- The skill: several bundles - "using NAME" picks one (closest name; asked when two fit); when
  seqtool can't do something, one or two lines of what it would need (command / option and the
  xLights setting), offered as a change, plus the xLights way meanwhile.

0.24.34 (the user's review):
- Near matches (common/fuzzy.py): a weighted Damerau-Levenshtein distance - a missing or extra
  character 1, two swapped 0.8, a neighbouring key 0.5, a look-alike digit (6/8/9/0, 1/7, 3/8,
  5/8, 2/5, 4/9) 0.4; similarity = 1 - distance / the longer length. Only against values known
  ahead (layout names, the song's sections and sung words, seqtool's own words). general.fuzzy:
  'accept' (0.8) and above - used, and said; 'ask' (0.6) to 'accept' - the user is asked (no
  one to ask: not used, the most likely shown); two equally near - asked.
- direct: mistyped words are put right first (direct.corrections; words in quotes against the
  sung words; 'plain_words' are never typos); a section number the song doesn't have is not used
  (the most likely shown). "enlarge / reduce X by N bars|beats|s" (or "N bars longer") is timing:
  'sections move' of the next section's start (the last section: its own start), every repeat
  of X unless one is named; without "by" enlarge / reduce stay bigger / calmer. '{slot}' as a
  phrase in 'say' / 'not' (slot present). "flash at TIME" = a cue.
- '@WORD' as a time (explain.parse_time, every command): where WORD is sung (near spellings as
  above; '@star#2' its second time, '@star-0.5' before it).
- Arguments: seqtool's own --stale / --install / --quiet also after the command name when the
  command has no option of that name (__main__.late_globals; '--stale rebuild' too). On seqtool
  lines (the prompt, the GUI console, batch, start) a quoted word starting with '-' is text, not
  an option (common/args.split_line marks it Literal; argparse takes Literal words as
  positional). From the operating system's shell quotes can't be seen - there '--' before it.
- 'bundle' (common/bundle_cmd.py): the prefs folder (not cache/), the layout's two xLights files,
  the song, its results folder (not stems/, *.play.wav or files over 50 MB unless --all) and the
  .xsq files beside it, with bundle.json (old folder -> place in the zip). 'bundle --open FILE'
  unpacks into a new folder and rewrites every path in its JSON files (Windows paths: any case,
  either slash), then says how to work there (SEQTOOL_PREFS=.../prefs in .../song) - for running
  the seqtool-direction skill in a Claude session against the user's own show.
- 'start' and general.session_start (["doctor", "sections", "feel"]): run when the seqtool>
  prompt starts; the skill runs 'start' first.
- The skill: which show (own vs demo; bundle), start, dry run, typos, enlarge-by, @WORD, where
  --stale goes.

0.24.33 (the user's request):
- 'direct "TEXT"' - plain-language direction without a connection to Claude (matchup/direct.py,
  direct_cmd.py). No language model: preferences/intents.json lists intents, each with 'say'
  (phrases; a word matches its longer forms and close misspellings; phrases score by length, the
  longest wins), 'not' / 'unless' / 'need' (what rules it out), 'do' (command templates), 'means'
  and 'check' (read commands run afterwards). Slots come from the text and the current song and
  plan: section words -> @#N (every chorus = one per repeat group; "the second chorus" = that
  one, --only; a part the song doesn't have: not applied, said), prop and group names -> plan
  targets (all name words, else the first; the most specific; a group over its members when it
  matched the same words), quoted words -> --words, 'at 1:05' -> @1:05, effect names or words
  for them (effect_words), degree words -> {hi}/{lo}, the singing start -> {split_vocals} /
  {before_vocals}. A slot with several values repeats the command; '{slot|default}', '?' lines.
  Text is split at 'and' / 'then' / ';' / commas (not inside quotes); a piece that means nothing
  alone joins its neighbour; a clause without props takes the previous clause's. It shows what it
  understood (other readings by number), asks (--yes: no; no one to ask: not run), runs it as one
  batch (undo and the like on their own) and runs the checks. --dry-run, --json, --debug (scores),
  --list. --eval FILE ('TEXT => CMD; CMD' lines) compares with expected commands - the skill's
  translations, to see how well direct does (skills/seqtool-direction/direct-cases.txt).
- The layout's channel line: props without a controller come after the controllers' channels
  (an .fseq holds up to the last of them) - confirmed by the user, as is that inactive
  controllers keep their channels.

0.24.32 (the user's review):
- Absolute channels: xlights_networks.xml beside xlights_rgbeffects.xml is read with the layout
  (import_layout.read_networks). xLights numbers the channels of all controllers one after another
  in file order - inactive ones keep their place (auto-sized with no props: 1 channel); a
  controller's size is the sum of its outputs' MaxChannels. A prop's controller range becomes
  origin.absolute ("a-b"); the controllers are in adapter.xlights.controllers; 'layout' shows the
  count and the total (an .fseq of the show holds that many channels - fseqdump's header says);
  'models' has a channels column (absolute when it can be) and prints the fseqdump command for a
  prop. A changed xlights_networks.xml makes the stored layout stale.
- Design rule: a progress message rewrites one line - its text, clear-to-end-of-line and a carriage
  return (log.progress; log.progress_end clears it) - so it doesn't scroll useful output away. On a
  terminal and in the GUI console (streams with handles_cr; the console replaces the text after a
  '\r'); in a log or a pipe it is an ordinary line. common/progress, Demucs, transcription and the
  re-plan's "... planning, round N" use it.
- The seqtool-direction skill ships in the download: skills/seqtool-direction/SKILL.md, its
  version line bumped with seqtool's.
- fseqdump: without zstandard / the zstd tool, on a terminal it offers to install zstandard with
  pip (once). xLights' own zstd library is inside xLights and can't be used from Python.

0.24.31 (the user's review):
- The .fseq reader is a stand-alone tool, fseqdump.py beside seqtool.py (no seqtool imports, MIT;
  wildcards; JSON to <file>-fseqdump/); the 'seqtool fseq' command is gone. Without zstandard / zstd
  a zstd file says how to get them - or to save the .fseq uncompressed / zlib in xLights.
- A re-plan says where it is while it runs ("... planning, round 1", log.PROGRESS - stderr, which
  the silenced re-plan keeps).
- The 'direction' tutorial: no batch step (batch is a general command); an optional step about
  setting up Claude, with links to Anthropic's help pages.
- Planned: absolute start channels from xlights_networks.xml (ingested with the layout) - waiting
  for a sample file.

0.24.30 (the user's request):
- Creative controls: 'feel NAME VALUE [@#N]' (matchup/feel.py) - busy (continuity change penalty /
  persistence bonus x 2^((0.5-b)*2), decision windows x 2^(0.5-b)), intensity (scores x 1 + 0.6(2i-1)(2e-1),
  e = the effect's music_fit.energy; per song and per section), warmth (palette colours pulled towards
  30 or 215 degrees, up to 60 %), unison (base-pass moments per minute x 2^((u-0.5)*2.4); 0 = none).
  0.5 = neutral. Stored per song (songs.json "feel"). The GUI: 2. Song > feel (sliders). A change's
  report counts a colour change too.
- 'fseq FILE [--start CH --count N] [--from T --to T | --frames N] [--every K] [--json [OUT]]': the
  rendered channel data (adapters/xlights/fseq.py, after FPP's FSEQFile.cpp: v1, v2, ESEQ; none / zstd
  / zlib in blocks; sparse ranges; variable headers). zstd needs 'zstandard' (or the zstd tool) -
  not testable here (no package access); zlib, plain and sparse are.
- 'batch' re-plans at the end whenever settings changed (also for commands that don't re-plan).
- Tutorial 'direction': feel, batch, and asking Claude with the seqtool-direction skill.

0.24.29: 'batch "CMD; CMD" | batch FILE [--dry-run]' - several commands as one change: each runs
(through dispatch, so nested undo records fold into the batch's one step), re-plans are deferred
(reroll._DEFER; _apply_and_show / reroll / palette say "planned at the end of the batch") and made
once at the end, with the combined diff. A failing command stops the batch and its earlier commands
are taken back (the settings files restored), no re-plan. Not in a batch: run, demo, gui, batch,
undo, redo, test, clear, package, xlights-kit. (The user's first re-plan after 0.24.28 re-read the
layout - 16 s - because the xLights preferences file changed with the new export_on_replan key;
once only.)

0.24.28 (the user's timings: 16.6 s - export 3.9, matchup 3.6 + 2.4 (two feedback rounds), summary
2.6, the rest reading and checking): a re-plan after a change ('run --replan', added by reroll.rerun)
no longer writes the timeline page (the GUI has its own; written if missing) or the explain example,
and doesn't export the .xsq unless 'pref xlights.export_on_replan = true' - it says the .xsq is out
of date ('xlights-export' / 4. Export). Expected: about 10 s on the user's show.

0.24.27 (the user's review: 'palette' takes ~20 s): a re-plan of 4 s or more says where the time
went (the slowest stages; log.STAGES keeps when each stage started). The timeline page's waveform
is decoded once per audio version (view.cached_peaks, the GUI's disk cache) instead of every run.
On the demo a re-plan takes under a second; the user's 20 s is not reproduced here - the timing
line is to find it.

0.24.26 (the user's review): the palette wheel - the music's choice a thick dashed outline just
outside the wedge, yours a thick solid one on it (both visible on one wedge); a click keeps the panel
open, moves the marker at once and redraws with the result when 'palette ...' has run (JOB_DONE
callbacks when the command queue is empty); the box the 'now' colours come from is outlined (its
first 3 - the high-energy ones - dashed red); a wedge's tooltip says why it has its number of rings
(one per palette of the style in palettes.json), the label shows (N).

0.24.25 (the user's review):
- Faces: an open mouth may go 'beyond' its marked pixels (mouth_shapes.*.beyond, 1 for AI, O, U,
  L), and with marked pixels the open shapes use the marked height (h >= 0.5: all of it).
- Palette: 'palette [STYLE [N]] [--hue DEG] | auto' per song (songs.json "palette"; build_palettes
  override: style, pick, hue turn). Only the colours change - effects still follow the music's
  style. The GUI: 2. Song > colour palette - a wheel: a wedge per style (its share of the song's
  style scores), a ring per palette, the hue across the wedge; the centre: auto.
- {#RRGGBB} inline colour codes (terminal 24-bit, GUI spans) - swatches.
- Meteors: radial / ring props fit better (0.75 / 0.65) and explode on them - a choice parameter
  can be narrowed per prop shape (parameters.*.by_class).
- '@vocals' (and @vocals+-S) as a time anywhere a time is taken: where the singing starts (the first
  lyric word, else the vocal stem's first rise) - e.g. 'sections split 1 @vocals'.
- Reactions, the general form: PRESET@EVENT[w1|w2] - a preset's look on any event, optionally only on
  certain sung words ('react PROP LOOK --on EVENT --words W1,W2'). The GUI: "build one" (look, event,
  words, on top) in the react menus and the layout panel.

0.24.24 (the user's review):
- Reacting on certain sung words without writing a preset: 'NAME[w1|w2]' is preset NAME only where
  one of the words is sung (the line, for a preset on lyric lines; whole words, any case) -
  reactive.get_preset resolves it everywhere a preset is looked up. 'react PROP word-flash --words
  star,night [--over]' writes it. The GUI: "on certain sung words" in the react menus (here / song /
  every song, with the song's words to pick from) and in the layout panel's reaction choice; the
  GUI adds --over (a flash on top of the normal effects).
- Noted for later (the user): xLights' Breakdown Words puts more 'etc' mouths among the others and
  the mouths look a little livelier - revisit the phoneme generation.

0.24.23 (the user's review: the phoneme layer didn't line up with the words in xLights):
- A word's sounds keep the times they were given when the words were aligned; a word moved or
  stretched since (magnifier, 'lyrics time', shift, split) kept its sounds where it had been. The
  phoneme layer now fits each word's sounds to the word as it is (for_words).

0.24.22 (the user's review):
- Exported timing tracks are written active="0", so xLights doesn't open the sequence with all of
  them selected.
- While the song plays, the C key taps a cue at the playhead (paused, C types as usual): shown at once, sent as one 'cue add @A @B
  ...' 1.5 s after the last tap (one re-plan).

0.24.21 (the user's review):
- A word's touching neighbour follows its edge only within the phrase: across a phrase boundary a
  gap opens; Ctrl+drag (lyrics time L.W A B --alone) opens one within a phrase too. A neighbour
  run into is still cut back (both sides now).
- Words split and join: 'lyrics split L.W @T [TEXT TEXT]' (the text at a space or hyphen, else
  shared by the time), 'lyrics join L.W [--tight]'; in the magnifier's right-click menu on a word.
- Cues in the magnifier: a flag and a dashed line; drag the flag to move it ('cue move @A @B'), click
  it for its menu; right-click anywhere: add a cue here.

0.24.20 (the user's kit, observations.json): the Faces effect's face and phoneme track weren't set.
The kit's phoneme-track step recorded the face changing again as its one changed setting (the
track itself appeared as a companion), so the track's name was written into the face setting -
over the face. Now a setting an EARLIER step of the effect stands for is not a later text step's
(claimed_keys); the track is the remaining text setting (E_CHOICE_Faces_TimingTrack); a companion
xLights drops with it (E_CHOICE_Faces_Phoneme) is dropped too.

0.24.19 (the user's review: the stem waveform and melody marks drift later than the sound, ~0.7 s
by the end of a 3-minute song):
- The page plays a WAV copy of a compressed song (<results>/<song>.play.wav, made once with
  ffmpeg, again when the song changes): browsers place a seek in an MP3 by estimate (worst in a
  VBR file), so after a jump late in the song the sound is off what is shown, growing with the
  position; in a WAV every position is exact. The song itself when ffmpeg is missing.
- Waveform buckets carry their real length in decoded samples (peaks_timed: step), and the GUI
  places them by it, not by the file's stated duration (an MP3's can be an estimate).

0.24.18 (the user's review):
- Cues: your own trigger marks per song (songs.json "cues": [{t, len?, for?}]) - 'cue add @T
  [--for PROP,...] [--len S]', 'cue remove @T | --all', 'cue from-xsq TRACK [--xsq FILE]' (a
  timing track tapped in xLights). A reacting prop shows its first preset's effect at each cue,
  forced: what plays at the cue stops there, the next real event still comes when it comes; only
  where it reacts. A new trigger "on": "cue" and the preset cue-flash react to cues alone ('react
  PROP cue-flash --over'). The GUI: a cues row under the stems (click: add here / for one prop;
  a cue: remove). The plan's settings keep the cues.
- The steps bar has four steps: Faces is a submenu of Layout, Lyrics of Song (#fxsubmenu).
- No moments row when there are no moments (folded or per prop, nothing lit).
- Export: a learned text setting (Faces' face definition, phoneme track) whose kit step changed
  several settings is still found (the one holding text; or the one named like the step); if it
  can't be, the export says so instead of leaving xLights' default silently. 'xlights-kit --redo
  EFFECT.STEP' learns chosen steps again.

0.24.17 (the user's review):
- Export step menu: the sequence itself (xlights-export) as well as the verification sequence.
- A thin lyrics row under the bar / beat ticks when the song has lyrics: lines blue, words
  yellow (the word playing brighter), as in the magnifier; hover: the line and word, click: play
  from there. It is part of the strip that stays at the top.
- The browser's player is gone: a play / pause button left of the time, seek 0 / -5 s / +5 s right
  of it (left column, under "waveform ... BPM"); volume and speed drop-downs, the stems box and the
  magnifier button at the left end of the legend row. Space, the console's play / seek / volume /
  speed commands and the remembered speed / volume work as before.
- The split between the song view and the console is remembered (localStorage, per browser).
- A setting for every song made now - 'react PROP PRESET', 'face use PROP FACE' - wins in the
  current song too: that song's own reaction settings for the prop (e.g. an earlier "no singing
  anywhere in this song") and its pins on a row under a group are taken away, said, undoable; and
  the plan is made again at once (a 'react' for every song didn't re-plan). Why a face doesn't
  sing (no lyrics, no word times ...) is said after the change.

0.24.16 (the user's review):
- Layout panel: the reaction choice has a "sing with a face" group - one entry per face of the
  prop ('face use PROP FACE'), or "sing (no face yet)" greyed - above "react to the music" (the
  presets). A prop that sings shows it as its choice (it showed "no reaction" before).
- 'face use PROP FACE|off' re-runs the plan when there is one, as react and pin do.

0.24.15 (the user's review):
- Layout panel: a submodel in a group is shown as a part ("Mouth - part of Mask", italic), not
  as the whole prop; a prop a group holds only in part isn't counted as grouped there. The
  import keeps structure.models (the props a group lists whole beside its parts); for a layout
  stored before, the panel reads them from the source file.
- Fixed: pins on a detail row ('9. Masks (detail)') were never used - the detail pass didn't read
  its pins (pin_pass="detail"). An unused pin no longer says "no visible change: it was already
  the choice there"; the 'unpin' it suggests names the row as the timeline does, quoted.

0.24.14 (the user's review):
- The 'react' tutorial starts with "Effects or reactions?" (a new step kind, read: true - it only
  explains; Enter goes on) and ends with turning the reaction off ('...' in the GUI, 'react PROP off').
- The legend row (effect colours, stems box, vocals button) stays at the top with the waveform.
- 'models PROP --disable / --enable' re-runs the plan when there is one (as pin and react do), so
  the prop's effects go at once. A disabled prop that a sequenced group holds is still lit by the
  group in xLights - said, with how to keep it dark ('--enable' then 'pin PROP dark').
- The row's pin opens a menu: keep every section's effect (pin --all), dark or transparent for the
  whole song, or one effect for the whole song ('pin PROP EFFECT'); unpin when pinned.

0.24.13 (the user's review):
- A singing face is not a pin: it is a reaction (preset 'sing', on "sung"), planned in its own
  'face' row. Like your pins and placed effects it wins over seqtool's own effects and over other
  reactions; between a pin and a reaction, the later command wins ('react ... @T' takes the pins
  there away). 'pin PROP face' says to use 'react PROP sing @T' (here) or 'face use' (every song).
- A reaction is many short effects (a flash a beat), too small for a '...' each: its row is drawn
  as runs, one per section it reacts in (hover: outlined, '...' at its end). The prop's own row
  shows where it rests for the reaction as a dashed "reacting" / "singing" cell with the same
  '...'. The reaction row's name has a '...' for the whole song (Ctrl+click on it too).
- Lanes carry the plan's react and react_parts. Fixed: the row under the mouse was compared by
  object, but rows are fresh copies each draw, so a row's hover icons (star, pin, die) never showed.

0.24.12 (the user's review):
- The strip that stays at the top holds the waveform and its bar / beat ticks too (with the
  magnifier button and zoom over it).
- A reaction's or a singing face's effect has a '...' menu (and Ctrl+click): no reaction here /
  in this song / in the preferences (`face use PROP off` for a face), another reaction, or an
  effect of your own here instead (`react PROP off @T` then `pin PROP @T EFFECT`).

0.24.11 (the user's review):
- The magnifier repaints when results reload (it waited for the next mouse event), and an edited
  text shows at once.
- No overlaps: a dragged phrase stops at its neighbours (Alt+drag, which shifts everything after,
  is not limited); a dragged word may run into a neighbour, which is cut back (never below 0.05
  s); `lyrics time L.W` cuts the next word's start too when the word now runs into it.
- The section headings stay at the top while the rows scroll: a strip (#cvsec, sticky) copied from
  the canvas's top; its mouse events go to the canvas as if at its top.
- `rerun` (after pin, react, reroll, promote ...) rebuilds stale files without asking (the question
  hid under the magnifier; the change seemed to do nothing); --stale=warn is kept.
- `react PROP PRESET @...` (the cell menu's 'here') takes away the prop's own pins in that section
  (they won over reactions, so the reaction didn't show), and says so; 'undo' brings them back.
  A reaction that changes nothing says why for singing (only where its voice's words are sung).

0.24.10 (the user's review): phrases can be edited like words - double-click, or right-click >
edit text (words: edit "WORD"); `lyrics line L TEXT`: as many words as before keep their times
and voice marks, another number share out the phrase's sung time by word length.

0.24.9 (the user's review): in the magnifier a box's edge zones reach a quarter of the box inside
(6-14 px; 6 px outside) - the trailing edge was only 6 px wide, so a grab just inside it moved the
whole phrase; the pointer shows what a drag does: a double arrow (the whole phrase or word), a
right arrow (its trailing edge), a left arrow (its leading edge) - drawn SVG cursors, since the
system's e-/w-resize look alike on most systems; col-resize on a section line, grab elsewhere.

0.24.8 (the user's review):
- Tapped marks are off for now (`TAPS=false` in app.html keeps the code): edge snapping replaces them.
- **Snapping to the singing** (a 2-state 'snap' button in the magnifier, on by default, remembered):
  dragging a phrase's or word's leading edge snaps to the nearest place the singing starts, its
  trailing edge to the nearest place it stops (within 60 px); Shift+drag moves it and snaps both.
  The edges come from the vocal stem (the mix without one) - music/edges.py: the level every 10 ms,
  'on' 10 dB over the quiet level (at most 24 under the loud level), 'off' 6 dB lower; a rising
  edge where the rise begins, a falling edge where the fall ends (`/api/edges`, once per song).
  A phrase's words stretch with it (as before); the old Shift+drag (it and everything after) is
  Alt+drag now.
- A word whose neighbour touched it before a move still touches it after (`lyrics time L.W`).
- `lyrics split L @TIME` / `lyrics join L` (the magnifier: right-click a phrase): words keep their
  times; each phrase spans its words; a word cut by the split goes where most of it is.

0.24.7 (the user's review):
- Magnifier settings are remembered: speed (a new audio source reset it to defaultPlaybackRate -
  now set too, and put back on every load), volume, the view's length, follow, voice / mix, half.
- A ribbon under the magnifier's waveform shows where the singing is (vocals / mixed /
  instrumental, the main waveform's colours); the bars stay grey so the stem marks keep their
  contrast.
- `lyrics shift DELTA from L.W`: that word and every word after it move by DELTA, each keeping its
  length; moving earlier cuts the word before if they now overlap; phrases follow their words
  (a phrase that moved whole keeps its own start, the one the word is in ends with its last
  word, neighbours' boundaries move as in 0.24.6). The magnifier: Shift+drag a word (Shift+drag
  a line still moves whole lines), or right-click a word for -0.25 ... +0.25 s.

0.24.6 (the user's review):
- Magnifier: its button is larger and sits before the time; the waveform is the vocal stem's by
  default (`/api/peaks?src=vocals`; the whole mix when there is no stem - the button says so), a
  button flips to the mix; another draws it one-sided (top half, twice as tall); marks grab within
  10 px (the nearest wins); a green mark dragged with its word keeps the word touching the next
  one if it did.
- A moved first / last word takes its phrase boundary with it (`lyrics time L.W`), and a phrase
  that grows into its neighbour moves that one's boundary - never past the neighbour's own words.
- Silent files (an empty stem) no longer break the waveform peaks.

0.24.5 (the user's review): the magnifier's "play here" plays only once the seek to the view's
start has landed (a play begun before it could start from the old place), and 'follow' no longer
moves the view when the play head is a hair before its start (audio positions are quantised:
it jumped back by a tenth); the tooltip names the time. Dragging a green mark moves its word with
it (`lyrics time`, the word's length kept).

0.24.4 (the user's review):
- A GUI command whose page is gone is cancelled (Server._orphans, checked every 0.5 s): no page
  connected for 3 s (the event stream ticks every 2 s, so a closed page is noticed within a few
  seconds; a reload reconnects sooner) - a command waiting at a question returns as cancelled at
  once, a working one stops at its next line of output (Job.write raises Cancelled once), and the
  terminal is told. Before, the terminal stayed "waiting for the GUI command ... to finish".
- `lyrics tidy`: every word that runs into the next one ends where that one starts (lines end
  with their last word); the magnifier's right-click menu on the lyrics offers it with the count.

0.24.3 (the user's review):
- Magnifier: a dropped word or line shows where it was dropped at once (`magLocal`; the command's
  result replaces it on reload - before, it showed back at its old place until then, which looked
  like a bounce); the edits go through the command queue (`actQ`), so none is lost while another
  command runs. The word or line being sung is drawn brighter.
- Moving a word (`lyrics time L.W`, `lyrics starts`) cuts the word sung before it where the moved
  one starts, if it ran into it (`_tidy_before`; it keeps at least 0.05 s).
- The "typing goes to the console" key handler leaves list boxes alone: the magnifier's speed lost
  the focus after its first change, so later arrow keys went to the console history.
- Questions that want a folder or file (`ask(..., complete="dir"|"file")`: the kit's training
  folder, `cd`, `run`'s song) complete paths - Tab in the terminal, the list in the GUI console.
- Kit sub-buffer steps (kit v13) use the Sub-Buffer's right-click presets - Halves > Left Half,
  Thirds > Middle Third, Halves > Bottom Half - exact values, nothing to drag. The learner reads
  the right edge from the half (50), the left from the third (33 / 67), and the top edge from the
  bottom half (50; whether it counts up comes from its value in the left half: 100 = up). Renamed
  steps (subbuffer_left_half / _middle_third / _bottom_half), so a training with the 0.24.2
  dragging steps is asked for these again.

0.24.2 (the user's review): `xlights-kit` in the GUI's console only printed every step (the wizard
needed a terminal to read keys). It now runs there: each step asks, the user saves in xLights and
presses Enter, the file is checked (s / b / a / q as in the terminal). With a training already
there, a printed list (no terminal, no GUI) shows only the steps it lacks.

0.24.1 (the user's review): the magnifier's tapped marks can be dragged sideways (paused or
playing; a click on one while paused still removes it, while playing still adds one); M now
marks while the empty console line has the focus (it nearly always has - M did nothing before;
a capture-phase handler takes it before the line does).

0.24.0 (the user's review; MINOR: singing faces are planned differently):
- **Singing is a reaction**: the preset `sing` (`on: "sung"`: each passage the prop's voice sings,
  lyric lines from `sing.lead` before to `sing.tail` after, gaps under `sing.join` closed;
  effect `face` with params `"auto"` = the prop's own face / track / area). So it works per song
  and per section like every reaction: `react PROP sing @#3`, `react PROP off @#5`, the GUI's react
  menu. `face use PROP FACE` = which face (and voice, area) + `react PROP sing` for the whole song;
  `face use PROP FACE @#3` = only there. A face set before 0.24.0 (no `sing` list) still sings the
  whole song. The old face pass (passes.face_plans) is gone; engine `_sing` makes the rows:
  one per face, each on its own layer above the prop's rows; 'alone' (default) carves the prop's
  other rows by the sung segments only (not by the whole section), `--over` (`sing_over`) doesn't.
- **Several faces, voices**: `face use PROP FACE --voice V --area x,y,w,h [--add]` keeps a list
  (`targets.PROP.sing = [{face, voice, area}]`). Voices come from codes in the lyrics - `{BOB}`,
  `{ALICE}`, `{ALL}` - typed anywhere in the words or set with `lyrics voice NAME @L[.W]`
  (music/voices.py): normalised whenever lyrics are stored (songs.update): a code on a word, in
  the line's text before a word, or as a word of its own marks that word (`voice_mark`); every
  word then carries the `voice` in force (ALL before the first code); the line text keeps the
  codes, `for_music` strips them. A prop with a voice sings its words and ALL's. The export adds a
  timing track per voice, `seqtool-lyrics-VOICE` (phrases, words, phonemes), and the face follows
  its own.
- **Placement on a matrix**: `area` (percent, top-left origin) is written as the effect's
  sub-buffer. Its form is learned, not assumed: three kit steps on the On effect (kit v12) drag the
  Sub-Buffer's right edge to the middle, then the left edge in, then the top edge down; which of
  the value's four numbers is which edge, and whether 'top' counts up, come from what changed
  (encoding._learn_area). Not learned yet: the effect covers the whole prop and the export says
  'xlights-kit --update'. Any effect can carry an `area`.
- GUI: text boxes keep the focus (the console line took it on every mouse-up - the layout
  panel's filter could not be typed in); the magnifier's play button shows play / pause.

0.23.0 (the user's review; MINOR: the preference folder moves, face pictures change):
- **Preference folder in the home folder**: `~/seqtool-prefs` by default (SEQTOOL_PREFS - relative
  from the start folder - or `--preferences` for another), so none appears beside songs. A
  `./seqtool-prefs` in the start folder that isn't used gets a warning saying where settings
  are now; seqtool moves nothing (the user moves it).
- **Faces into / out of xlights_rgbeffects.xml**: `face write NAME [--prop P]` puts a built face
  on the prop it was built for (a face of that name there is replaced); `face remove NAME`
  forgets a built face (its folder stays), `--xlights` also takes it out of the file. The file
  is edited as text (adapters/xlights/write_faces.py): only that model's element changes, the
  result must parse, a copy goes to `<show folder>/seqtool-backups/` first, and the layout is
  read again. It asks whether xLights is closed (`--yes`: doesn't; non-interactive needs it).
  The faces step's menu offers both; `face list` shows built faces not in the file yet.
- **Face viewer alignment**: the marks canvas no longer reaches 16 px past the picture (that
  could bring in scroll bars, shrinking the picture under marks already drawn - a pixel off);
  a ResizeObserver on the picture and its box places every overlay again after any size
  change; the box outlines are `box-sizing: border-box` (their border was outside the cells).
- **Marked mouths stay in their pixels**: with a mouth marked pixel by pixel over 3 or more
  rows, every mouth shape is drawn only on the marked pixels and fitted to their height (a
  single row of lips still lets it open below, as before). Eyes were already only drawn on
  their marked pixels.
- **Building from a picture face build made**: every picture `face build` writes carries a PNG
  text chunk `seqtool-made` ({kind: boxes | base | blank | mouth | sheet, face, from}); older ones
  are recognised by their face folder's `*-build.json`. Building from one (the boxes picture
  drew its boxes in again - the user's case) warns and offers the original picture.

0.22.2 (the user's review):
- **Esc / click again**: Esc hides the panel shown last, one per press, whatever has the focus
  (the console line usually does; Esc there still clears an answer prompt or a typed line first):
  menus first, then a stack of panels ordered by when each became visible (a MutationObserver
  on their style / class) - explanation, magnifier, help, preferences, layout panel, picker,
  face viewer, vocal settings, cache box. A plain click on the effect, section, row name or
  pivot cell the explanation panel shows hides it again.
- Stem rows: colour swatches (and kick / snare / hat) in the row names; their tooltip and a
  click give the key. Bass is purple and melody green in the rows as in the magnifier. The
  stems box sits at the left of the legend row.
- The faces step's menu: "add a face (from an image) ...".
- Face viewer: a checkerboard behind pictures with see-through pixels (any alpha < 255);
  with the mouth / eye tools, a stroke that starts on a pixel that tool already marked
  unmarks, and the right button rubs out (as the rub-out tool).

0.22.1 (the user's review):
- **Tapping word starts**: in the magnifier, while the song plays, a click on the waveform (or
  the M key) leaves a mark there (rounded to 0.01 s; kept per song in the browser's storage -
  a convenience, nothing else depends on it). Red = no word starts there, green = one does.
  Paused: dragging a word's start (or the whole word) snaps to a mark within 12 px; a click on a
  mark removes it; "snap N words" pairs the red marks, in order, with the words from the one
  nearest the first red mark on (a word already on a green mark ends a run and is skipped),
  each run one `lyrics starts L.W T1 T2 ...` (new: the words from L.W on start at these times,
  each keeping its length cut at the next one's start; lines follow their words).
- **Timeline header**: section headings on top, then the waveform (its left column: tempo,
  time with the magnifier button, zoom, bar/beat key), then one row with the stems box, the
  effect colours centred and, on the right, the vocals button beside the waveform colours;
  then the timing and stem rows, then the row controls (by effect, fold, hide empty, filter,
  order), then the props. Undo / redo sit right beside Preferences.
- **Fix**: `run` without `--preferences` reset the preference folder to `./seqtool-prefs` of the
  *working* folder - which follows the current song's folder since 0.21.4 - so it found no
  stored layout ("no layout: ingest one first"), depending on where seqtool was when it ran.
  The default folder is now always that of the folder seqtool started in (`config._anchor`;
  `reanchor()` when it moves to ~/seqtool-files at start-up).

0.22.0 (the user: "drum, bass and other stems, and following the melody"): see section 5,
"Drum, bass and other stems, and the melody". MINOR: music.json gains fields and events and a
vocal-only analysis is redone when stems are on.

Next phases: B the layout panel (an overlay, not the lane column: the tree with role
per group, sequenced or not per prop, likes / avoids effects - possibly as a ring of the
effect families' colours - and a reaction), C a magnifier pane over the timeline for
editing in detail (lyrics row: words and their timing; D sections: drag a boundary,
merge, split, retype), E lyrics from an .xsq's timing tracks.


## DESIGN.md revisions and the review log

1. The layout input is xlights_rgbeffects.xml, through the xLights input adapter.
2–3. Props are characterised by generic shapes from the importer, the wizard,
   or (later) photos. Re-implementing xLights' node placement is the fallback.
   Semantic hints outrank geometry, but the geometry-only class is recorded for comparison.
4. Effect terms are corrected to generic ids, with a mapping table in the adapter.
5. The XSQ encoding is learned from a user-made reference kit (§7).
6. Groups are analysed per member or as a combined canvas. The `progression`
   capability captures prop-to-prop sequences. Render modes are deferred to the adapter.
7. Every measurement exists in both normalised (`*_norm`) and absolute form.
8. Hashes exclude transient keys. `lineage` carries the source-data hashes.
9–10. Scoring is restructured: gates, then a weighted sum, then Viterbi, then motifs.
11. The validator emits feedback, and the matchup iterates on it.
12. Multi-pass layering is adopted; pass 1 is implemented.
13. Sections have sequential indexes plus frame and beat ranges.
14. Whole-stream algorithms run on compact arrays; decoding streams.
15. Licensing is relaxed to "somewhat FOSS-compatible" for the prototype.
16. The project is separate from trackED; reusing its code is allowed.

rev 3 (seqtool 0.2.0) changes:
- Renamed xseq to seqtool, with a shebang launcher; no command runs the demo, and `test` / `--test` runs the unit tests.
- The frame interval is configurable.
- `*_rel` fields are renamed `*_norm`.
- Added the kit wizard, versioning, and stale-file handling.

rev 4 (seqtool 0.3.0) changes:
- The xLights importer was rebuilt from a real show file: boxed sizing,
  Custom depth layers, Poly Line PointData, trees, and floods.
- Added exclusions, group structure kinds, and views.
- Added the FIGURE and FLOOD classes, and moved 2-D geometry analysis to the
  best-fit plane.
- Target selection is now group-kind aware and avoids overlaps.
- The pipeline prints stage banners and writes the timeline viewer and
  Audacity labels, with repeat markers.
- No arguments prints usage; `-demo` runs the demo.

rev 5 (seqtool 0.4.0) changes:
- Shadow models are now sequenced and their channel helpers skipped, using
  channel-range resolution. Channel overlaps are reported, and
  `exclude_models` was added.
- `render_buffer` is kept separately from physical size.
- Group roles (top/unit/detail/off) were added, with the `groups` command.
- The explanation now shows weights and the arithmetic.
- The kit wizard was reworked: cumulative copies, max/min targets, corrected
  labels, file n of N, save path shown, paste-to-copy, and a loop until the
  file verifies.
- Prompts always reach the terminal and never block when there is none.
- The test runner shows a single progress line.
- `@lineno` suffixes are now on debug output only (`SEQTOOL_LINENO=1` adds
  them to warnings).

rev 6 (seqtool 0.5.0) changes:
- Asking is the default, and remembered answers become the next defaults.
- Added the user preference folder, overlaid on the never-modified defaults.
- Prompts use a short readline input line.
- Added the channel-overlap question.
- Kit wizard: relaxed placement, either editing style accepted, "aka"
  labels, n/N headings, Enter re-uses the last folder, kit-info.json, and
  per-version learned encodings.
- Paths are shown relative to the current directory.
- The "not planned" summary is condensed into counts by reason.

rev 7 (seqtool 0.5.1, patch: results unchanged, so 0.5.0 files stay fresh):
- Added `explain MODEL @TIME` (the demo shows it as a worked example) and
  unique-prefix commands.
- Shorter stale messages, with the version printed once at startup.
- Compact stage banners.
- Tolerant kit effect recognition (fixes chase.xsq being rejected) that
  reports what it found.
- Planned: effect thumbnails in the timeline.

rev 8 (seqtool 0.5.2, patch: analysis results unchanged):
- The kit wizard is now live and single-file: it watches the saves and
  checks each step immediately.
- The learned observations are written per xLights version.
- Added a .xsq reader (`adapters/xlights/xsq.py`), based on the user's real
  2025.13.1 file.

rev 9 (seqtool 0.5.3, patch):
- Kit wizard: "training file" wording and the model-type hint are back.
- 30 s sequences.
- Primary/companion settings.
- Blank max values rejected.
- Number Chases set to max; Repeat may be a checkbox; Movement minimum
  wording; Direction/Effect for Meteors.
- Any new timing track accepted.
- Added `--fresh`.

rev 10 (seqtool 0.6.0, minor: new output):
- The xLights exporter is implemented: learned encoding with spans, per-10s
  scaling, choices, sign and companions; the template-based writer; timing
  tracks; and the read-back check. It runs as pipeline stage 8.
- Clicking an effect in the timeline shows its explanation.

rev 11 (seqtool 0.7.0, minor: export values change):
- Interactive shell with tag-based command discovery.
- `inspect` (xlights, layout, audio), with discoverable targets.
- `layout` command and the stored layout.
- The summary and example explanation go to files.
- Musical rates (per second/beat/bar) for repetition settings.
- `assume` fallbacks for values xLights doesn't store.
- Kit v4 files are read (fixes the export crash).

rev 12 (seqtool 0.7.1, patch):
- Help topics, `clear`, and the `gui` command (usable mid-pipeline).
- The demo/run tail points to `gui`.
- Missing required arguments are prompted for, remembering answers.
- `layout` and `--rgbeffects` accept a folder.
- Section table heading in `inspect audio`.
- Kit compatibility check (kit_version / min_compatible).
- In `explain`, exact prop names win over fragments.

rev 13 (seqtool 0.7.2, patch):
- Glob patterns everywhere.
- `<base>-seqtool.<kind>` default names, and run results beside the song.
- `pwd`, `cd`, and `memory`.
- Absolute preferences folder.

rev 14 (seqtool 0.8.0, minor: section results change):
- Per-song seeds and scoped overrides.
- `reroll` with diff and undo; the seed is shown everywhere.
- Section rules (min_bars 8 by default).
- `sections` editing and Audacity label import, with fix-it hints.
- `classify-music` defaults to the latest analysis.
- `explain music`.

rev 15 (seqtool 0.8.1, patch):
- `pref` command (view/set/reset/changed/edit, plus the virtual param_map).
- `run` defaults to the last song.
- `status` shows the last song.

rev 16 (seqtool 0.8.2, patch):
- Live browser GUI with a console, song and cache status, and
  auto-refresh; global `--gui`.
- Leftover iteration files are cleaned up.
- Bar/beat count fix in `explain music`.

rev 17 (seqtool 0.8.3, patch):
- Server-Sent Events push replaces browser polling.
- Questions are asked and answered in the GUI console, with Esc to cancel.
- "Waiting for …" messages between the GUI and the terminal.
- Per-thread output routing.

rev 18 (seqtool 0.8.4, patch):
- One shared "current song" across single stages and pipeline results; the
  GUI follows it and refreshes for every stage.
- First-command output fix (connect first, chunked catch-up).
- Waveform peak cache.

rev 19 (seqtool 0.9.0, minor: the analysis adds chroma and segmentation, so
music files are rebuilt):
- Laplacian segmentation and the combined method.
- Exact section times with optional snapping.
- Custom section types with aliases.
- Confirmation before replacing edits.
- `match` defaults to the current song.
- GUI: keystroke focus, the stuck-"running…" fix, and quiet connection
  errors.
- Up-arrow history with `--gui`.

rev 20 (seqtool 0.10.0, minor: continuity changes results):
- Music-contrast continuity.
- Music-reactive roles (`react`).
- `explain` "based on" notes and colour reasons.
- Optional timing tracks.
- GUI lanes sorted by name.
- Fresh results are rounded exactly as stored, so first runs and re-runs
  agree.
- MVP scorecard (§13a).

rev 21 (seqtool 0.11.0, minor: layer order and reactive plans change results):
- Exported timing tracks join the training file's views; the export reminds
  the user to add them to the Master View otherwise.
- Beat timing marks are labelled with the beat number in the bar.
- `react --over` layers are now the top xLights layer.
- Reaction presets with conditions (`presets`, `react A,B`), replacing the
  fixed modes (which remain as presets).
- Name rules (`rules`): defaults by regular expression on model/group names.
- `effects` and `help effects`: what each effect type looks like and suits.
- GUI and timeline: colour-coded bar ticks (numbered) and beat ticks.
- "heard/ideal" wording in `explain`.
- MVP item 9 done (opened in xLights).

rev 22 (seqtool 0.12.0, minor: the built-in presets changed, so plans are
rebuilt; results are otherwise the same):
- `explain MODEL` without a time: the settings that apply all the time
  (kind, class, how it is planned, allowed effects, preferences, reactions
  and their presets, name rules, seed overrides) and its effects over the
  song. In the GUI and timeline, click a name in the left column.
- GUI Help button: a filterable tree of the overview, pipeline, each help
  topic's commands, effect types and presets, with the full help text.
- "bars / beats" label for the tick row.
- Presets: `split` and `{"step": [...]}` (a step sequencer within the bar);
  example preset `bar-steps`.
- Backlog (§13b).

rev 23 (seqtool 0.13.0, minor: new passes and effects change results; kit v6):
- CSS-style keyframes for presets (syncopation, glides with timing functions)
  and ramps exported as value curves.
- Submodels imported and analysed; groups of submodels plan on their parts.
- Top, detail and enhance passes (§9); row order for xLights precedence.
- Kit v6: Fill, VU Meter, submodel rows, value curves; `xlights-kit --update`
  learns only the new steps. Older kits stay usable; unlearned effects are
  not planned (or are substituted at export).
- Lyrics import (LRC / Audacity), the `seqtool-lyrics` timing track, `lyric`
  and `word` triggers, `~regex` conditions.
- Effect thumbnails in the GUI and timeline.

rev 24 (seqtool 0.14.0, minor: glides are written as steps; kit v7):
- Precedence confirmed (uppermost layer wins; later rows win).
- Value curves dropped: glides become short stepped effects.
- Kit v7: VU Meter sensitivity is learned while Level Bar is selected; a
  choice set back to its default counts as a change (VU Meter Waveform); the
  submodel step is last and says so; no value-curve step.
- `layout` and the export offer to run the training wizard when it is
  missing or incomplete.
- `tutorial` command; inline colour codes everywhere; larger previews.

rev 25 (seqtool 0.15.0, minor: spiral direction and kept 'off' segments change results):
- Spirals direction fixed: in xLights a negative Movement turns clockwise.
- 'off' explained (no threshold; best lit choice vs off), kept in later
  passes, drawn as outlines; empty lane areas explain the moment.
- Quoted example commands highlighted automatically everywhere.
- Older-kit messages: complete trainings say "nothing to re-learn";
  `xlights-kit --update` then marks them current; `--fresh` re-learns all.

rev 26 (seqtool 0.15.0, docs only): effect table (fill, vu_meter), milestones,
§13d state / unchecked items; HANDOFF.md for continuation sessions.

rev 27 (seqtool 0.15.1, patch: results unchanged; music.json files made with
--stems by 0.15.0 are rebuilt once): the vocal stem is checked like any other input
(§5): stems on/off and a missing or changed stem make music.json stale; `status`
reports it; the reuse line names the stem; Demucs progress is shown. Agreed
roadmap (§13e): dark/transparent, top-down base pass, style training wizard,
lyric transcription back on the list.

rev 28 (seqtool 0.15.2, patch: results unchanged): vocals in `inspect audio` and
as a line over the waveform (GUI and timeline page); a failed `--stems` is an
error with a question; `doctor` setup check; `baseline save|diff` for tuning on
real songs; `groups` defaults to the stored layout.

rev 29 (seqtool 0.16.0, minor: the effect id `off` is now `transparent`, models.json
gains role guesses, so plans and models are rebuilt; kit v8): `transparent` /
`dark` (§9, §11); `pin` / `unpin` and `run --candidates N` (§7a); guessed group
roles with reasons and a one-question review (§8); change reports and the
summary table name later-pass layers ("MegaTree (enhance)") - before, a prop's
enhance row overwrote its main row in `reroll`'s report.

rev 30 (seqtool 0.17.0, minor: group role choices change - duplicates by level, flat
whole-yard groups are top, role 'off' is 'unused' - so models are rebuilt): example
fix commands in problem messages (status, validator, unknown names); group levels
from numbered names; group_kind / role name rules; groups sorted by name;
paths relative to the song or layout; GUI menu bar, pin and die on effects,
trackED-style waveform, red close button, clicked layer explained first; deps
checked without importing, restart offer; baseline defaults to the last song.
Roadmap numbers moved up by one (base pass is now 0.18).

rev 31 (seqtool 0.17.1, patch: plans unchanged): quitting the prompt closes the GUI;
an open explanation is redone when results change; rerolling a pinned effect
changes only its settings (and says so); vocal/instrumental/mixed passages
shorter than music.display.min_region (2 s) merge into a neighbour; stronger
waveform colours; clearer 'lyrics import' message and two lyric presets
(lyric-color, word-flash).

rev 32 (seqtool 0.17.2, patch: plans unchanged; profiles rebuild once for the new
novelty_weight setting): `sections score` / `sections tune` against the user's
fixes; undo / redo; player commands (play, pause, seek, volume, speed) and
playhead buttons; Demucs progress; tooltips further from the pointer.

rev 33 (seqtool 0.17.3, patch): `baseline save SONG` adds to the baseline instead of
replacing its songs (the user's 3 single-song saves left 1); `baseline remove`;
fixed songs found next to known songs, missing ones named; `sections score
[SONGS] --detail`; `sections --audio SONG`.

rev 34 (seqtool 0.17.4, patch: plans unchanged): section lists show start - end
(length) in m:ss; vocals / mixed / instrumental decided by a singing gate on the
stem plus voice-vs-mix lead, `inspect vocals`; `sections snap`, the snap
preference, one-bar scoring tolerance, clearer detail wording; `run --baseline
[N]`, numbered baseline songs; sections score / tune / snap and inspect vocals
in the GUI menu.

rev 35 (seqtool 0.17.5): sections snap to bars by default (said in `sections`;
import aligns too); vocal-entry section candidates (`sections.vocal_entry`, off;
in the tune grid); analysis of the user's songs recorded in §6; GUI vocal sliders
with live recolouring; `vocal_hold` replaced by `vocal_gap` (gap length, edges
kept); `pref` accepts a number where the default is 'auto'; tune reports "already
the best" on ties.

rev 36 (seqtool 0.17.6): moved songs are found again (same file name in a folder
songs were used from or a sibling of one, same checksum when known; remembered
answers, baselines and analysis paths are updated, and a remembered prompt
default that no longer exists is relocated or dropped); lyric repeated-block
section candidates (`sections.lyrics`, in the tune grid); sections score / tune
prefer the newest analysis and flag old ones; `pin TARGET --all`; GUI row
buttons (pin / reroll a whole row, shown on hover).

rev 37 (seqtool 0.17.7): the playhead stays in view while playing and after a
seek (GUI and static page); vocal passages smoothed over 1 s by default
(`vocal_gap` 1.0, `min_region` 1.0; the user's slider trials). Section scores on
a re-analysed tuning song: addendum A1.

rev 38 (seqtool 0.18.0): lyrics transcription (`lyrics transcribe`, faster-whisper
on the vocal stem) and alignment (`lyrics align`, plain-text import); section
boundaries and types from the words (`music/lyric_structure.py`,
`sections.lyric_min_bars`, `type_why`, in score --detail and the tune grid); the
profile is rebuilt when the lyrics change (`source.sections.lyrics`); the vocal
auto gate is kept 12-18 dB below the loudest singing (was 12-30); playhead
follows by half a page; Space plays / pauses; `pause` in the play menu; lyrics
menu. Roadmap: base pass 0.19, style training 0.20, kit wizard in the GUI 0.21.

rev 39 (seqtool 0.18.1, patch): `baseline add [SONG]` / `remove SONG|N` / `update` /
`diff` (`save` kept as an alias); Whisper models: offered for download when not
there, unknown names explained, `lyrics models`, the last-used model remembered.

rev 40 (seqtool 0.18.2, patch): Whisper progress and memory check; `status` checks a
moved song's vocal stem where the song is now (it looked next to the old path, so
music.json stayed STALE after a run, and the fix hint named the old path), gives
one fix per results folder (`--out` when the folder isn't the song's own), and
`run` warns if any of its results are still stale afterwards ("please report");
"has moved" is said once per session.

rev 41 (seqtool 0.18.3, patch): a renamed song's old result files (same audio, old
file name, in its results folder) are no longer counted as its results - `status`
lists them apart and `status --clean` deletes them (`current.leftovers`; 0.19.8: also
`current.superseded` - single-stage results left next to the song, `<song>-seqtool.music.json`
..., once the song's results in use are in its -seqtool folder: `run` never rewrote them, so they
stayed stale for ever; now they aren't counted, `run` and `status` say so, `--clean` deletes them;
an old `--out` folder counts only while its results are the ones in use); `status`
finds a moved/renamed song's stem through the current song (same audio) and no
longer relocates anything itself (0.18.2 could re-point remembered paths while
only looking); the GUI title and header show the seqtool version.


rev 42 (seqtool 0.18.4, patch): stage commands and the results folder agree.
`analyze-music SONG` writes into the song's results folder (`<song>-seqtool/<song>.music.json`)
when it has one (`paths.stage_output`), else next to the song as before; classify-music,
match and validate name their output like their input (`paths.sibling`: song.music.json ->
song.music-profile.json; before, a results-folder input got a 'song-seqtool.*' file
beside it and the folder's own file stayed STALE). classify-music, match --music and
validate --matchup take a song (its newest results; `current.music_of` / `results_of`),
validate defaults to the current song. `--baseline [N]` works on analyze-music,
classify-music, match, validate, lyrics and sections (`__main__.BASELINE_ARG`; no N =
each song in turn). An audio file or other non-JSON where a .json is expected, and a
missing file, give a one-line message (`canonical.NotJSON`, `__main__._friendly`)
instead of UnicodeDecodeError / FileNotFoundError.

rev 43 (seqtool 0.18.5, patch): `lyrics transcribe` says the song, the model and why
(--model / the one used last / the default), free memory against what the model
needs, the language found, and a line before the slow start; `--baseline` names
the song it works on ("baseline song N: ..."); every command warns when the
installed VERSION is newer than the running session (a GUI or prompt started
before an update runs the old code - the likely cause of the user's report that
`lyrics transcribe --baseline N` used the last song, which could not be reproduced).

rev 44 (seqtool 0.18.6, patch: plans unchanged): design clean-up (stage banner and the 8
stages, default file names since 0.18.4, exporter no longer "pending", role
`unused` throughout, MVP scorecard complete, §13d/13e/14 brought up to date and in
order, §7a retitled, duplicate bullet removed); the verification sequence
`xlights-export --checks` (§13d, also in the GUI menu); messages about overlapping
detail groups say `unused` with a `pref` example instead of "off", and the summary
groups unused groups again; the Whisper progress test no longer depends on running
under a terminal. Roadmap revised with the user (§13e): singing faces 0.19 (Matrix
first, faceInfo XML snippet), base pass 0.20 with one-aspect variations, duration
limits and a members option (cut / over / under), style training 0.21, the
action list; design notes in §13f.

rev 45 (seqtool 0.19.0, minor: VU Meter choices and pins on top groups / group members change
plans; layouts gain faces, so stored layouts are re-ingested): singing faces, part 1 - the face
format learned from the layout (`faceInfo` keys, eye states, image names, path style; shipped
fallback learned from the user's 2025.13.1 layout), `face build MODEL IMAGE` (mouth shapes and
closed eyes from a pixel image, 20 images, contact sheet, `faceInfo` XML snippet), `face list`,
`face format`, `inspect faces` (§13f). Pins: on a top group they make it take over there (they
used to change nothing: "no visible change"); on a prop a group sequences they give it a row of
its own, exported after the group's so it wins (`pin Tree @1:08 dark`); unused pins are said;
detail and enhance layers rest where a top group plays; the pin report sums up resting targets.
`--baseline [N]` on the commands that work on the current song (xlights-export, explain, pin,
unpin, reroll, gui, status, inspect, play). VU Meter: xLights' Sensitivity is a threshold, so
Level Bar with a high value only moved at the loudest moments (the user's check); kit v9 learns
Volume Bars and Spectrogram, the automatic choices are Volume Bars / Spectrogram / Waveform with
Sensitivity near its default, and the verification slots start at the song's first chorus.
GUI: the song name coloured, bar and beat ticks with more contrast.

rev 46 (seqtool 0.19.1, patch for existing plans - only props given a face change): singing
faces, part 2 - phonemes (CMUdict by default, other dictionaries and the user's own words by
preference, spelling guesses listed; the third layer of seqtool-lyrics; `lyrics phonemes`),
kit v10 with xLights' Faces effect (a `text` kind in the parameter map for the face name and
timing track), `face use PROP FACE [--over]` and face plans that sing the lyric lines (§13f).
`face build` takes globs, ~ and bash-escaped spaces in the image path like every other path
(it took the path literally, so a pattern was "not found"), and a missing file names the folder
seqtool is in. Kit problems are no longer reported for choice settings (they have no extreme).

rev 47 (seqtool 0.19.2, patch: plans unchanged): rules for every command - wildcards in any path,
`--baseline [N]` for any song (§2). Pronunciations: an add-on dictionary
(seqtool-prefs/pronunciations.dict, or a sticky `--dictionary FILE`, `--dictionary default` to
go back) instead of the `phonemes.words` preference; guessed words listed as lines to correct
and paste. Kit v11: the Faces timing-track step explains the breakdown xLights needs; the
"Eyes: Auto" step is gone (it is the default, so it could never change - the user got stuck).
`face build`: the face definition with a Copy button in the GUI (new `{copy}` code) and on the
clipboard at a terminal; clearer step 4; `face show NAME` / `inspect face NAME` flips through a
face's images in a GUI panel. GUI: Ctrl+click on an effect opens a list of effects to choose
for that moment (the best for the prop's type first; "auto" removes your choice); the row and
unpin commands use the lane's pass (top, pin, detail) so they match the pin.

rev 48 (seqtool 0.19.3, patch): `tutorial faces` - the end-to-end lyrics and singing-face test
as a tutorial (new checks and placeholders); `package` - a self-extracting seqtool-X.Y.Z.pyz for
Linux and Windows that unpacks next to itself on first run and upgrades with a manifest check:
unchanged files replaced silently, customised ones asked about (§12b).

rev 49 (seqtool 0.19.4, patch): DESIGN-addendum.md takes the developer's own songs and show
(measurements, song names, the layout's props and faces); DESIGN.md keeps the general design
with pointers. Transcription checks (§7a): sung passages without words are named and transcribed
again without the voice filter; `lyrics transcribe --diagnose` writes a Whisper log; `--no-vad`,
`--no-refill`; alignment without apostrophe and hyphen mismatches, global (repeat-safe) and
tolerant of near words, with a report of unrecognised stretches (`--report`). `lyrics phonemes`:
clearer counts, guesses in a copy block, words shown with their mouths, doubled consonants
fixed. Face detection: background by flood fill, features surrounded by skin, eyes first,
detection at the image's own size; `<name>-boxes.png` with a ruler. The kit's clean-up also
offers to delete the training file's .fseq.

rev 50 (seqtool 0.19.5, patch): `--debug` replaces `--diagnose` and is the rule for commands that
can surprise (lyrics transcribe / align / phonemes, sections, face build; `common/debuglog`).
Completion at the prompt and as-you-type in the GUI console (`common/complete.py`). Transcription:
lines split at long pauses, so refilled passages no longer interleave. `lyrics align` reads LRC /
labels as lyrics (their stamps were taken as words), uses the file's times to pair repeats and to
place unrecognised lines, leaves fillers out, matches common variants. Face viewer: pointer
coordinates on the grid and box labels as tooltips; readable labels on the boxes picture.

rev 51 (seqtool 0.19.6, patch): transcription - words Whisper stretches over the music are
shortened before looking for passages without words, and after the refill the lines are untangled
(no overlaps; duplicates once); the refill shows progress; the debug log lists the lines as kept.
`lyrics align --times heard|file` and a whole-file offset for LRC. `history` and `!N` / `!!` /
`!TEXT` (prompt and GUI, one file). An unwritable or Windows system start folder -> ~/seqtool-files.
Face viewer: drag a rectangle, copy the `face build` command. Face fills: lids and the old mouth
from the colours round them; lips/tongue the darkest, teeth the lightest in the mouth box.

rev 52 (seqtool 0.19.7, patch): lyrics with line times are timed from their phrases (the user's
design): starts from the file, ends from the vocal stem, words and sounds shared out by weighted
sounds (vowels hold, consonants keep their spoken length), nothing in a breath; no transcription
needed (`--times heard` for the Whisper way). Whisper lines no longer split off a dangling "I" /
"the" / "to".

rev 53 (seqtool 0.19.8, patch): progress for long work is a rule (`common/progress`; `sections
tune` has it). Unused groups say why in a few words. Older single-stage results next to the song
no longer show as stale once the song's results are elsewhere (`status --clean` deletes them). GUI
console: Up/Down move in the completion list while it is open, else in the history.

rev 54 (seqtool 0.19.9, patch): single stages write into the results subfolder, never beside the
input; completion no longer calls commands that don't use argparse (the stray preference list);
`run` without --audio fixed (UnboundLocalError) and a static test for that kind of bug; ...-all
groups are umbrella by default; tutorials with skipped steps are incomplete; the rules tutorial
explains patterns; `help rules` shows the help; `react` takes the current song's (demo) props.

rev 55 (seqtool 0.19.10, patch): version in every help; `pref` accepts new names in maps of your
own (section_types); GUI monospace font stack names Linux fonts; the demo's place stated.

rev 56 (seqtool 0.19.11, patch): `status` reports a stale stored layout (and `layout` re-reads
it); props on 'No Controller' are planned like the others.

rev 57 (seqtool 0.20.0, minor): the base pass - whole-yard moments (unison hits, sweeps in yard
order, call and response), escalating with repeats, a budget per minute, and the members option
(cut / over / under); effect duration limits and one-aspect variations; TOO_SHORT / TOO_LONG;
yard positions in models; "settings used" notes. Older analyses and plans are stale (0.19 -> 0.20).
Roadmap: stems and melody next (0.21), then style training.

rev 58 (seqtool 0.20.1, patch): `models` lists the props; unused groups explain in general words;
"same sequenced props" when the members differ; shadow-covered props worded generally; prop-wizard
says what it is for.

rev 59 (seqtool 0.20.2, patch): `pref NAME` shows valid values and what it does; pref names
complete after a dot; skip_shadow by default; inactive xLights models not planned; prop-wizard can
add to the stored layout and `layout` asks to keep such props; faster model analysis.

rev 60 (seqtool 0.20.3, patch): models following a shadow model (asked, remembered); GUI pivot
by effect type, row filter, folded moments; `sections from-xsq` deduces sections from an existing
sequence; borrowing from an .xsq and long-table ideas written down (not built).

rev 61 (seqtool 0.20.4, patch): borrowing from an existing .xsq (xsq-borrow, borrow, unborrow; the
pass 'borrowed', written as it is); long tables in the GUI (members under groups, sort, stars,
mini-map); the timeline's controls, legend band, length and play head, section headings explained.

rev 62 (seqtool 0.20.5, patch): submodel groups are units by default (a prop is planned once,
also when only groups of its submodels cover it); group role reasons that say something, a guide
and random-access role changes in `groups`, `groups NAME`; face viewer zoom, left / right eye
boxes, colour touch-up kept across rebuilds; the completion list no longer wraps at the top.

rev 63 (seqtool 0.20.6, patch): `groups NAME` lists everything (no cut lists), every matching
group, and for a prop the groups it and its parts are in; role reasons with singular / plural and
"under 1%".

rev 64 (seqtool 0.20.7, patch): `groups PROP` closest groups first, `max_list` / `--all`; props
no unit covers go to the closest umbrella group (`loose_props_to_umbrella`), and a prop on its
own says why (`why_target`, in explain); faces marked pixel by pixel, filled from the colours
round them, colours picked in the viewer (`--marks`); viewer labels, font and red close button.

rev 65 (seqtool 0.20.8, patch): face marks kept inside the PNG (a tEXt chunk; `face build`
finds them, `--no-marks`); only the widest top group plays - said in the guide / help / reasons,
and `groups` warns about top groups it won't use; rule patterns may start with '-'.

rev 66 (seqtool 0.21.0, minor - everything is rebuilt once): promote / demote (pins of pass
'place', the place pass, GUI selection and menu); explain says first who carries a prop; face
marks drawn as borders; shorter reason for umbrella top groups; role reasons from analyses made
before 0.20.5 no longer say "0 props" (and 0.21 re-analyses the layout).

rev 67 (seqtool 0.21.1, patch): whole-row promote / demote; promotion candidates (twins once,
unusable ones with why); unpin through repeats; GUI click hints, compare two effects, hide
empty rows, section headings on three rows; models: nodes, closest groups, --disable / --enable.

rev 68 (seqtool 0.21.2, patch): every group holding a selection is offered for promote (6.Wise-all);
`layout --forget`, and `help layout` says how to use another layout.

rev 69 (seqtool 0.21.3, patch): promote --list / the menu say why a group isn't offered; a placed
effect a target can't play is said; history.txt with session lines; `songs` and `songs forget`.

rev 70 (seqtool 0.21.4, patch): reactions per song and per section (react --song / @#N, the effect
menu); legend tooltips with xLights names; export finds the song's audio; completion keys and
alphabetical lists; the working folder follows the current song.

rev 71 (seqtool 0.21.5, patch): folders end in '/'; one icon per effect (pin or '...') opening the
menu with pin and reroll; placed / pinned props keep their own row; reactions leave placed rows.

rev 72 (seqtool 0.21.6, patch): group and model names complete for `groups` / `models`; no
duplicate dict keys (static test).

rev 73 (seqtool 0.21.7, patch): the GUI workflow, phase A - step bar, file picker, dropped files;
`open-xsq` (an .xsq as it is, `--fill`, `--as-is`).

rev 74 (seqtool 0.21.8, patch): step bar checks / arrows / short text; timing tracks as rows and
`sections from-timing`; the layout panel with the effect wheel (`groups --role`, `models --exact`,
`prefer`); shorter `groups` reasons; time line and full row names in tooltips.

rev 75 (seqtool 0.21.9, patch): preferences window; the effect wheel as a pie with weights
(`prefer EFFECT=WEIGHT`); role / reaction tooltips; the magnifier (phases C and D): lyrics and
section editing by mouse (`lyrics word`, `lyrics time`).

rev 76 (seqtool 0.21.10, patch): responsive effect wheel (queued commands); undo / redo buttons and
keys; magnifier speed, volume, draggable region; `lyrics shift`; `lyrics from-xsq` (phase E); face
viewer layout and picture size.

rev 77 (seqtool 0.22.0, minor): four Demucs stems in the results folder; drum hits, bass notes,
melody (YIN on the voice, a sustain-cancelling salience on 'other'); stem triggers and values for
reaction presets (kick, snare, hat-sparkle, bass-pulse, melody-fill, melody-color); drums / melody
in music_fit; stems in explain, inspect audio, GUI rows and the magnifier.

rev 78 (seqtool 0.22.1, patch): tapped marks and word snapping in the magnifier (`lyrics starts`);
timeline header rearranged; undo / redo beside Preferences; the preference folder no longer
follows the working folder (the "no layout" after `layout` + `run`).

rev 79 (seqtool 0.22.2, patch): Esc closes the panel shown last, a second click hides the
explanation; stem colour keys; stems box at the left; "add a face" in the faces step; face viewer
checkerboard and unmarking pixels.

rev 80 (seqtool 0.23.0, minor): ~/seqtool-prefs by default; `face write` / `face remove [--xlights]`
(text edit of xlights_rgbeffects.xml, backup in seqtool-backups/); face viewer overlays follow
size changes; marked mouths drawn inside their pixels; made pictures recognised (PNG chunk).

rev 81 (seqtool 0.24.0, minor): singing as the reaction preset 'sing' (per section); several faces
per prop with voices ({VOICE} codes, 'lyrics voice') and areas (sub-buffer learned by 3 kit steps);
a timing track per voice; GUI focus fix; magnifier play/pause label.

rev 82 (seqtool 0.24.1, patch): drag tapped marks; M works with the console line focused.

rev 83 (seqtool 0.24.2, patch): the kit wizard runs in the GUI (Enter after each save); --update lists
only the missing steps.

rev 84 (seqtool 0.24.3, patch): magnifier drop shown at once, previous word cut, sung word lit, speed
box keeps its keys; path completion for questions; kit sub-buffer steps use the right-click presets.

rev 85 (seqtool 0.24.4, patch): a closed GUI page cancels its command; `lyrics tidy`.

rev 86 (seqtool 0.24.5, patch): "play here" from the view's start exactly; a dragged green mark takes
its word along.

rev 87 (seqtool 0.24.6, patch): magnifier: vocal-stem waveform / mix toggle, one-sided toggle, bigger
button, wider mark grab, words keep touching; phrase boundaries follow moved words.

rev 88 (seqtool 0.24.7, patch): magnifier settings remembered, vocal ribbon, `lyrics shift ... from L.W`.

rev 89 (seqtool 0.24.8, patch): magnifier edge snapping to the singing (music/edges.py), tapped marks
off, touching words stay touching, `lyrics split` / `lyrics join`.

rev 90 (seqtool 0.24.9, patch): magnifier edge zones wider inside; direction cursors.

rev 91 (seqtool 0.24.10, patch): edit a phrase's text (`lyrics line`, magnifier edit text).

rev 92 (seqtool 0.24.11, patch): magnifier repaint, no overlaps, sticky section headings, rerun
rebuilds without asking, a reaction set here takes away pins there.

rev 93 (seqtool 0.24.12, patch): waveform stays at the top too; menu on reaction / singing effects.

rev 94 (seqtool 0.24.13, patch): reaction runs and "reacting" cells with menus; row hover icons fixed.

rev 95 (seqtool 0.24.14, patch): effects-vs-reactions tutorial step; sticky legend; disable re-plans; row pin menu.

rev 96 (seqtool 0.24.15, patch): submodels shown as parts in the layout panel; detail-row pins used.

rev 97 (seqtool 0.24.16, patch): singing faces as a choice in the layout panel; face use re-plans.

rev 98 (seqtool 0.24.17, patch): own player controls; lyrics row; export menu; split remembered; every-song settings win now.

rev 99 (seqtool 0.24.18, patch): cues; four steps with submenus; no empty moments rows; Faces text settings found; kit --redo.

rev 100 (seqtool 0.24.19, patch): WAV play copy for exact positions; waveform buckets placed by their real length.

rev 101 (seqtool 0.24.20, patch): Faces face and phoneme track set from a kit whose track step repeats the face.

rev 102 (seqtool 0.24.21, patch): gaps between touching words; word split / join; cues in the magnifier.

rev 103 (seqtool 0.24.22, patch): timing tracks inactive in the .xsq; C taps cues.

rev 104 (seqtool 0.24.23, patch): phonemes fitted to the words as they are now.

rev 105 (seqtool 0.24.24, patch): reactions on certain sung words (PRESET[w1|w2], react --words, GUI).

rev 106 (seqtool 0.24.25, patch): wider mouths; palette choice + wheel; meteors on radial props; @vocals; PRESET@EVENT.

rev 107 (seqtool 0.24.26, patch): palette wheel clearer, stays open while trying choices.

rev 108 (seqtool 0.24.27, patch): re-plan timings; timeline waveform cached.

rev 109 (seqtool 0.24.28, patch): quicker re-plans (no export / timeline page after each change).

rev 110 (seqtool 0.24.29, patch): batch - several commands, one re-plan, one undo step.

rev 111 (seqtool 0.24.30, patch): feel controls; fseq reader; direction tutorial.

rev 112 (seqtool 0.24.31, patch): fseqdump.py stand-alone; re-plan progress; tutorial setup step.
rev 113 (seqtool 0.24.32, patch): absolute channels from xlights_networks.xml; one-line progress rule; skill in the download.
rev 114 (seqtool 0.24.33, patch): direct (offline intent router) and --eval.
rev 115 (seqtool 0.24.34, patch): fuzzy matching, @WORD, enlarge-by, late options, bundle, start.
rev 116 (seqtool 0.24.35, patch): networks stale check; skill: using BUNDLE, missing-capability lines.
rev 117 (seqtool 0.24.36, patch): pin settings, group render styles, demo show files and demo --bundle.
rev 118 (seqtool 0.24.37, patch): pin onset/offset, quiet start, GUI start, reaction explain.
rev 119 (seqtool 0.24.38, patch): section from from=/until=, vocal edges cached.
rev 120 (seqtool 0.24.39, patch): pin from/until in the GUI menu; --later + replan; GUI re-plans in a child process.
rev 121 (seqtool 0.24.40, patch): all GUI changes plan asynchronously.
rev 122 (seqtool 0.24.41, patch): tap-mark word drag fix; palette panel after the plan.
rev 123 (seqtool 0.24.42, patch): voice codes inside words; skill lists of directions.
rev 124 (seqtool 0.24.43, patch): voice code at a word end; voice flags in the magnifier.
rev 125 (seqtool 0.24.44, patch): lyrics word replaces the word's voice codes.
rev 126 (seqtool 0.24.45, patch): codes at both ends of a word.
rev 127 (seqtool 0.24.46, minor): plan for choreography; palette colors; picture effect; definitions.
rev 128 (seqtool 0.24.47, minor): choreo effect; files brought into the show folder; start runs xlights-kit --update; face --over default.
rev 129 (seqtool 0.24.48, minor): value curves learned by the kit; glides, rotation, choreography keyframes.
rev 130 (seqtool 0.24.49, minor): call and response from tagged cues; only / pitch spread / order; angle submodels.
rev 131 (seqtool 0.24.50, minor): per-song score (score / write / apply / note).
rev 132 (seqtool 0.24.51, patch): value curves as xLights really writes them (left-out fields, dropped slider).
rev 133 (seqtool 0.24.52, patch): the kit's rotation step points at Roto-Zoom > Z rotation.
rev 134 (seqtool 0.24.53, minor): shared parts (segment, settings, durations, glide runs); react steps.
rev 135 (seqtool 0.24.54, patch): general.directions (ask | decide) for the seqtool-direction skill.
rev 136 (seqtool 0.24.55, patch): new-user test fixes (bare lyric times, missing-package message, generic examples, skill role and first steps).
rev 137 (seqtool 0.24.56, minor): update check and 'update' (GitHub releases or the main branch).
rev 138 (seqtool 0.24.57, minor): adjust (settings over what plays, faces too); Windows console colours; overview and source map.
rev 139 (seqtool 0.24.58, patch): second new-user test fixes (Windows paths, kit labels and Pictures, status kit line); REVISIONS.md split out; favicon.
rev 140 (seqtool 0.24.59, patch): real-song fixes (effects listing, choreo note, Windows line editor, kit prerequisites / --list / --redo N, GUI copy and sticky column, dir, seqtool.pyz launcher).
