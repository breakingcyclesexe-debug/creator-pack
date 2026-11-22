# Finding the story in someone's takes

> Mirrors dump-to-script step 3; change both together. The rules between the sync markers are that step's rules in generic words, and `tests/test_story_sync.py` fails when that step gains or changes a rule this copy hasn't taken in.

People who talk to camera without a script circle their point: they warm up, restart, say the good line on the third try, wander, and land the real point near the end. Your job is to find the story they were trying to tell and lay it out as beats, using only what they actually said.

<!-- sync:dump-to-script-step3 start -->
## The story rules

Find the story in the creator's own words before any line is written. Inputs: the transcript (`CPACK transcript PID`), and from `CPACK project PID` what the piece is made for (`purpose`), the length, the mode and the script if there is one. Use only those; nothing about one creator is written into these rules. Output the whole storyboard JSON (below), in full, never a summary paragraph.

1. **Read all of it, then find the moment of change.** Note the point they most want across (often said late, or twice), every repeat, the warm-up. Write `trying_to_tell`: "What are they trying to tell here, in their words?" and check every cut against it. The ending is the change; the beginning is its opposite.
2. **First gate.** One sentence: after this, the viewer can ___ (`first_gate`). No answer, no arc.
3. **Hook = the viewer's problem** or the question they would type into search, never the creator's situation or an update. Give 2-3 search phrasings with it (`hook.search`). It comes from what the creator says the piece is for.
4. **Shape:** the one the material already has. Never force one; never ask for a low point the shape doesn't need.

| shape (key) | fits when | beats |
|---|---|---|
| `turn` | something happened and changed | hook, setup, turn (+ after-feeling), what it means, close |
| `setback` | it really went wrong | normal, the low, what they did, a bit better, close |
| `belief` (belief then break) | they were sure, then wrong | belief, backed it, break, turn, close |
| `opinion` | against the common view | what everyone says, why not (their proof), what they do instead |
| `beforeafter` (before / after) | then and now | before, the change, after, close |
| `tips` | several points | strongest first, surprising last, each says why it belongs |
| `qa` (Q&A) | a question they answer | question, why people get it wrong, answer, proof |
| `rant` | pushing back | the claim, what's wrong, the real point, what to do |

