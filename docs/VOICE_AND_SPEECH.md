# DARWIN Voice and Speech Handoff

Last updated: September 10, 2026

This document contains the current state of DARWIN's microphone, wake-word,
speaker-identification, speech-to-text, text-to-speech, and media-audio-focus
work. It is intended to let a new development chat continue without repeating
the investigation or accidentally deploying a failed model.

## Current status

The normal voice pipeline works, and DARWIN can hold wake-gated spoken
conversations. Wake-word recognition is reasonably responsive in a quiet room,
but it remains unreliable while music is playing. This is the main unresolved
voice problem.

The active wake model is still:

```text
data/models/openwakeword/darwin_v1.onnx
```

The active threshold is configured in `.env` as `DARWIN_WAKE_THRESHOLD`. It was
last tested at `0.20`.

A media-specific candidate was trained and saved as:

```text
data/models/openwakeword/darwin_media_v2.onnx
```

Do **not** make that candidate the default. Its evaluation was:

```text
Media recall:                0.99%
Media false-positive rate:   0.248%
Original-data recall:       76.12%
Original false-positive rate: 2.9%
Recommended threshold:       0.76
```

The detailed report is at:

```text
training/wakeword/outputs/darwin_media_v2/evaluation.json
```

This candidate failed its purpose because almost every wake phrase recorded
over music still scored below a safe threshold. It is an experiment, not a
production model.

## Implemented pipeline

Continuous mode currently follows this sequence:

```text
Persistent microphone
  -> streaming openWakeWord detector
  -> Silero voice activity detection and command recording
  -> Faster Whisper transcription
  -> speaker verification
  -> LangGraph supervisor
  -> Fish Audio streaming speech
  -> short follow-up listening window
```

### Persistent microphone

`src/app/voice/microphone.py` keeps one PortAudio stream open and shares it
between wake detection, command capture, and follow-up capture. This replaced
the earlier design that repeatedly opened and closed the microphone.

It uses 16 kHz mono audio and 80 ms frames. Its bounded queue retains current
audio and drops stale audio if the consumer falls behind. The queue is cleared
after DARWIN finishes speaking so DARWIN does not transcribe its own voice.

DARWIN now also has an Apple-native capture backend under:

```text
native/macos_voice_audio/
```

It enables `AVAudioEngine` voice processing and streams 16 kHz mono signed PCM
to the existing Python microphone contract. This gives the input path Apple's
device-tuned acoustic echo cancellation, noise suppression, and automatic gain
control without changing the wake-word, VAD, or ASR consumers.

Build it once with:

```bash
native/macos_voice_audio/build.sh
```

Select the backend with:

```text
DARWIN_MICROPHONE_BACKEND=auto       # Apple helper when built, else PortAudio
DARWIN_MICROPHONE_BACKEND=apple      # Require Apple voice processing
DARWIN_MICROPHONE_BACKEND=portaudio  # Explicit legacy fallback
DARWIN_APPLE_AUDIO_HELPER=<path>     # Optional binary override
```

The default is `auto`. This integration does not assume that macOS cancels
Spotify or Apple Music from other processes on every device route. That must be
verified with controlled raw-versus-processed recordings before claiming the
music wake-word problem is solved.

Apple VoiceProcessingIO always applies some non-voice ducking. DARWIN selects
Apple's minimum level while listening, suspends the native engine during its
own TTS playback, and resumes it for follow-up capture. This prevents the
always-open voice-processing engine from making DARWIN's voice sound quiet.

### Speech endpointing

`src/app/voice/speech_activity.py` wraps Silero VAD. It is used by
`src/app/voice/speech_to_text.py` to detect the beginning and end of speech.

The recorder includes a short pre-roll so quiet opening phonemes are not lost.
It stops after silence instead of always recording for a fixed duration. This
substantially reduced user-input latency.

Relevant setting:

```text
DARWIN_VAD_THRESHOLD
```

The current default is `0.5`.

### Speech-to-text

`src/app/voice/speech_to_text.py` uses Faster Whisper on the CPU with int8
inference. The current default model is `small.en`.

Relevant setting:

```text
DARWIN_WHISPER_MODEL
```

Observed Whisper inference is normally about 0.4 to 1.4 seconds after
endpointing. Recording time depends on how long the user speaks and how quickly
the VAD recognizes trailing silence.

### Speaker identity

`src/app/voice/speaker_identity.py` uses SpeechBrain's ECAPA VoxCeleb model.
The enrolled Ashish voiceprint is stored locally under:

```text
data/voice_profiles/ashish/
```

Five natural samples are collected by:

```bash
python -m app.voice.enroll
```

The current default verification threshold is `0.30`, configurable through:

```text
SPEAKER_VERIFY_THRESHOLD
```

Speaker verification occasionally rejects Ashish when music contaminates the
captured command. It should not be treated as authorization for sensitive
actions. It is only an attention/filtering signal; the safety confirmation
system must remain separate.

### Wake word

The selected wake word and assistant name are `DARWIN`.

`src/app/voice/openwakeword_detector.py` performs continuous openWakeWord ONNX
inference over 80 ms frames. It reads `.env`, supports a configurable model,
and can print live scores.

