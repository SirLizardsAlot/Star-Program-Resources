# Star Program resource pack for Minecraft 26.2

`sp_v11-mc26.2.zip` retains the repaired v10 assets from commit `b06190b`.
The compatibility overlay changes five files:

- Declare resource format 88.0 for Minecraft 26.2.
- Use Minecraft's current lightmap sampler in the particle vertex shader.
- Use procedural full-screen triangles for both custom post vertex shaders.
- Flatten the marker-list macro so GLSL 330 does not require a later line-continuation extension.

All 2,351 asset paths remain present. The other 2,347 files are byte-identical,
including custom sounds, textures, glyphs, models, and shader effect equations.
All 11 shader stages pass CPU-only shaderc compilation with the official 26.2
shader imports. The ZIP passes CRC checks and all 1,413 JSON files parse.
Rendered appearance and runtime driver bindings have not been checked in Minecraft.

SHA-256: `52258bd824660893513732797a19141c2cd51486f67e1deef0ae7f312875403a`

SHA-1: `e8d5fb3f03885e38406ed4b887c3045c28087557`
