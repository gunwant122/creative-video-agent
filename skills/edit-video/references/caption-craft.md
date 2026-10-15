# Caption craft

Captions are built from the word-timed transcript: `vv overlay captions` turns the render's timeline words into styled cards on the overlay track (Hindi/Devanagari supported). For animated word-pop styles use Remotion (`motion-graphics` skill).

## Text
- Fix transcript errors first, especially names. Ask the user for spellings you cannot verify.
- Max 2 lines, ~32 characters per line for 9:16; ~42 for 16:9.
- Break lines at phrase boundaries, never between an article and its noun.
- Each caption is on screen >= 0.8 s and no longer than the speech plus ~0.3 s.
- Social "word pop" style: 1-4 words per card, timed to word onsets.

## Placement (9:16, 1080x1920)
- Keep text clear of platform UI: top ~220 px, bottom ~420 px, right ~150 px.
- Default vertical position: just below centre to lower third (around y = 1150-1350).
- Avoid covering faces and mouths; move the caption for that shot if needed.

## Style
- Bold sans, 56-72 px at 1080 width, white with a dark stroke or soft shadow; never thin fonts.
- One highlight colour max for the active word.

## Timing changes
Captions are timed to the cut. Any re-cut means regenerating captions from the new edit - list it in `notes.md`.
