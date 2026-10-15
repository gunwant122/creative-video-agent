# Orchestra ranges (sounding pitch, MIDI note numbers, C4 = 60)

Stay inside the **comfortable** range by default; the full range is for effect and often sounds worse in sample libraries.

| Instrument | Full range | Comfortable | Notes |
|---|---|---|---|
| Violin | G3-E7 (55-100) | G3-A6 (55-93) | Above A6 thin; great for high sustains over dialogue |
| Viola | C3-E6 (48-88) | C3-A5 (48-81) | Warm mid; often doubles melody an octave down |
| Cello | C2-A5 (36-81) | C2-E5 (36-76) | Lyrical melody around A3-A4; ostinati below C3 |
| Contrabass | E1-G4 (28-67) | E1-D3 (28-50) | Sounds an octave below written; foundation only |
| Harp | C1-G7 (24-103) | C2-C7 (36-96) | Arpeggios; mid-low strings ring longest |
| Horn | B1-F5 (35-77) | F2-F5 (41-77) | Heroic F3-F5; soft low notes for warmth |
| Trumpet | F#3-D6 (54-86) | C4-C6 (60-84) | Bright; fanfares, sparingly |
| Trombone | E2-F5 (40-77) | A2-F4 (45-65) | Weight and menace |
| Tuba | D1-F4 (26-65) | F1-C4 (29-60) | Doubling basses for power |
| Timpani | D2-A3 (38-57) | D2-A3 | Tune to tonic and dominant (D and A in D minor) |
| Tubular bells | C4-F5 (60-77) | C4-F5 | Tolling; one note can be enough |
| Glockenspiel | G5-C8 (79-108) | G5-C8 | Sparkle; sounds 2 octaves above written |

Sample-library notes:
- Check which notes each SFZ actually maps (`<region>` / `lokey`/`hikey` in the file) - notes outside play nothing.
- Velocity often selects the sample layer (soft/medium/loud). Read the SFZ's `lovel`/`hivel` values to see where its layers switch, and write dynamics as velocity. Some sustained patches are single-layer and use CC1/CC11 for swells instead: check for `amplitude_oncc`/`volume_oncc` opcodes.
