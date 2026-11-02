"""Prepare the existing DF Sky Window renderer with runtime day controls.

Only this overlay's dfsky include files are generated. The source project and
its built archive remain unchanged. No resource pack is built or published.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
SOURCE = WORKSPACE.parent / "Simulation DF plot"
INCLUDES = HERE / "overrides/assets/dfsky/shaders/include"
TRACKS = ("sky_color", "fog_color", "cloud_color", "sunrise_sunset_color", "star_brightness")


def source_bytes(relative: str) -> bytes:
    loose = SOURCE / "resource-pack" / relative
    if loose.is_file():
        return loose.read_bytes()
    with ZipFile(SOURCE / "build/df-sky-window-26.2.zip") as archive:
        return archive.read(relative)


def rgba(value: str | int) -> tuple[float, ...]:
    if isinstance(value, str):
        digits = value.removeprefix("#")
        number = int(digits, 16)
        alpha = ((number >> 24) & 255) / 255 if len(digits) == 8 else 1.0
    else:
        number = value & 0xFFFFFFFF
        alpha = ((number >> 24) & 255) / 255
    return (((number >> 16) & 255) / 255, ((number >> 8) & 255) / 255,
            (number & 255) / 255, alpha)


def glsl_float(value: float) -> str:
    return f"{float(value):.10f}"


def glsl_vec(values: tuple[float, ...] | list[float]) -> str:
    return f"vec{len(values)}(" + ", ".join(glsl_float(v) for v in values) + ")"


def sample_track(keys: list[dict], ticks: float, color: bool) -> tuple[float, ...]:
    tick = ticks % 24000.0
    a, b = keys[-1], keys[0]
    at, bt = a["ticks"], b["ticks"] + 24000
    if tick < keys[0]["ticks"]:
        tick += 24000
    for left, right in zip(keys, keys[1:]):
        if left["ticks"] <= ticks % 24000 < right["ticks"]:
            a, b = left, right
            at, bt, tick = left["ticks"], right["ticks"], ticks % 24000
            break
    amount = 0.0 if at == bt else (tick - at) / (bt - at)
    av = rgba(a["value"]) if color else (float(a["value"]),)
    bv = rgba(b["value"]) if color else (float(b["value"]),)
    return tuple(x + (y - x) * amount for x, y in zip(av, bv))


def bezier_ease(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0

    def cubic(t: float, a: float, b: float) -> float:
        return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3

    low, high = 0.0, 1.0
    for _ in range(32):
        middle = (low + high) * 0.5
        if cubic(middle, 0.362, 0.638) < value:
            low = middle
        else:
            high = middle
    return cubic((low + high) * 0.5, 0.241, 0.759)


def state_at(tracks: dict, config: dict, ticks: float) -> dict:
    sampled = {name: sample_track(tracks[name], ticks, name != "star_brightness") for name in TRACKS}
    sky = tuple(v * m for v, m in zip(rgba("#78a7ff")[:3], sampled["sky_color"][:3]))
    base_fog = tuple(v * m for v, m in zip(rgba("#c0d8ff")[:3], sampled["fog_color"][:3]))
    fog_blend = 1 - (0.25 + 0.75 * min(config["renderDistanceChunks"], 32) / 32) ** 0.25
    return {
        "timeTicks": ticks % 24000.0,
        "sunAngle": bezier_ease(((ticks - 6000) % 24000) / 24000) * math.tau,
        "starBrightness": sampled["star_brightness"][0],
        "skyColor": sky,
        "fogColor": tuple(v + (s - v) * fog_blend for v, s in zip(base_fog, sky)),
        "cloudColor": tuple(v * m for v, m in zip(rgba("#ccffffff"), sampled["cloud_color"])),
        "sunsetColor": sampled["sunrise_sunset_color"],
    }


def track_function(name: str, keys: list[dict]) -> str:
    color = name != "star_brightness"
    result_type = "vec4" if color else "float"
    render = lambda value: glsl_vec(rgba(value)) if color else glsl_float(value)
    lines = [f"{result_type} dfsky_track_{name}(float tick) {{",
             f"    float t = tick < {glsl_float(keys[0]['ticks'])} ? tick + 24000.0 : tick;"]
    for a, b in zip(keys, keys[1:]):
        lines.extend([
            f"    if (t < {glsl_float(b['ticks'])}) {{",
            f"        return mix({render(a['value'])}, {render(b['value'])},",
            f"            (t - {glsl_float(a['ticks'])}) / {glsl_float(b['ticks'] - a['ticks'])});",
            "    }",
        ])
    a, b = keys[-1], keys[0]
    lines.extend([
        f"    return mix({render(a['value'])}, {render(b['value'])},",
        f"        (t - {glsl_float(a['ticks'])}) / {glsl_float(b['ticks'] + 24000 - a['ticks'])});",
        "}",
    ])
    return "\n".join(lines)


def prepare() -> dict:
    config = json.loads((SOURCE / "sky-config.json").read_text(encoding="utf-8"))
    timeline = json.loads((SOURCE / "tools/vanilla-26.2/data/minecraft/timeline/day.json").read_text(encoding="utf-8"))
    tracks = {name: timeline["tracks"]["minecraft:visual/" + name]["keyframes"] for name in TRACKS}
    noon = state_at(tracks, config, 6000)
    old_settings = source_bytes("assets/dfsky/shaders/include/settings.glsl").decode("utf-8")
    field_macros = {
        "sunAngle": "DFSKY_SUN_ANGLE", "starBrightness": "DFSKY_STAR_BRIGHTNESS",
        "skyColor": "DFSKY_SKY_COLOR", "fogColor": "DFSKY_FOG_COLOR",
        "cloudColor": "DFSKY_CLOUD_COLOR", "sunsetColor": "DFSKY_SUNSET_COLOR",
    }
    noon_error = 0.0
    for field, macro in field_macros.items():
        expression = re.search(r"^#define " + macro + r" (.+)$", old_settings, re.M).group(1)
        old_values = tuple(float(n) for n in re.findall(r"[-+]?\d+\.\d+", expression))
        values = noon[field] if isinstance(noon[field], tuple) else (noon[field],)
        error = max(abs(a - b) for a, b in zip(old_values, values))
        assert len(old_values) == len(values) and error <= 5.1e-9, (macro, old_values, values)
        noon_error = max(noon_error, error)

    settings = """#ifndef DFSKY_SETTINGS_GLSL
