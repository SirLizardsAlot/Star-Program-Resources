# Star Program resource pack for Minecraft 26.2

`sp_v13-mc26.2.zip` retains the repaired v10 assets from commit `b06190b`.
The compatibility overlay:

- Declare resource format 88.0 for Minecraft 26.2.
- Use Minecraft's current lightmap sampler in the particle vertex shader.
- Draw particle control markers at near depth 1 for Minecraft 26.2's reversed depth buffer, preserving the existing shake, warp, and alarm channels.
- Use procedural full-screen triangles for both custom post vertex shaders.
- Flatten the marker-list macro so GLSL 330 does not require a later line-continuation extension.
- Restore acacia monitor signs using 14 Minecraft 26.2 block models, including standing, wall, attached hanging, and wall hanging variants.
- Map each model face to the original monitor artwork and register those two textures in the block atlas. The PNGs remain byte-identical.

All 2,351 original asset paths remain present; 14 model files are added.
The other 2,346 source files are byte-identical, including all custom sounds,
textures, glyphs, and shader effect equations. Compared with v12, only the particle vertex shader changes: marker depth is
1 instead of 0. All other 2,365 archive entries remain byte-identical. The ZIP passes CRC checks and all 1,427 JSON files parse.
Four sign compatibility tests verify geometry, atlas entries, and exact texture
pixels and orientation across all 158 model faces against official client assets.
Rendered appearance and runtime driver bindings have not been checked in Minecraft.

SHA-256: `5dc5d20418aa87210a58677787c72a6a8f75e9468b22049404a59462275236f7`

SHA-1: `851d70f4f6a8bdbc7b27ee5e9edf2756a0170273`

Enable **Improved Transparency** in Video Settings to run the post-processing
chain. Disable any active Iris shader pack, which replaces core shaders.
