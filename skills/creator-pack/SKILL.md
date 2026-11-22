---
name: creator-pack
description: Opens the Creator Pack Editor page on this Mac (footage, story, look, cut, export) and then works the jobs the page sends - building the storyboard from the speaker's own words, making change requests on a cut, answering the video's chat. Use when the user types /creator-pack, says "open the creator pack", "edit my video", "cut my takes", or when the page says it is waiting for Claude Code.
---

# Creator Pack Editor (beta)

The page does the mechanical work itself (setup check, transcribing, cutting, captions, rendering, checks). You do the judgement: the story, changes, and chat. The page and you talk through job files; you never need the browser.

`CPACK` below means the pack's launcher: `"${CLAUDE_PLUGIN_ROOT}/bin/cpack"`, which is `bin/cpack` two folders up from this skill's base directory. Quote the path (it can have spaces). Run every command with the Bash tool. The first run sets up the pack's Python helpers (about 30 seconds).

## 1. Open the page
Run `CPACK start`. It starts the local page (127.0.0.1 only) if it isn't running and opens it in the browser. Tell the user in one line: the page is open at the printed address, add footage there, and press Go; you will pick up the story when it is ready.

## 2. Work the jobs, in a loop
Run `CPACK jobs next --wait 540` in the foreground (never in the background, never with `&`; it returns by itself within 9 minutes). It prints one job as JSON with a `what_to_do` line, or `{"none": true}`.
- `none`: run it again straight away. Say nothing to the user unless they ask. An empty wait costs almost nothing, so keep going: the user may come back hours later with a new video. Stop looping only when the user asks you to, or after 60 empty waits in a row (about 9 hours). Then tell them, in these plain words: "I stopped listening for the Creator Pack Editor after a long quiet spell. When you want me again, send /creator-pack here in Claude Code." Never mention terminals or windows.
- A job: do it (sections 3 to 5), finish it with `CPACK jobs done ID --reply "<one or two plain sentences for the user>"`, then go back to the loop.
- If a job fails, `CPACK jobs done ID --failed --reply "<what went wrong, in plain words>"`.

## 3. Story job (type "story")
1. Read [story-method.md](story-method.md) in this folder before every storyboard and follow its story rules in order: moment of change first, 2-3 competing arcs, scored by a separate judge subagent that wrote none of them, then the winner.
2. `CPACK project PID` shows the mode (`find`, `keep`, `script`, and the script text for script mode), what it's made for (`purpose`) and the length asked for (`length`: short = up to 1 min on Instagram or under 3 on YouTube, mid = up to 3 min on Instagram or 3 to 8 on YouTube, long or auto = as long as it needs). `CPACK transcript PID` prints the transcript, one line per sentence with start and end seconds.
3. Write the storyboard JSON (the full shape with `arcs`, `score`, `winner` and `question` is at the end of story-method.md; the short shape below still saves) to a file in the system temp folder, then `CPACK storyboard save PID FILE`. It checks every line against the transcript. If it says NOT SAVED, fix exactly what it lists and save again. Never change the speaker's words to make a line pass; pick a different stretch instead.
4. Done reply: the story in one line and how many beats, e.g. "Your story: <one line>. 7 beats, ready to check." If the winner has a missing beat, add its one question in plain words.

```json
{"mode": "find", "shape": "turn", "shape_alts": ["tips", "rant"],
 "one_line": "The story in one plain sentence",
 "advice": ["Your strongest hook is at 04:12, try it first"],
 "beats": [{"id": "b1", "label": "Hook", "line": "words exactly as said", "take": "TAKE.MOV", "start": 12.3, "end": 18.9,
            "alts": [{"take": "TAKE.MOV", "line": "the same point said another time", "start": 80.2, "end": 86.0}]}],
 "left_out": [{"line": "what was cut, short", "take": "TAKE.MOV", "start": 40.1, "end": 52.0, "why": "plain reason"}]}
```
`take` is the take's name as the transcript header shows it. `start` is where the line starts (from the transcript times); `end` is optional. `alts` are other tellings of the same beat the user can swap in (only when the take really has them).

## 4. Change job (type "change")
The user watched the cut and asked for something. `CPACK project PID` shows the storyboard (beats with ids, keep, order), the settings and the last QA.
- Story changes (drop, move, swap a beat, use a different line): write the edited storyboard and `CPACK storyboard save PID FILE`. Saving resets approval; that is fine for a change job.
- Cut feel (more room after sentences, tighter, keep pauses, keep fillers): `CPACK settings PID '{"cut": {"breath": "relaxed"}}'`. Keys: cut.breath tight|normal|relaxed, cut.fillers, cut.pauses, cut.repeats (true/false), captions.style word|three|lines|none, captions.size s|m|l, captions.position top|middle|bottom, captions.color / captions.pop "#rrggbb", format 9:16|16:9|4:5|1:1|source, fit crop|pad (pad = show it all with a soft blur). Turning is per clip: `CPACK turn PID CLIP 0|90|180|270`.
- Then `CPACK render PID --note "<what changed>"` (about a minute) and reply with what changed and the QA line it printed, in plain words.
- If the request can't be done in this version (music, titles, animations, a different font), say so plainly and suggest finishing it by hand in an editing app.

## 4b. Fit job (type "fit")
The buyer added clips to a video that already has a story and chose to keep it. The job's `clips` lists the new clips (already transcribed). Keep the current storyboard: every part, order and choice the buyer made stays. Place the new clips' best lines into it, as a new part where it tells the story better or as another try (`alts`) of a part it repeats. Save with `CPACK storyboard save PID FILE` (it becomes a new story version; the old one is kept) and reply in one line with what you added.

## 5. Chat job (type "chat")
Answer the question in one to three plain sentences. If it is really a change request, do section 4.

## Rules
- Only the speaker's own words, ever. Never write a line for them, never tidy their words in a beat's line; the cut uses what they said.
- Plain words to the user: no file names, job ids or JSON in replies.
- Nothing leaves the Mac: don't upload footage or transcripts anywhere.
