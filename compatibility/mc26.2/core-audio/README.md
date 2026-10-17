# Positional core audio

`build_audio.py` downmixes six existing core sound assets from the preserved
published `sp_v21-mc26.2.zip`. It introduces no new recordings or attribution
claims. The original pack and extracted source bytes remain preserved.

The downmix is `(left + right) / 2`, with gain 1, no filtering, normalization,
resampling, trimming, or pitch manipulation. Each output retains the source's
sample rate and complete decoded waveform. Ogg Vorbis quality is 0.5. The
manifest records original/output hashes, frame counts, RMS, and peak levels.
Stereo averaging naturally reduces RMS where the two channels differ; there is
no compensating gain that could further overload the inherited loud recordings.

The inherited beep stream ends at granule 47104, including a 1024-frame initial
offset. It decodes to 46080 actual waveform frames (0.96 s at 48 kHz). The mono
file preserves those 46080 samples. The manifest records its source container
granule separately rather than adding silence or cutting any decoded samples.

`custom.powerswitch` already points to a mono 44.1 kHz recording and remains
byte-identical. Event registrations remain unchanged. No new metadata or credits
are inserted into the resource-pack archive. All existing credits, turbine audio,
announcements, elevator audio, artwork, and shaders remain byte-identical to v21.

The final archive differs from v21 in exactly the six specified Ogg files.
`core_audio_overlay.py` verifies source hashes, prepared manifest, native sample
rates, and output frame counts before the pack builder accepts replacements.
