# Edit craft

## Assembly
- Establish story order from the transcript and visuals, not filenames. Confirm it with the user if it is ambiguous.
- First pass: lay everything in order, trim only obvious dead air at heads and tails. Watch the whole thing (via frame sheets) before refining.
- Trim heads to ~4-8 frames before the first meaningful motion or word; tails to ~8-12 frames after the last.

## Pacing
- Short-form social: something should change every 2-4 s (cut, punch-in, text, camera move).
- Keep a long silent moment when it is the emotional beat (a rise, a reveal, a reaction) - and give it to the music. Do not trim silence just because it is silence.
- Cut a line's pause only if the pause is not doing work. Hesitation before a confession is content.

## Cut types
- **Hard cut** - the default. Cut on action (mid-movement) to hide the join.
- **J-cut** - next shot's audio starts before its picture. Pulls the viewer forward; good into a new speaker or scene.
- **L-cut** - current audio continues over the next picture. Good for reactions, and for hiding a picture glitch while keeping the line.
- **Punch-in** - scale 110-120% on the same shot to hide a jump cut or crop out a fault. On 1080-wide sources keep it <= 120%; beyond that softness shows. Use `vv punch set` (static) or `vv punch key` (animated push-in); split the clip first if only part of it needs the punch.
- **Cutaway** - insert a different shot over continuing audio. The cleanest glitch fix if a usable shot exists.

## Hiding problems without losing words
- **Morph cut** - a 4-frame dissolve across a small jump (after removing a pause or bad frames) reads as continuous motion, not a jump cut.
- **Cut in the pauses** - take frames out of a silence (e.g. 0.75 s after a line) to remove a morph without touching any words.
- **Start a shot late** - if a shot opens on a melting door or settling artefacts, trim the head until the picture is clean and the action is already under way.
- **Punch-in on action** - a punch-in that lands while someone moves reads as a motivated push-in, and can frame a fault out (up to ~135% if the source is sharp).
- **Cutaway over a line** - `vv clip cover` keeps the line running over a listener's shot while the faulty frames disappear.
- **Hard cut where a dissolve would expose glitch frames** - a dissolve shows both sides; check the handles are clean before choosing one.

## Transitions
- Default is no transition. Every dissolve must earn its place.
- **Dissolve (8-16 frames)** - within a scene, to soften a time skip or hide a fault.
- **Dip to black (12-24 frames total)** - between scenes or acts; marks a change of place or time.
- Match audio: dissolve picture -> crossfade audio over the same length; dip to black -> fade audio out and in, or let the score carry across.
- Never stack two transitions back to back.

## Continuity checks
- Screen direction, eyelines and a character's appearance across cuts (AI clips often drift: hair, clothing, props).
- Same-scene clips should match in colour and loudness. If not, note it for `mix-audio` or a colour pass.

## Versioning
- v1 = assembly, v2 = refined cut + sound, v3 = fixes after review. Write what changed in `notes.md`.
- When the cut changes, anything timed to it (score hits, captions, overlays) must be retimed - list them in the notes.