Relevant settings:

```text
DARWIN_WAKE_BACKEND=openwakeword
DARWIN_WAKE_MODEL=data/models/openwakeword/darwin_v1.onnx
DARWIN_WAKE_THRESHOLD=0.20
DARWIN_WAKE_WORD_DEBUG=1
```

`DARWIN_WAKE_MODEL` may be omitted to use `darwin_v1.onnx`.

Standalone debug test:
```bash
DARWIN_WAKE_WORD_DEBUG=1 python -m app.voice.streaming_wake_word
```

The earlier personalized MFCC/template detector remains available as an
explicit fallback through `DARWIN_WAKE_BACKEND=personalized`, but it is not the
preferred architecture.

### Text-to-speech

`src/app/voice/text_to_speech.py` uses the Fish Audio API and streams PCM audio
to `sounddevice`. It starts the first sentence immediately and generates later
sentences concurrently. Local `pyttsx3` is the fallback.

Relevant settings:

```text
FISH_API_KEY
FISH_TTS_MODEL
FISH_VOICE_ID
FISH_TTS_SPEED
```

Speed `1.25` sounded best in user testing. The speech cleaner removes Markdown,
list markers, URLs, emoji, and problematic punctuation. It also converts
decimals, Fahrenheit/Celsius symbols, and `mph` into speech-friendly text.

Fish Audio sounds substantially more natural than Kokoro and `pyttsx3` in the
tests performed, but it is a remote API. It adds network latency and sends the
response text to Fish Audio. A production privacy/offline mode still needs a
better local voice option.

### Media audio focus

`src/app/system/audio_focus.py` gradually lowers only active media playback;
DARWIN's own voice is not lowered. It currently supports Spotify and Apple
Music.

Media is ducked only after real user speech begins and while DARWIN is speaking.
Passive wake-word and follow-up listening do not repeatedly lower the music.
The original media volume is restored smoothly afterward.

Relevant settings and defaults:

```text
DARWIN_MEDIA_DUCK_RATIO=0.35
DARWIN_MEDIA_DUCK_MINIMUM=18
DARWIN_MEDIA_FADE_STEPS=8
DARWIN_MEDIA_FADE_STEP_SECONDS=0.04
SPOTIFY_DEVICE_NAME=<local computer device>
```

This behavior feels smooth, but ducking begins only after speech detection.
Therefore it does not help the wake-word model hear the first word over loud
music.

## Wake-word training completed so far

### Synthetic v1 model

The openWakeWord training workspace is under:

```text
training/wakeword/
```

It includes:

- A local openWakeWord checkout.
- A Piper sample generator and LibriTTS voice model.
- Approximately 30,000 positive training clips.
- Approximately 5,000 positive test clips.
- Approximately 30,000 adversarial negative training clips.
- Approximately 5,000 adversarial negative test clips.
- MIT room impulse responses.
- MUSAN noise/background audio.
- The 16 GB precomputed ACAV100M feature dataset.
- The 176 MB openWakeWord validation feature dataset.

The Piper pronunciation that sounded correct was `dar_vin` with a length scale
of `1.15`. Faster variants sounded like “Davin” and were rejected.

The final v1 training run reported approximately:

```text
Accuracy:                 0.7633
Recall:                   0.5284
False positives per hour: 0.2655
```

The PyTorch training environment is the separate Conda environment:

```text
darwin-wakeword
```

Compatibility changes required during training included:

- Python 3.11
- NumPy 2.2.6
- SciPy 1.13.1
- `setuptools<81`
- `onnxscript` for ONNX export
- DataLoader workers set to zero on macOS to avoid lambda pickling errors
- Saving/loading a state dictionary because the local model class itself is
  not pickleable

### Quiet-room results

At threshold `0.20`, the wake word became noticeably smoother and produced zero
false activations during one five-minute room-noise test. Earlier controlled
tests also produced strong clean-speech scores, frequently between roughly
`0.55` and `0.95`.

These observations are useful but are not a sufficient production evaluation.
There is no finalized, repeatable long-duration false-acceptance test yet.

### Music-playback failure

With Spotify playing at normal volume, the user said `DARWIN` approximately 20
times and received only about three detections. The successful scores included
`0.763`, `0.760`, and `0.373`; most misses stayed near `0.001`.

This proves the main problem is not merely threshold selection. Lowering the
threshold cannot recover examples that score around `0.001`, and doing so would
increase false activations.

The original openWakeWord background set contained general noise but not enough
representative music. The model did not learn to separate Ashish saying DARWIN
from foreground vocals and music.

### Personalized media dataset

The following real dataset was recorded while Spotify played at normal volume:

```text
data/voice_profiles/ashish/darwin_media/20260910_175036/
```

It contains:

- 12 positive recordings of Ashish saying `DARWIN` over music.
- 8 negative recordings of Ashish saying ordinary commands over music.
- 8 music-only negative recordings.

The v1 model detected only 2 of the 12 positive recordings at useful scores.
Its negative recordings remained near `0.001`, confirming that the failure is
mostly false rejection caused by masking, not a threshold problem.

