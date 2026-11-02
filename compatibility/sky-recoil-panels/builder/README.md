# Sky Block and visual recoil

Red glazed terracotta is named **Sky Block** and renders the earlier DF Sky
Window sky on all six faces. The native cloud bitmap, cloud cell shapes, sun,
moon, sky disc and day timeline come from the previous Simulation DF plot
renderer. The actual lunar sky remains separate.

Oak trapdoors are named **Sky Panel**. Their mounting/back broad face is a
double-sided sky backing. The front and four thin edges use actual tinted
glass. An inset inward face makes the sky backing visible through the front
glass even when the panel is flush against a solid block. Bottom, top, open,
all four directions and waterlogged states retain native trapdoor dimensions,
collision and interaction. Sky Panel uses the same time control as Sky Block.

Call these native functions for the default player:

- `SP.Shader.Sky.Time(6000)` selects noon. `0` is dawn, `12000` dusk and
  `18000` midnight. Inputs wrap through the 24,000 tick day. Time changes take
  up to a quarter second along the shortest route through the day.
- `SP.Shader.Recoil(2, 0.5)` gives a visual kick two degrees upward and half a
  degree right, then returns over four ticks. Negative values reverse each
  axis. Repeated calls restart the kick. Each axis is limited to eight degrees.
  Small one to three degree kicks avoid noticeable cropping.

The player's actual aim and mouse axes remain unchanged. The existing player
loop owns the heartbeat. No extra recoil process or saved variable is added.

The four added controls use `entity_effect` particles with zero opacity. Their
red byte is the tick sequence modulo 128, green identifies the channel and blue
is the payload. See `native-controls.json`. Each sequence has a separate shader
pixel, preventing older particles from averaging newer recoil values. Camera
metadata uses binary pixels, which remain exact under half-float accumulation.

Sky Block keeps solid depth and writes a visibility mask in framebuffer alpha.
Premultiplied glass composition preserves that mask. The final pass subtracts
the fixed noon baseline and adds the selected sky with the surviving coverage.
This permits particle-controlled time without adding unsupported terrain
sampler bindings. Native and Sodium 0.9.2+mc26.3 terrain paths share the same
baseline. Item icons retain a fixed noon sky. Missing camera metadata leaves
the baseline visible, and expired recoil controls ease back to zero.

`py build.py` builds and validates the exact pinned base plus these overrides.
The archive preserves every unrelated resource and existing audio byte. The
local ShaderC validator checks core attributes, shader stage interfaces, OIT
variants, both depth conventions and post-pass bindings. `preview.mjs` is an
isolated WebGL preview, not a Minecraft test.

`release.py stage`, `publish` and `pin` use a dedicated publication branch,
verify immutable hosted bytes and preserve the previous resource pin. Native
helpers are prepared in the matching portal build. The user sends them.
