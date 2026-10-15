---
name: generate-media
description: Paid AI generation for an episode, cost-gated - ElevenLabs sound effects, voice isolation, text-to-speech, music beds and Scribe word-timed transcripts (strong for Hindi and Indian languages); fal image-to-video to regenerate a glitched shot, upscalers and image generation/editing. When generation is worth paying for, how to prompt it, and how results go back into the pipeline.
---

# Generate media (router)

Generation costs money; the free local pipeline is the default. Every tool asks the user to approve the
cost first (a card in the UI). Never split one request into many small ones to look cheaper.

## When it is worth it
| Problem | Tool | Instead of |
|---|---|---|
| Dialogue with heavy noise/music that `cva mix clean` cannot fix | `el_voice_isolate` | stronger afftdn (sounds watery) |
| A hit, riser, whoosh or ambience the hits pack lacks | `el_sound_effect` | a mismatched stock sound |
| Narration, a pickup line, a dub | `el_tts` | re-shooting |
| User wants a quick bed, not a composed score | `el_music` | the vd score (still the default) |
| No local transcription, or Hindi / regional language | `transcribe_paid` with ALL sources in one call (Scribe v2 via fal or ElevenLabs) | local Whisper |
| A glitch no edit can hide and the line matters | `fal_run` image-to-video from a clean still | cutting the line |
| A punch-in above ~130% looks soft | `fal_run` upscaler on that segment | living with it |
| Title-card background, thumbnail, a cleaned still to regenerate from | `image_generate` / `image_edit` (LiteLLM proxy, `CVA_IMAGE_MODEL`) | stock images |

Check `fal_pricing <endpoint>` and `generation_spend` before proposing; tell the user the price and why.
LiteLLM image calls have no price up front; the proxy-reported cost is recorded in the ledger after each call.

## Prompt craft
- **Sound effects**: name the source, size, space and tail: "single deep orchestral boom, huge hall, long sub tail, no music". Ask for a duration that covers the tail.
- **Risers**: "rising string-and-noise riser, 3 seconds, ends abruptly" - it must end on the cut.
- **TTS**: pass the line exactly; for continuity use the same voice id as earlier pickups; set language_code for Hindi.
- **Shot regeneration (fal image-to-video)**: start from a still just *before* the glitch (`cva media still`), describe only the motion that should happen ("she slowly sits up in bed, camera static"), keep the duration as short as the gap you need, match the aspect ratio. The result is a new source: `vv source add assets/generated/...` and analyse it like any clip.
- Never ask a model to recreate a real person's likeness beyond the footage the user supplied.

## After generating
Every file lands in `assets/generated/` with a `.json` sidecar (prompt, model, cost). Measure it
(`cva media loudness/probe`), level it like any take, and run the QC gate on the version that uses it.
Mention every paid generation and its cost in the version report.