#define DFSKY_SETTINGS_GLSL
// Static geometry matches the successful DF Sky Window build.
// Runtime state starts at its exact fixed-noon values.
"""
    static_values = {
        "DFSKY_SUN_SIZE": config["sunSize"], "DFSKY_MOON_SIZE": config["moonSize"],
        "DFSKY_SKY_FOG_END": min(config["renderDistanceChunks"] * 16, 512),
        "DFSKY_CLOUD_FOG_END": config["cloudFogDistance"],
        "DFSKY_CLOUD_HEIGHT": config["cloudHeight"],
        "DFSKY_VIRTUAL_EYE_HEIGHT": config["virtualEyeHeight"],
        "DFSKY_CLOUD_OFFSET_X": config["cloudOffsetX"], "DFSKY_CLOUD_OFFSET_Z": config["cloudOffsetZ"],
        "DFSKY_FOG_BLEND": 1 - (0.25 + 0.75 * min(config["renderDistanceChunks"], 32) / 32) ** 0.25,
    }
    settings += "\n".join(f"#define {key} {glsl_float(value)}" for key, value in static_values.items()) + "\n"
    settings += f"#define DFSKY_CLOUDS {int(config['clouds'])}\n#define DFSKY_STARS {int(config['stars'])}\n"
    settings += """
struct DfSkyState {
    float timeTicks;
    float sunAngle;
    float starBrightness;
    vec3 skyColor;
    vec3 fogColor;
    vec4 cloudColor;
    vec4 sunsetColor;
};
"""
    settings += "DfSkyState dfskyState = DfSkyState(\n    " + ",\n    ".join(
        glsl_vec(value) if isinstance(value, tuple) else glsl_float(value)
        for value in noon.values()
    ) + "\n);\n"
    settings += "#define DFSKY_TIME_TICKS (dfskyState.timeTicks)\n"
    settings += "\n".join(f"#define {macro} (dfskyState.{field})" for field, macro in field_macros.items())
    settings += "\n#endif\n"

    runtime = """#ifndef DFSKY_RUNTIME_GLSL
