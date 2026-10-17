# Meltdown music sections

The approved draft assets, source recording, edit decisions, analysis, and
audition renders are preserved. `prepare_runtime.py` creates `runtime/` from
those assets without re-encoding. It removes only 217,233 digital-zero frames
from the ending by adjusting the final Ogg page granule and CRC. Decoding must
show that every retained PCM sample is identical to the approved recording;
intro and middle Ogg bytes are unchanged. The ending is exactly 62 seconds.

Runtime events at normal playback pitch and tempo:

- `star_program_music:meltdown.intro`: 67.56 seconds; first boundary at 1,350 ticks.
- `star_program_music:meltdown.middle`: 15.06 seconds; repeat every 300 ticks.
- `star_program_music:meltdown.ending`: 62 seconds; event impact after 1,240 ticks.

Section handles overlap by 60 ms. Start each new section at its declared
boundary without stopping the preceding handle. Stop all three event names
when ending playback early. The complete song asset is removed from v25;
`minecraft:custom.overloadmusic` remains an alias to the intro for compatibility.

Using the bundled Python interpreter, run `prepare_runtime.py`, `build_pack.py`,
then `stage_pack.py`. Build validation compares every archive member against
the exact published v24 baseline. Only the old song asset and its registration
may change; the three section recordings and their registry are added. All
warning alarms and unrelated sound registrations remain byte-identical.
Archives are immutable and limited to 40 MiB. `build_pack.py --check` validates
an existing v25 archive without rebuilding it.

Publish the staged checkout with a normal fast-forward push to the existing
`codex/star-program-resourcepack-26-2` branch, then run `pin_pack.py COMMIT`.
It verifies the immutable public ZIP against the checked local bytes before
backing up the previous configuration and updating the resource-pack pin.
None of these operations connects to Minecraft or sends native game code.
