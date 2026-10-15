# Complete Matthew announcements

The bank records each existing facility announcement as one continuous Matthew
utterance, generated through the user's subscribed ttsMP3 member interface.
The provider uses its natural default speaking rate. There is no word or
phoneme splicing, pitch flattening, or time stretching.

`authored-render-plan.json` preserves the source text, trigger, timer, and
audience for all 20 nonempty callsites. Two punctuation/color variants of
“Core anomaly detected” share one recording, giving 19 audio files. The three
empty announcement calls still clear their channel. Existing visual countdowns
remain independent of speech.

The selected processing adds restrained speaker shaping and a diffuse facility
room to the whole utterance: approximately 90 Hz to 6.5 kHz speaker bandwidth,
650 ms room tail, 25 ms predelay, 180 ms decay, and 17% wet signal. Whole-message
linear level matching keeps gain consistent. There is no hiss, chime, pitch
resynthesis, saturation, or extra pause between individual words.

`manifest.json` maps each ID to its render text, original-text aliases, custom
sound event, source provenance, SHA-256, speech duration, complete duration, and
playback ticks. Assets are mono 22,050 Hz Ogg Vorbis at quality 0.65, with one
deterministic, non-streamed sound per event. Tick timing includes the full room
tail. The plot requires no speech service or account during playback.

The native `announcements` mode matches a complete normalized message, ignoring
formatting, case, and punctuation differences. It preserves the existing major,
minor, chamber, and private audiences and one bounded playback queue. Stop and
channel-clear operations cancel an active recording as well as queued speech.

`@tts <recorded text>` privately previews a known announcement. New custom text
requires a new recording and pack rebuild. Source MP3s and their render requests
remain under `sources/`; generation uses the normal provider interface, while
local processing needs no provider credentials. The source bundle contains no
login, password, cookies, or API key.

Rebuild the audio from its preserved sources with Python and NumPy:

```powershell
python game/resource-pack/tts/announcements/render_announcements.py --source-map game/resource-pack/tts/announcements/source-map.json --effect intercom
```

The Windows helper loads the installed Audacity `mpg123.dll` and `sndfile.dll`
from `C:\Program Files\Audacity`. It imports the shared `../build_audio.py`
for WAV and OGG utilities, without invoking a speech engine. Models, Piper,
Praat, and an account login are unnecessary for local processing. Put NumPy on
the Python path or in the private `.tools/python/` dependency folder.

The [ttsMP3 FAQ](https://ttsmp3.com/faq) permits generated audio in commercial
and non-commercial projects. These are new stock-voice renders; no audio was
copied from Innovation Inc. Thermal Power Plant. The exact game announcer's
processing has not been reproduced or verified.

Earlier word, phoneme, and diphone experiments remain preserved separately.
Only the complete announcement clips enter this pack. The final ZIP retains
every pre-existing v14 resource byte-for-byte and must fit the 40 MiB plot limit.
