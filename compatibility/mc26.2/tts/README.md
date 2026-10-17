# Experimental phoneme intercom

40 generated English speech sounds: the 39 CMU/ARPABET phones plus unstressed
schwa `AX`. These are phonemes, not spoken alphabet letter names. The pack assets
are about 193 KB in total. This small bank deliberately sounds robotic; isolated
phones lack the transitions, stress, and rhythm of a complete speech synthesizer.

`preview-intercom.wav` and `.ogg` demonstrate the actual exported clips spliced
at the same 20-tick-per-second onset schedule as the DiamondFire queue:
“Attention. Reactor temperature critical.” No whole-word recording substitutes
for this preview.

## On-plot contract

`manifest.json` contains all sound event IDs, asset paths, and timing. Events are
`star_program:tts.aa` through the lower-case ARPABET names. `ticks` is the delay
before starting the next phoneme at pitch 1.0. `durationMs` includes a short room
tail, so adjacent clips deliberately overlap. Word and sentence pauses belong to
the plot queue, not to the audio files. Sound events contain a single, non-streamed
mono Vorbis asset each.

The DSP uses a 240–4100 Hz voice band, a subtle saturator, and four quiet early
reflections extending up to 103 ms. The total tail is 130 ms. This gives a small
intercom ambience without washing out consonants. There is no background hiss.

## Regenerate locally

Dependencies: Python 3 with NumPy; eSpeak NG 1.52.0 shared library and its data;
libsndfile with Ogg/Vorbis support. No cloud API, account, API key, microphone,
game connection, or global installation is used.

1. Download the official Windows MSI to `vendor/espeak-ng-1.52.0.msi` from
   <https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi>.
   SHA-256: `7f673c709ea5dd579d3b5ebb98688cc575328a6ab7438d2bc405b88cedaeafb9`.
2. Run `python extract_espeak.py`. It reads the MSI and extracts its CAB and
   authored directory paths locally. It never runs the MSI installer.
3. Run `python build_audio.py --sndfile "C:\Program Files\Audacity\sndfile.dll"`.
   The default uses the already installed Audacity DLL. `--espeak` selects the
   directory containing `libespeak-ng.dll` and `espeak-ng-data`.

To refresh only the preview from the existing OGG bank, run
`python build_audio.py --preview-only --config path/to/tts.json`. The default
preview config is `game/config/tts.json` in the project, or adjacent
`pronunciations.json` in a published source bundle. The preview uses that file's
dictionary, word/sentence pauses, and playback volume. It includes the word gap
after each word, including before sentence punctuation, exactly as the plot does.

`build_audio.py` calls the DLL in synchronous audio-retrieval mode and explicitly
provides its data path. It never starts `espeak-ng.exe` or plays sound through the
computer speakers. Windows error dialogs are suppressed for the native library.

Vowels use forced eSpeak phoneme input. Consonants use the onset of a neutral
schwa carrier, cut at eSpeak's phoneme event boundary with 8 ms of transition;
this retains otherwise silent plosive releases. The waveform is cropped, gently
normalized, fitted to the nearest 50 ms for game timing, processed, and encoded.
All outputs are decoded again to check sample rate, channel count, finite samples,
audible RMS, and clipping. Ogg stream serials/CRCs are normalized for reproducible
output. The script emits `raw/` scratch WAVs; only `assets/` belongs in the pack.

## Sources and licenses

The generated waveforms use eSpeak NG's built-in `en-us` formant synthesizer,
without MBROLA voices or third-party voice recordings. eSpeak NG is GPL-3.0-or-later:
<https://github.com/espeak-ng/espeak-ng/blob/1.52.0/COPYING>.
Source code is available at <https://github.com/espeak-ng/espeak-ng/tree/1.52.0>.
The dependency is a local build tool; its binaries/data are not part of the game
resource pack. The GPL covers output only if that output itself constitutes a
covered work: <https://espeak.sourceforge.net/license.html> (section 2).

The installed Audacity copy supplies libsndfile (LGPL), libogg (BSD), and libvorbis
(BSD) for local encoding. Their binaries are also excluded from the resource pack.
NumPy is BSD-licensed. No downloaded engine/dependency binary is required to play
the resulting resource pack.