#define DFSKY_RUNTIME_GLSL
#include <dfsky:settings.glsl>
// Color/brightness keyframes are copied from the same official 26.2 native
// day timeline used by the original fixed-time build. Inputs wrap at 24000.
"""
    runtime += "\n\n".join(track_function(name, tracks[name]) for name in TRACKS)
    runtime += """

float dfsky_bezierCubic(float t, float a, float b) {
    float inverseT = 1.0 - t;
    return 3.0 * inverseT * inverseT * t * a + 3.0 * inverseT * t * t * b + t * t * t;
}

float dfsky_celestialEase(float x) {
    if (x <= 0.0) return 0.0;
    if (x >= 1.0) return 1.0;
    float low = 0.0;
    float high = 1.0;
    for (int i = 0; i < 32; ++i) {
        float middle = (low + high) * 0.5;
        if (dfsky_bezierCubic(middle, 0.362, 0.638) < x) low = middle;
        else high = middle;
    }
    return dfsky_bezierCubic((low + high) * 0.5, 0.241, 0.759);
}

void dfsky_setTime(float ticks) {
    float tick = isnan(ticks) || isinf(ticks) ? 6000.0 : mod(ticks, 24000.0);
    dfskyState.timeTicks = tick;
    dfskyState.sunAngle = dfsky_celestialEase(mod(tick - 6000.0, 24000.0) / 24000.0) * 6.283185307179586;
    dfskyState.starBrightness = dfsky_track_star_brightness(tick);
    dfskyState.skyColor = vec3(120.0, 167.0, 255.0) / 255.0 * dfsky_track_sky_color(tick).rgb;
    vec3 fog = vec3(192.0, 216.0, 255.0) / 255.0 * dfsky_track_fog_color(tick).rgb;
    dfskyState.fogColor = mix(fog, dfskyState.skyColor, DFSKY_FOG_BLEND);
    dfskyState.cloudColor = vec4(1.0, 1.0, 1.0, 0.8) * dfsky_track_cloud_color(tick);
    dfskyState.sunsetColor = dfsky_track_sunrise_sunset_color(tick);
}
#endif
"""

    old_sky = source_bytes("assets/dfsky/shaders/include/sky.glsl").decode("utf-8")
    sky = old_sky.replace("#moj_import", "#include")
    sky = sky.replace("#include <dfsky:settings.glsl>", "#include <dfsky:settings.glsl>\n#include <dfsky:runtime.glsl>")
    start = sky.index("    if (c.b == 173 && c.a == 251) {")
    end = sky.index("    return all(equal(c, ivec4(17, 239, 173, 255)));", start)
    sky = sky[:start] + sky[end:]
    assert sky[sky.index("float dfsky_stars"):].replace("\r\n", "\n") == old_sky[old_sky.index("float dfsky_stars"):].replace("\r\n", "\n")
    INCLUDES.mkdir(parents=True, exist_ok=True)
    (INCLUDES / "settings.glsl").write_text(settings, encoding="utf-8", newline="\n")
    (INCLUDES / "runtime.glsl").write_text(runtime, encoding="utf-8", newline="\n")
    (INCLUDES / "sky.glsl").write_text(sky, encoding="utf-8", newline="\n")
    (INCLUDES / "vanilla_data.glsl").write_bytes(source_bytes("assets/dfsky/shaders/include/vanilla_data.glsl"))

    checked_ticks = sorted({0.0, 6000.0, 12000.0, 18000.0, 23999.0, 24000.0, -1.0,
                            *(float(key["ticks"]) for keys in tracks.values() for key in keys)})
    for tick in checked_ticks:
        state = state_at(tracks, config, tick)
        wrapped = state_at(tracks, config, tick + 24000.0)
        assert state == wrapped, (tick, state, wrapped)
        for name, value in state.items():
            assert all(math.isfinite(v) for v in (value if isinstance(value, tuple) else (value,))), (tick, name)
    return {
        "files": [str(INCLUDES / name) for name in ("sky.glsl", "settings.glsl", "vanilla_data.glsl", "runtime.glsl")],
        "nativeTimelineTracks": len(tracks), "nativeTimelineKeyframes": sum(map(len, tracks.values())),
        "noonMaximumDifferenceFromOriginalRoundedSettings": noon_error,
        "endpointAndKeyframeChecks": len(checked_ticks),
        "renderFunctionsUnchanged": True, "vanillaAssetsCopiedByteForByte": True,
    }


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
