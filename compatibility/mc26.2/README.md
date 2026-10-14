# Star Program resource pack for Minecraft 26.2

`sp_v14-mc26.2.zip` retains the repaired v10 assets from commit `b06190b`.
The compatibility overlay:

- Declare resource format 88.0 for Minecraft 26.2.
- Use Minecraft's current lightmap sampler in the particle vertex shader.
- Draw particle control markers at near depth 1 for Minecraft 26.2's reversed depth buffer, preserving the existing shake, warp, and alarm channels.
- Use procedural full-screen triangles for both custom post vertex shaders.
- Flatten the marker-list macro so GLSL 330 does not require a later line-continuation extension.
- Restore acacia monitor signs using 14 Minecraft 26.2 block models, including standing, wall, attached hanging, and wall hanging variants.
- Map each model face to the original monitor artwork and register those two textures in the block atlas. The PNGs remain byte-identical.
- Keep ordinary skies on Minecraft 26.2's native geometry and `FogSkyEnd` fog settings. The camera-facing cone is used only for the three existing custom-sky activator colors.

All 2,351 original asset paths remain present; 14 model files are added.
Compared with v13, only `sky.vsh` and `sky.fsh` change. The other 2,364 archive entries are byte-identical, including all custom sounds, textures, glyphs, particle control, post effects, and custom sky effect equations. Version 13 is retained unchanged. The ZIP passes CRC checks and all 1,427 JSON files parse.
Four sign compatibility tests verify geometry, atlas entries, and exact texture
pixels and orientation across all 158 model faces against official client assets.
Four focused sky checks verify ordinary sky geometry, all three custom activators, the official 26.2 fog contract, and the limited asset changes. Both corrected shaders pass CPU-only GLSL compilation with zero errors or warnings. Rendered appearance and runtime driver bindings have not been checked in Minecraft.

SHA-256: `8985217348dff707819803e36e8d86e078baf1480f55eadc08aacabe5d35db08`

SHA-1: `a2747e3ec5becffb70dd51306749eda6efd34bf9`

Enable **Improved Transparency** in Video Settings to run the post-processing
chain. Disable any active Iris shader pack, which replaces core shaders.
