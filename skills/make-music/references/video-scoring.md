# Scoring to picture

## Sync rules
- **Hit structural cuts, not every cut.** Scene changes, reveals and act breaks get a hit; ordinary coverage cuts do not. Over-hitting feels like a cartoon ("mickey-mousing").
- **Impacts start ON the cut** (the transient at exactly the cut frame, +-1 frame).
- **Risers END on the cut** - they build into it and stop dead or resolve into the impact. Typical length 1.5-4 s.
- **Swells** (cymbal swell, reverse cymbal) peak on the cut; start them 1-3 s early.
- Dips to black: let the music decay through the black, or land a soft hit as the new scene appears.
- A key change or new section should start on a scene cut, not in the middle of a line.

## Tempo and grid
- Pick a tempo where important cuts fall near beats. With cut times known, test candidate BPMs (e.g. 60-120) and choose the one minimising the distance between key cuts and beat/bar positions.
- Where they still don't line up, compose in free time for that section (sustained pads, no pulse) and place hits by absolute time. Pulse is not mandatory.
- Tempo changes at scene boundaries are fine and often good.

## Cue sheet discipline
Every hit and riser in the score must reference a cue sheet entry. After rendering, read the MIDI back and list `cue time | hit time | error (ms)`; all structural hits within +-20 ms.

## Percussion palette for structure
| Sound | Use |
|---|---|
| Timpani roll -> hit | Build and land a scene change |
| Bass drum / "boom" | Weight on a cut, an ending |
| Cymbal crash | Bright accent; use sparingly |
| Cymbal swell | Into a cut or reveal |
| Tubular bell | Church, tolling, fate, time |
| Low brass stab | Threat, authority, council |

## Escalation
Hold back the earlier hits (layer fewer sounds, -6 to -3 dB) so the final structural hit is the biggest -
layer timpani, a deep boom and cymbals there. `vd check` warns if an earlier impact is louder than the last.

## Silence
Silence is a choice. **Dry air before a key line**: drop the music completely for a beat so a line like
"Tell me everything. Now." lands in silence - mark it with `vd cue add <name> --t <s> --dry` and `vd check` keeps notes out.
One or two seconds of nothing before a big moment makes the moment land. Do not fill every second.
