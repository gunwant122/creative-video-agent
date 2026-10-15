# Speech edits

Use the word-timed transcript from `analyze-media` (`analysis/<clip>.words.json`). Never guess cut points by ear or by waveform alone.

## Cut padding around words
| Edge | Padding | Why |
|---|---|---|
| Before first word of a line | 80-150 ms | Keep the onset consonant and the in-breath feel |
| After last word of a line | 150-300 ms | Keep the decay; tighter sounds clipped |
| Between kept phrases (pause removal) | leave 150-350 ms of gap | Below ~120 ms speech sounds machine-spliced |

Word timings from Whisper-family models can be off by 50-100 ms. Before committing a cut, check the waveform level (see `analyze-media`) in a 200 ms window around the boundary and move the cut to the quietest point that does not clip a word.

## Removing pauses and fillers
- Only remove fillers ("um", "uh", false starts) if the user asked, or the piece is informational. In drama, hesitations are performance - leave them.
- Remove a pause by cutting both picture and audio, then cover the picture jump with a punch-in, cutaway or L-cut.
- Add a 10-20 ms audio crossfade at every speech splice.

## Room tone
- If a cut leaves a hole in the ambience, fill it with room tone taken from a silent stretch of the same clip (loop it with crossfades), at the same level.

## Story edits from transcript
- Build a paper edit first: a list of `{clip, start_word, end_word, why}` in `work/paper-edit.json`. Review it against the story before touching the timeline.
- Map word indices to times only when building the timeline, so the paper edit stays readable.
