# seqtool — music → light-sequence toolchain (prototype, v0.24.57)

The design is in [DESIGN.md](DESIGN.md) (findings on the developer's own songs and show: DESIGN-addendum.md); [HANDOFF.md](HANDOFF.md) is the short version for picking up development (state, conventions, open items). The core is generic; xLights lives in `seqtool/adapters/xlights/`.

## Quick start

You need Python 3.10+ and numpy. ffmpeg is optional and is only needed for MP3 and other non-WAV files.

```bash
unzip seqtool-0.24.57.zip && cd seqtool
./seqtool.py            # interactive prompt: type 'help', 'demo', 'inspect audio', 'quit' ...; Tab completes (twice: choices); 'history', '!!', '!N' 
./seqtool.py -demo      # or run one command and exit: the demo
./seqtool.py --gui      # prompt + live browser GUI (menu, timeline with pin/reroll on each effect and each row, a console that runs commands)
./seqtool.py -h         # usage; 'help setup', 'help stages', 'help commands' for the rest
./seqtool.py --test     # unit tests: one progress line; -v for the full list (also: ./seqtool.py test)
./seqtool.py --help     # all commands and global options
```

`python3 -m seqtool ...` works the same as `./seqtool.py ...`.

The demo writes every intermediate file to `./seqtool-demo/`:

| file | what to look at |
|---|---|
| demo-song.wav / demo-song.truth.json | generated test song (128 BPM, intro/verse/chorus/verse/chorus/outro) and its ground truth |
| demo-song.music.json | tempo, beats, boundaries, columnar frames (`frame_interval` inside) |
| demo-song.music-profile.json | styles, labelled sections (`index`, `frame_range`, `repeat_of`) |
| layout.json / layout.models.json | generic props → geometry class + capabilities |
| demo-song.matchup*.json | effect plan per target, score breakdowns, reasons (one per iteration) |
| demo-song.validation*.json | issues + feedback driving the next iteration |
| demo-song.timeline.html | waveform + sections + effect lanes; play, zoom, hover; click an effect for its explanation |
| <song>.xsq | with --rgbeffects and a learned kit: the xLights sequence |
| demo-song.labels-*.txt | Audacity label tracks (File > Import > Labels...) |

## With Claude

`skills/seqtool-direction/SKILL.md` is a skill for Claude: add it to your Claude account (Settings,
or ask Claude to save it) and Claude can set seqtool up with you, turn directions like "bigger
chorus" into seqtool commands, run them and check the result.

## Your own material

```bash
./seqtool.py doctor                                                 # is everything set up? says what to do next
./seqtool.py update                                                 # a newer seqtool? (also looked for at start, once a day: pref general.check_updates)
./seqtool.py tutorial                                               # guided walk-throughs (basics, your-song, react, rules, lyrics, xlights...)
./seqtool.py layout /path/to/show                                   # ingest the show layout once (folder or file)
./seqtool.py layout /path/to/other/show                             # another layout: replaces the stored one ('layout --forget' clears it)
./seqtool.py run --audio '../Songs/*.mp3'                             # then just give the song (globs ok); results go to ../Songs/<song>-seqtool/
./seqtool.py inspect audio | inspect layout | inspect xlights        # details about things
./seqtool.py gui                                                    # waveform, sections, effects in the browser (or: gui audacity)
./seqtool.py sections                                               # list sections; merge/split/move/type/import to fix them
./seqtool.py sections score                                         # how well detection matches the songs you fixed
./seqtool.py sections tune                                          # the detection settings that match your fixes best
./seqtool.py sections snap bar                                      # move your own boundaries onto the nearest bar line
./seqtool.py inspect vocals                                         # where the singing is: stem levels, gate, passages  (GUI: 'vocals' sliders)
./seqtool.py run --baseline 2                                       # run song 2 of the baseline again ('run --baseline': all)
./seqtool.py undo                                                   # undo the last command that changed settings; redo; undo --list
./seqtool.py play chorus 2                                          # GUI player: play [#N|TYPE|@TIME], pause, seek -5, volume 80, speed 0.75
./seqtool.py reroll MegaTree @#3                                    # new random choices for one prop in one section; reroll --undo
./seqtool.py pin MegaTree @#3                                       # keep MegaTree's effect in section 3 (and its repeats)
./seqtool.py pin MegaTree @#3 spirals                               # or force one; 'dark' blacks it out; 'pin' lists, 'unpin' removes
./seqtool.py pin MegaTree --all                                    # keep MegaTree's current effect in every section
./seqtool.py promote Flood01U Flood02U @#3                          # their effect in section 3 goes to the closest group holding both (--up N, --to GROUP)
./seqtool.py demote 4.Floods-all @#3                                 # the group's effect goes to what is in it (--down N, --to props)
./seqtool.py promote Flood01U --all --to 4.Floods-all                # the whole row, section by section
./seqtool.py models Tree --disable                                   # don't sequence Tree (--enable undoes it)
./seqtool.py songs                                                   # songs with kept settings (pins ...); 'songs forget N' forgets one
./seqtool.py open-xsq Song.xsq                                       # start from an existing sequence as it is (--fill: seqtool plans the empty rows)
./seqtool.py prefer Arches twinkle=like fire=avoid                   # effects a prop likes / avoids (the GUI's effect wheel)
./seqtool.py groups 4.Floods-all --role unit                         # one group's role (auto: back to the guess)
./seqtool.py sections from-timing Beats @#3                          # sections start at an .xsq timing track's marks there
./seqtool.py lyrics time 3.2 41.2 41.65                              # when line 3's second word is sung (the GUI's magnifier: drag it)
./seqtool.py lyrics word 3.2 night                                   # its text (the magnifier: double-click it)
./seqtool.py lyrics shift -0.3 @1:12                                 # every line from 1:12 on, 0.3 s earlier (the magnifier: Shift+drag)
./seqtool.py lyrics starts 3.2 41.2 41.6 42.05                      # words from 3.2 on start at these times (the magnifier: tap marks while playing, then snap)
./seqtool.py lyrics shift +0.2 from 3.2                              # that word and every word after it, 0.2 s later, lengths kept (magnifier: Shift+drag a word)
./seqtool.py lyrics line 3 "silent night"                             # a phrase's text (magnifier: double-click it, or right-click > edit text)
./seqtool.py lyrics split 3 @41.5                                    # one phrase into two at 41.5 s ('lyrics join 3' joins lines 3 and 4; magnifier: right-click a phrase)
./seqtool.py lyrics tidy                                             # words that run into the next one end where it starts
./seqtool.py lyrics voice BOB @3.2                                   # BOB sings from line 3's second word on (or type {BOB} / {ALL} in the lyrics)
./seqtool.py lyrics from-xsq                                         # the lyrics of the .xsq's lyric timing track
./seqtool.py react MegaTree beat @#3                                 # this song, section 3 (and repeats) only; --song: this song only
./seqtool.py promote Wise1R-3D --list                                # the groups it could go to, and why others can't
./seqtool.py sections from-xsq ~/xLights/show/Song.xsq               # the sections an existing sequence shows (--apply: use them)
./seqtool.py xsq-borrow ~/xLights/show/Song.xsq                    # what an existing sequence holds, by section and row
./seqtool.py borrow Arches @#3                                      # ... keep those effects as they are there ('unborrow' gives them back)
./seqtool.py pref scoring.passes.base.members = over                # whole-yard moments on top of the props' own effects (default: cut)
./seqtool.py pref scoring.durations.default.max = "16 bars"         # longer effects before they get one-aspect variations
./seqtool.py run --candidates 5                                     # try 5 seeds, keep the plan the show critic scores best
./seqtool.py explain music @0:37.5                                  # what the analysis heard at that moment
./seqtool.py react Floods beat                                      # props that follow the music ('presets' lists the choices)
./seqtool.py react Arches chorus-beat-chase,beat --over             # first match wins; --over = on top of the normal effects
./seqtool.py rules add '(?i)flood' prefer=color_wash*1.5            # settings by name pattern (rules test PATTERN to try one)
./seqtool.py rules add '(?i)-all$' kind=group group_kind=umbrella   # your naming convention: ...-all groups are umbrella groups
./seqtool.py effects                                                # what each effect type looks like (also: help effects)
./seqtool.py -demo --rgbeffects /path/to/show/xlights_rgbeffects.xml   # synthetic song on your yard
./seqtool.py run --audio song.mp3 --view browser                    # or audacity / none
./seqtool.py prop-wizard my-yard.json                               # build a layout by answering questions
./seqtool.py run --audio song.mp3 --layout my-yard.json
./seqtool.py --install=ask run --audio song.mp3 --stems             # Demucs stems in song-seqtool/stems/: vocals, drums, bass, other
./seqtool.py pref stems = true                                      # use the stems for every song
./seqtool.py react MegaTree melody-fill                             # with stems: the tree fills up and down with the tune
./seqtool.py react Arches snare,kick,hat-sparkle                    # with stems: the drum kit on the arches
./seqtool.py react MegaTree word-flash --words star,night --over        # a flash only on those sung words
./seqtool.py react Spinners spoke-bounce --on word --words star        # any preset's look on any event (here: those words)
./seqtool.py palette ballad 2 --hue 30                              # this song's colours: another style's palette, turned
./seqtool.py sections split 1 @vocals                               # a new section where the singing starts
./seqtool.py batch "pin A @#3 spirals; react B beat --over"         # several changes: one re-plan, one undo step
./seqtool.py feel busy 0.7                                          # creative controls: busy, intensity (per section too), warmth, unison
./seqtool.py direct "make the chorus bigger and warmer"             # plain words, offline: shows what it understood, asks, runs it
./seqtool.py bundle                                                 # settings, layout and song in one .zip (bundle --open FILE unpacks it)
./seqtool.py start                                                  # the start-of-session commands (general.session_start)
./seqtool.py pin Matrix @#1 meteors direction=explode speed=medium-fast   # a pinned effect with settings of yours
./seqtool.py palette colors green,purple,orange --accent blue      # your own colours for this song
./seqtool.py pin Matrix @#2 picture file=pumpkin.gif              # a picture / animated GIF (pinned only)
./seqtool.py define set "left arm wave" --show --for spinners ...  # your terms, at levels; 'define dump' reads them
./seqtool.py pin Spinner1 @#3 pinwheel rotation=10oclock..7oclock..10oclock   # a setting that glides (a value curve)
./seqtool.py adjust Matrix @#1 rotation=180deg..360deg until=@ready --on face   # settings over what plays (a face turning upright)
./seqtool.py score                                                    # the song's score: its terms and every direction, as commands ('score apply FILE' replays it)
./seqtool.py cue tag call @#3 ; ./seqtool.py calls                   # call and response: mark a pair, seqtool finds the rest
./seqtool.py submodel angles "Spinners" --write               # clock-position submodels (seqtool-10oclock ...) in your layout
./seqtool.py pin "All Props" @#3 choreo name="both arms wave"   # a choreography: a definition's --data played on the props inside
./seqtool.py demo --bundle                                          # the demo as a show of its own (xLights files + song) in one .zip
python fseqdump.py Song.fseq --start 1 --count 30 --from 12 --to 14 # stand-alone: what xLights rendered, channels as hex (or --json)
./seqtool.py cue add @1:05.2                                        # your own trigger mark: an extra hit for the reacting props
./seqtool.py cue from-xsq Cues                                      # ... or the marks of a timing track you tapped in xLights
./seqtool.py run --audio song.mp3 --frame-interval 0.025            # any multiple of 0.01 s
./seqtool.py status seqtool-out                                     # which files are stale, and why
./seqtool.py baseline add '../Songs/*.mp3'                            # keep these songs' plans (no song: the current one); change prefs; then:
./seqtool.py baseline diff                                          # every effect choice your change altered
./seqtool.py xlights-kit                                            # teach seqtool your xLights version: one file, check after every save
./seqtool.py xlights-kit --fresh                                    # start the kit over at step 1
./seqtool.py groups                                                  # group roles of the stored layout (top/unit/detail/unused): a guide, then change any by number or name
./seqtool.py groups 1.ALL                                            # what is in one group: its groups, parts, props, and its role
./seqtool.py groups Flood01U                                         # a prop: its groups, the closest first (--all: no "... and N more")
./seqtool.py explain MegaTree @37.5                                  # why MegaTree shows its effect at 37.5 s
./seqtool.py explain MegaTree                                        # its settings: reactions, presets, preferences, rules
./seqtool.py lyrics transcribe                                      # lyrics from the singing (Whisper on the vocal stem; --model medium; 'lyrics models')
./seqtool.py lyrics align words.txt                                 # your lyrics as plain text, timed from the singing
./seqtool.py lyrics align words.txt --report                        # ... and every stretch of your words that wasn't recognised, and why
./seqtool.py lyrics import words.lrc                                # an LRC: lines start where it says, end where the singing stops; words timed by their sounds
./seqtool.py lyrics align words.lrc --times heard                   # ... or the words timed from the transcription (Whisper) instead
./seqtool.py lyrics transcribe --debug                              # also a Whisper log: each segment's confidence, the sung passages it skipped
                                                                    # (--debug also on lyrics align / phonemes, sections, face build)
./seqtool.py lyrics import song.lrc                                  # timed lyrics (LRC or Audacity labels): timing track, lyric presets, sections
./seqtool.py xlights-kit --update                                    # teach only what's new (Fill, VU Meter, submodel rows)
./seqtool.py xlights-export --checks --audio song.mp3               # verification sequence: one labelled slot per feature to look at in xLights
./seqtool.py xlights-export --baseline 2                            # --baseline N also works on explain, pin, reroll, gui, status ... (song N becomes current)
./seqtool.py pin 1.ALL @1:08 color_wash                             # a top group takes over there; 'pin Tree @1:08 dark' blacks out one prop of a group
./seqtool.py face build Matrix pumpkin.png                      # singing face: 10 mouth shapes x eyes open/closed + the faceInfo line for xLights
./seqtool.py face list                                              # faces in your layout ('face format': the format learned from them)
./seqtool.py face use Matrix Showman                            # Matrix sings the lyrics with that face (xLights Faces; --over keeps its other effects)
./seqtool.py face use Matrix Showman @#3                        # ... only in section 3 (singing is the reaction 'sing': 'react PROP sing @#N', the GUI's react menu)
./seqtool.py face use Matrix Bob --voice BOB --area 0,0,50,100       # several faces on one matrix (--add for the next), each singing its voice's words
./seqtool.py lyrics phonemes                                        # the mouth shapes of the words (CMUdict + your seqtool-prefs/pronunciations.dict)
./seqtool.py lyrics phonemes --dictionary my-words.dict             # another add-on dictionary, remembered ('--dictionary default' goes back)
./seqtool.py tutorial faces                                         # walk through lyrics -> phonemes -> a face that sings them
./seqtool.py package                                                # dist/seqtool-X.Y.Z.pyz: one file to share (unpacks itself; upgrades ask about changed files)
./seqtool.py face show Pumpkin                                      # a face's images in the GUI (< >, zoom, mark the mouth / eye pixels, pick colours, touch up)
./seqtool.py face build Matrix pumpkin.png                      # after 'save marks' in the viewer: uses the marks kept in pumpkin.png
./seqtool.py face write pumpkin                                      # put the built face into xlights_rgbeffects.xml (close xLights; a copy goes to seqtool-backups/)
./seqtool.py face remove pumpkin [--xlights]                         # forget a built face (--xlights: also take it out of xlights_rgbeffects.xml)
./seqtool.py expl tree @#3                                           # same, abbreviated; middle of section 3
```

Re-running reuses fresh analysis files and rebuilds stale ones. A file is stale when:
- its source file changed,
- a setting changed,
- it depends on an upstream file that changed, or
- it was made by an older seqtool version.

The `--stale=ask|rebuild|warn` global option controls this. `ask` is the default; it rebuilds when there's no terminal to answer from.

Individual stages are listed by `./seqtool.py --help`; add `-h` to any command for its options.

Global options go before the command:

| option | effect |
|---|---|
| `--quiet` | hide progress messages |
| `--install=ask\|yes\|no` | control optional-package installs |
| `--stale=ask\|rebuild\|warn` | what to do with stale intermediate files |
| `--version` | print the seqtool version |
| `--test` | run the unit tests |

## Your settings

```bash
./seqtool.py pref                         # the preference files (* = you changed something)
./seqtool.py pref min_bars                # look at one value or any group (music.sections, scoring/weights, ...)
./seqtool.py pref min_bars = 12           # change it (stored in your folder only)
./seqtool.py pref changed                 # everything you changed;  pref reset NAME  to undo
./seqtool.py pref edit music              # or edit your music.json in $EDITOR
```


Your choices go to `seqtool-prefs/` in your home folder (`SEQTOOL_PREFS=DIR` or `--preferences DIR` for another); the built-in defaults are never changed:
- **Preference files:** only the keys you changed are stored there.
- **`answers.json`:** remembers your previous answers, which become the next defaults.

Use `--preferences DIR` or `SEQTOOL_PREFS` to put them elsewhere.

## Versioning

The version is in the `VERSION` file:
- **MINOR** is bumped for every major update, which makes older artifacts stale.
- **PATCH** is bumped for fixes that don't change results.

Schema versions are separate (see DESIGN.md §3, §15).

## Status

xLights export works once `xlights-kit` has run for your xLights version: `run --rgbeffects ...` writes `<song>.xsq`, or use `xlights-export --out <folder>`.

Next (DESIGN.md §13e, §13f): node-range singing faces, the top-down base pass with
one-aspect variations and effect duration limits (0.20), style training (0.21).
