# Star Program resource pack for Minecraft 26.2

`sp_v12-mc26.2.zip` retains the repaired v10 assets from commit `b06190b`.
The compatibility overlay:

- Declare resource format 88.0 for Minecraft 26.2.
- Use Minecraft's current lightmap sampler in the particle vertex shader.
- Use procedural full-screen triangles for both custom post vertex shaders.
- Flatten the marker-list macro so GLSL 330 does not require a later line-continuation extension.
- Restore acacia monitor signs using 14 Minecraft 26.2 block models, including standing, wall, attached hanging, and wall hanging variants.
- Map each model face to the original monitor artwork and register those two textures in the block atlas. The PNGs remain byte-identical.

All 2,351 original asset paths remain present; 14 model files are added.
The other 2,346 source files are byte-identical, including all custom sounds,
textures, glyphs, and shader effect equations. The 11 shader stages are unchanged
from the v11 build that passed CPU-only shaderc compilation with official 26.2
imports. The ZIP passes CRC checks and all 1,427 JSON files parse.
Four sign compatibility tests verify geometry, atlas entries, and exact texture
pixels and orientation across all 158 model faces against official client assets.
Rendered appearance and runtime driver bindings have not been checked in Minecraft.

SHA-256: `c77c8147e200ffd0febd934008e14c926bba321858f07fccaba2cd7eb7528542`

SHA-1: `36d2c05a491793afa792699cf1102c9f5c4880a7`