### Media v2 experiment

The fine-tuning implementation is split into:

```text
training/wakeword/media_finetune/data.py
training/wakeword/media_finetune/train.py
```

It:

- Mixes existing synthetic positive and adversarial speech with recorded music
  at multiple signal-to-noise ratios.
- Adds the real media enrollment recordings.
- Retains original v1 features to reduce catastrophic forgetting.
- Uses MPS when available.
- Caches every expensive feature set.
- Saves an epoch resume checkpoint.
- Exports a candidate without automatically changing the active v1 model.

The run completed, but the evaluation above shows that v2 collapsed on the
media-positive validation data. Do not rerun it unchanged and do not activate
it.

## Known issues

1. Wake-word recall during music playback is still unacceptable.
2. There is no acoustic echo cancellation. Siri/Alexa-class barge-in normally
   relies on an audio playback reference plus echo cancellation, microphone
   arrays and device-specific signal processing. Training alone may not solve
   this on a laptop microphone.
3. The media enrollment dataset is too small and contains only one short
   session. Training and validation share a narrow acoustic environment.
4. Speaker identity becomes unreliable when music leaks into command audio.
5. Clean-room and media metrics are not yet produced by one reproducible
   evaluation harness.
6. False accepts must be measured over hours of ordinary speech, television,
   music and room noise—not only a five-minute manual test.
7. Follow-up listening is time-based. It does not yet use dialogue state or
   intent to decide whether DARWIN should continue listening.
8. Fish Audio requires the network and shares generated response text with the
   provider.
9. Microphone, location, Automation, Accessibility and media permissions need
   a proper first-run installer/permission flow.

## Recommended next work

Proceed in this order:

1. Build a deterministic wake-word evaluation command that compares v1 and
   candidates over separate clean-positive, media-positive, ordinary-speech,
   music-only and long ambient datasets. Report recall, precision, ROC/PR
   curves, per-condition recall, and false accepts per hour.
2. Inspect complete v1/v2 score distributions and training loss before changing
   the model. Determine why the v2 positive-media scores collapsed.
3. Record multiple media sessions with different songs, volumes, microphone
   distances and speaking styles. Keep speakers/songs or recording sessions
   strictly separated between training and validation.
4. Correct the augmentation/training recipe and run a small controlled
   experiment before another full fine-tune. Reject candidates automatically if
   either clean recall or false-accept performance regresses.
5. Investigate real acoustic echo cancellation using a playback reference
   (WebRTC AEC or macOS VoiceProcessingIO). This is the most promising path to
   reliable barge-in while DARWIN or Spotify is playing audio.
6. Re-evaluate speaker identity after AEC. Do not lower its threshold blindly.
7. Add end-to-end latency telemetry for wake detection, endpointing,
   transcription, first LLM token, first audio and playback completion.
8. Only after the candidate passes the evaluation gate, configure
   `DARWIN_WAKE_MODEL` to use it and run long-duration soak tests.

## Important operating commands

Run DARWIN:

```bash
python main.py
```

Test the active streaming wake model with scores:

```bash
DARWIN_WAKE_WORD_DEBUG=1 python -m app.voice.streaming_wake_word
```

Enroll the speaker profile again:

```bash
python -m app.voice.enroll
```

Record another media wake-word session:

```bash
python -m app.voice.enroll_media_wake_word
```

Run voice-related tests:

```bash
pytest -q \
  tests/test_microphone.py \
  tests/test_openwakeword_detector.py \
  tests/test_personalized_wake_word.py \
  tests/test_speech_activity.py \
  tests/test_speech_gate.py \
  tests/test_wake_word.py
```

Temporarily test a candidate without changing `.env`:

```bash
DARWIN_WAKE_MODEL=data/models/openwakeword/darwin_media_v2.onnx \
DARWIN_WAKE_THRESHOLD=0.76 \
DARWIN_WAKE_WORD_DEBUG=1 \
python -m app.voice.streaming_wake_word
```

The current v2 metrics are poor, so this command is for diagnosis only.

## Files a new chat should read first

```text
docs/VOICE_AND_SPEECH.md
src/app/voice/conversation.py
src/app/voice/microphone.py
src/app/voice/openwakeword_detector.py
src/app/voice/speech_activity.py
src/app/voice/speech_to_text.py
src/app/voice/speaker_identity.py
src/app/voice/text_to_speech.py
src/app/system/audio_focus.py
training/wakeword/media_finetune/data.py
training/wakeword/media_finetune/train.py
training/wakeword/outputs/darwin_media_v2/evaluation.json
```

## Guardrails for the next chat

- Do not overwrite `darwin_v1.onnx` until a candidate passes measurable gates.
- Do not rerun the existing media-v2 recipe unchanged; it already failed.
- Do not solve media misses only by lowering the threshold.
- Do not use speaker identity as authorization for sensitive actions.
- Keep training artifacts and heavyweight dependencies out of the main DARWIN
  runtime environment.
- Never commit API keys from `.env`.
- Make changes in small, testable stages and report measured results rather than
  subjective impressions alone.
