# Code Black audio

`build_audio.py` exports one 13.4-second rise/hold/fall sweep from the user's
selected Poligonstudio CC0 siren, plus a complete new Matthew evacuation
announcement processed with the established intercom EQ and room effect.
Original downloads, hashes, request text, and source licenses are preserved.

Runtime events at normal playback pitch:

- `star_program_emergency:code_black.siren`: 268 ticks, 13,400 ms. Repeat in code.
- `star_program_emergency:pa.code_black`: 307 ticks, 15,314.15 ms including tail.

`build_pack.py` creates and validates `../sp_v23-mc26.2.zip` from published v21.
Every v21 asset remains byte-identical, including the original core recordings
that were deliberately restored after v22. Only the two emergency sound files,
their deterministic event registry, and credits are added. The script rejects
unrelated changes, duplicate ZIP names, corrupt files, and archives over 40 MiB.

Use the existing bundled Python interpreter. Build audio first, then the pack.
Resource publication and the game pack pin are handled separately after verifying
the immutable public archive. This workflow never connects to Minecraft or sends
game templates.
