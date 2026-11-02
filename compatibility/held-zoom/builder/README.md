# Held zoom

`SP.Shader.Zoom(t)` sets the default player's held zoom. Inputs are normalized
from 0 to 1 and are clamped to that range.

- `0` restores the player's current view.
- `0.5` selects approximately half of the player's current vertical FOV.
- `1` reaches the zero-FOV limit, sampling only the centre pixel.

The target stays active until another call changes it. Repeated calls set the
target. They do not accumulate. The existing independent particle heartbeat
refreshes each player's target during plot initialization and gameplay.

The shader interpolates FOV angle toward zero, then derives the centred crop
from that angle. Both image axes use the same factor to preserve aspect ratio.
Zoom magnifies the rendered image, so it retains the source image's detail.
It does not change the player's actual aim or require a client mod.

The current projection is recovered from the camera ray map to avoid treating
ordinary view bobbing as a change in focal scale. Zoom transitions use the
existing smooth target response and snap exactly to settled endpoints.

The native target is `SP.Shader.Player.%uuid.Zoom` in unsaved game scope.
The particle payload has 255 intervals. Greens 246 and 245 are distinct from
old recoil particles, so old neutral recoil packets cannot enable zoom.
Sky time, invisible marker item data, camera metadata, legacy shake/alarm,
the sky renderer and the corrected Sky Panel models are preserved.

`py build.py build` derives the archive from the exact pinned clean-panel pack
and runs local shader checks. `stage`, `publish`, and `pin` publish verified
immutable files. `game/tools/install-held-zoom.mjs` prepares only Join, Init,
Tick, the retired recoil stub and the new Zoom function for the portal.
The user handles sending all five templates. No Minecraft connection is used.
