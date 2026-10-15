# Underscoring dialogue

The voice wins. Music under speech supports mood without competing for the same space.

## Keep out of the voice's range
- Speech fundamentals sit around 85-255 Hz; intelligibility lives at **1-4 kHz**.
- Under lines, avoid melody and busy figures between roughly **C4 and C6** (MIDI 60-84) - that register masks consonants and draws attention.
- Use: low sustained notes (cello/bass, below C3), high soft sustains (violins above C6, harmonics), slow-moving chords.
- Save the melody for gaps between lines and for silent "feature" moments.

## Density and motion
- Under speech: whole notes and long tones, slow harmonic rhythm (one chord every 1-2 bars or slower), no rhythmic figures in the mid range.
- Avoid entrances and big changes on top of a line. Make changes in the breaths between sentences (use `speech_regions`).
- Pizzicato/ostinato under speech only if low or soft and narrow in range.

## Dynamics
- Write at pp-mp (MIDI velocity ~30-70) under speech; let `mix-audio` add the 8 dB duck on top.
- Swell into gaps, back off before the next line - shape it in the notes, don't rely only on the duck.

## Check
Read the MIDI back: list every note overlapping a speech region whose pitch is between 60 and 84 and velocity > 70. That list should be empty or justified.