5. **2-3 competing arcs** (`arcs`), each a different way in and a different shape. If the creator named an angle (in `purpose` or the chat), one arc builds it as given. Per arc: way in (`way_in`); shape; hook + search phrasing; 2-3 openings (their line, its take and start, what's on screen at 0 s); **beats named first** (`label`), then one line per beat, quoted exactly with its source (take + start seconds), never invented, fixed or stitched; plant -> payoff (`plants` / `pays_off` name the other beat's id); the after-feeling only where they already said one (never ask for it: if they didn't say how it felt, `after_feeling` is `{"line": null, "missing": true}` and that is fine); the ending (a real beat, never a moral or summary); the open thread, the reason to follow (`open_thread`); the missing beat as ONE plain question (`missing_question`), who and when named, never a made-up person stacked with a date and the ask. Per point pick one telling (the clearest, usually the last), whole sentences only, and list what was left out with a plain reason (`left_out`).
6. **A product, feature or offer is the payoff of the story, never the story:** last third only, at most 3 features, in their words.
7. **Scored by a separate judge that wrote none of the arcs.** Start a fresh subagent (the Agent tool) and give it only the transcript, the purpose and the arcs; it never sees your reasoning. It scores each arc 0-10 on six things, out of 60: `hook` (viewer's problem, stops a stranger), `arc_turn` (clear change, after-feeling, plants pay off), `own_lines` (strong, exact, sourced), `stranger` (the stranger test: someone with zero context follows it and knows whose life it is), `goal_fit` (first gate, what the piece is for, product kept to the payoff), `missing` (10 = nothing missing). One line of why per arc, a winner, a tie goes to fewer missing lines (the higher `missing` score). Put it in `score` with `by` naming the judge. Then a cold judge reads the winner top to bottom as a stranger (PASS / FIX / FLAG; FIX means fix and score again), then you do.
8. **Then stop.** The page shows the creator the winning arc as beats (hook, each beat in one plain line, ending); the other arcs stay in `arcs`, one line each; the winner's one missing-beat question goes in `question`. Nothing gets cut until the creator OKs it on the page. Their changes come back as a change job and go back to these rules, not into your own rewrite.

### The hook bank (ways in)
Use it to make the 2-3 openings and arcs really different ways in. Every example must be the creator's own line from this transcript; the bank only names the shape.

| way in | what the line does |
|---|---|
| Who they are, one breath | their situation in one line, then straight to the problem |
| What they decided | the decision, said plainly |
| Owning it | an admission, with the reason right behind it |
| The feeling the viewer has | the viewer's feeling first, a fact about the creator next |
| Outside vs inside | how it looks from outside against what it is |
| The number | a real figure they said |
| In the middle of it | open inside the moment, explain after |
| What someone said | a line someone said to them |
| Talking to one person | "to the people who..." |
| The list | "one thing I wish I knew..." |
| What nobody tells you | the part people skip |
| The clock | a real deadline they said |
| A question for you | a question put to the viewer |

Never open on a line that already opened one of their posts (when they mention it), and never on the same fact as a recent piece.

**Every line is the creator's own words.** You choose and order; you never write, tidy or stitch a line for them. A beat they never said becomes `missing_question`, not a line.
<!-- sync:dump-to-script-step3 end -->

## Modes
- `find` (default): arrange the beats in the order that tells the story best. Reordering is expected. 2-3 arcs.
- `keep`: keep the beats in the order they were said. Still pick the best tellings and leave things out, still label the shape. Arcs may differ only in where they start and end and what they leave out; one arc is allowed. Put reorder ideas in `advice` only ("Your line at 04:12 would open stronger").
- `script`: the user filmed from a script (shown in `CPACK project PID`). One beat per script line, in script order, using the best take of that line (the most complete, fewest restarts; usually the last). Label beats "Line 1", "Line 2"... A script line nobody said goes in `left_out` with why "not found in the takes". One arc is enough.

## Choosing the lines
- **One telling per point.** When a point is said several times, pick the clearest complete telling (usually the last full one) and put the other tellings in that beat's `alts`.
- **Complete thoughts only.** A beat starts at the start of a sentence and ends at the end of one. Never end on "and", "but", "so", "because".
- **Length:** for Instagram aim for 30 seconds to 3 minutes of beats (Instagram only recommends reels up to 3 minutes to non-followers). For YouTube there's no cap; keep everything that earns its place.
- **Leave out** warm-up, side stories that don't serve the point, repeated points, and anything that would confuse a stranger. Every left-out stretch longer than a sentence goes in `left_out` with a short, plain reason ("warm-up before the point", "said again better at 3:10").
- **Quote exactly.** `line` is the words as said, in order, from the transcript. You may leave out an "um" or "uh"; don't add, swap or fix words. The save step finds every line (beats, openings, an after-feeling) in the take and rejects anything it can't find. The cut itself removes fillers, restarts and repeated phrases inside each beat.

## One line and advice
- `one_line`: the winner's story in one plain sentence a friend would say.
- `short_title`: 3 to 6 words that name this video in the buyer's list of videos, from their own words ("Quit and drove out of Hong Kong"). No full stop.
- `advice`: up to 3 short, specific tips, e.g. a stronger hook found later in the take, a missing close. No generic advice.

## The JSON
The top-level `beats` are the winner's beats (what the page shows and the cut uses); leave them out and the save step copies them from the winning arc. `shape` defaults to the winner's shape and `shape_alts` to the other arcs' shapes.

```json
{"mode": "find", "one_line": "", "trying_to_tell": "",
 "arcs": [{"id": "A", "way_in": "", "shape": "turn", "first_gate": "after this, the viewer can ...",
   "hook": {"problem": "", "search": ["", ""]},
   "openings": [{"line": "words as said", "take": "TAKE.MOV", "start": 12.3, "on_screen": ""}],
   "beats": [{"id": "b1", "label": "Hook", "line": "words as said", "take": "TAKE.MOV", "start": 12.3, "plants": "b4", "pays_off": null,
              "alts": [{"take": "TAKE.MOV", "line": "the same point said another time", "start": 80.2}]}],
   "after_feeling": {"line": null, "missing": true}, "ending": "", "open_thread": "",
   "missing_question": "", "left_out": [{"line": "", "take": "TAKE.MOV", "start": 40.1, "end": 52.0, "why": ""}]}],
 "score": {"by": "a judge subagent that wrote none of the arcs",
           "A": {"hook": 0, "arc_turn": 0, "own_lines": 0, "stranger": 0, "goal_fit": 0, "missing": 0, "total": 0, "why": ""}},
 "winner": "A", "question": "the winner's one missing-beat question",
 "advice": [""], "left_out": []}
```
