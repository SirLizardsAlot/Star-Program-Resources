"""Reproducible 26.2 compatibility overlay; every unrelated asset is preserved."""
from pathlib import Path
import copy
import hashlib
import json
import re
import struct
import zipfile
from tts_overlay import tts_patches
from intercom_overlay import intercom_patches
from turbine_overlay import turbine_patches
from core_audio_overlay import core_audio_patches, CHANGED_FILES, PREVIOUS_SHA256

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "input" / "sp_v10-fixed-1.21.11.zip"
CLIENT = ROOT.parents[1] / "plot-locations" / ".local" / "gradle-home" / "caches" / "fabric-loom" / "26.2" / "minecraft-client.jar"
OUTPUT = ROOT / "sp_v22-mc26.2.zip"
PREVIOUS = ROOT / "sp_v21-mc26.2.zip"
EXPECTED_PREVIOUS_SHA256 = PREVIOUS_SHA256
EXPECTED_PREVIOUS_CHANGED = CHANGED_FILES
EXPECTED_PREVIOUS_ADDED = set()
OVERRIDES = ROOT / "overrides"
VALIDATION = ROOT / "validation"
EXPECTED_SOURCE_BLOB = "13cf5e4b2b1168b639b4de54c009bbb7a2317591"
MAX_PACK_BYTES = 40 * 1024 * 1024

# Minecraft 26.2 moved signs from entity rendering to ordinary block models.
# Its compact 32x32 atlas is different from the original 64x32 entity atlas.
# Keep the authored monitor artwork untouched and map each new-model face to
# its original pixels. Values on the right are legacy pixel coordinates;
# reversed coordinates intentionally preserve the original bottom/chain UVs.
SIGN_UVS = {
    (0, 0, 12, 1): (2, 0, 26, 2),
    (0, 1, 12, 7): (2, 2, 26, 14),
    (0, 8, 12, 14): (28, 2, 52, 14),
    (0, 14, 12, 15): (26, 2, 50, 0),
    (12, 1, 13, 7): (26, 2, 28, 14),
    (12, 8, 13, 14): (0, 2, 2, 14),
    (14, 0, 15, 7): (2, 16, 4, 30),
    (14, 8, 15, 15): (6, 16, 8, 30),
    (14, 15, 15, 16): (4, 16, 6, 14),
    (15, 0, 16, 7): (4, 16, 6, 30),
    (15, 8, 16, 15): (0, 16, 2, 30),
}
HANGING_SIGN_UVS = {
    (0, 0, 8, 2): (4, 0, 20, 4),
    (0, 2, 8, 3): (4, 4, 20, 6),
    (0, 3.5, 8, 4.5): (24, 4, 40, 6),
    (0, 8, 1, 13): (0, 14, 2, 24),
    (1, 7, 8, 8): (2, 12, 16, 14),
    (1, 8, 8, 13): (2, 14, 16, 24),
    (1, 13, 8, 14): (16, 14, 30, 12),
    (8, 2, 10, 3): (20, 4, 24, 6),
    (8, 3.5, 10, 4.5): (0, 4, 4, 6),
    (8, 4.5, 0, 6.5): (20, 4, 36, 0),
    (8, 8, 9, 13): (16, 14, 18, 24),
    (9, 8, 16, 13): (18, 14, 32, 24),
    (10, 0, 16, 3): (14, 6, 26, 12),
    (11, 3.5, 12.5, 6.5): (0, 6, 3, 12),
    (11, 5.5, 12.5, 6.5): (0, 10, 3, 12),
    (12.5, 3.5, 11, 6.5): (3, 6, 0, 12),
    (12.5, 5.5, 11, 6.5): (3, 10, 0, 12),
    (14, 4, 15.5, 6): (6, 7, 9, 11),
    (14, 4.5, 15.5, 6): (6, 8, 9, 11),
    (15.5, 4, 14, 6): (9, 7, 6, 11),
    (15.5, 4.5, 14, 6): (9, 8, 6, 11),
    (16, 0, 10, 3): (26, 6, 14, 12),
}


def sign_model_patches(client, source):
    """Retain 26.2 sign geometry and bind it to the original monitor PNGs."""
    patches = {}
    atlas_resources = []
    for hanging, uv_map in [(False, SIGN_UVS), (True, HANGING_SIGN_UVS)]:
        suffix = "hanging_sign" if hanging else "sign"
        texture = "minecraft:entity/signs/" + ("hanging/" if hanging else "") + "acacia"
        texture_path = "assets/minecraft/textures/" + texture.split(":", 1)[1] + ".png"
        image = source[texture_path]
        if image[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", image[16:24]) != (64, 32):
            raise ValueError(f"Expected the original 64x32 sign texture: {texture_path}")
        names = [f"acacia_{suffix}_rot_{rotation}" for rotation in range(4)]
        if hanging:
            names += [f"acacia_hanging_sign_attached_rot_{rotation}" for rotation in range(4)]
        names += [f"acacia_wall_{suffix}"]
        for name in names:
            path = f"assets/minecraft/models/block/{name}.json"
            if path in source:
                raise ValueError(f"Refusing to overwrite an authored sign model: {path}")
            child = json.loads(client.read(path))
            if child["textures"]["all"] != f"minecraft:block/acacia_{suffix}":
                raise ValueError(f"Unexpected vanilla sign texture: {path}")
            namespace, parent_name = child["parent"].split(":", 1)
            template = json.loads(client.read(f"assets/{namespace}/models/{parent_name}.json"))
            model = copy.deepcopy(template)
            model["textures"] = {**child["textures"], "all": texture}
            for element in model["elements"]:
                for face in element["faces"].values():
                    if face["texture"] != "#all":
                        raise ValueError(f"Unexpected vanilla sign face: {path}")
                    pixels = uv_map[tuple(face["uv"])]
                    face["uv"] = [value * (0.25 if index % 2 == 0 else 0.5) for index, value in enumerate(pixels)]
            patches[path] = (json.dumps(model, indent=2) + "\n").encode()
        atlas_resources.append(texture)
    atlas_path = "assets/minecraft/atlases/blocks.json"
    atlas = json.loads(source[atlas_path])
    atlas["sources"] += [{"type": "minecraft:single", "resource": resource} for resource in atlas_resources]
    patches[atlas_path] = (json.dumps(atlas, indent=2) + "\n").encode()
    return patches


def git_blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def changed_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f"Expected exactly one source fragment: {before!r}")
    return source.replace(before, after)


def sky_shader_patches(source):
    """Use the custom sky cone only for its three authored fog activators."""
    vertex_path = "assets/minecraft/shaders/core/sky.vsh"
    fragment_path = "assets/minecraft/shaders/core/sky.fsh"
    vertex = changed_once(source[vertex_path].decode(),
        "if (1 == 1 || is_sky_color(", "if (is_sky_color(")
    # The ordinary sky keeps the native 26.2 sky fog contract. The custom
    # space, End, and warp branches are retained byte for byte.
    fragment = changed_once(source[fragment_path].decode(),
        "apply_fog(ColorModulator, sphericalVertexDistance, cylindricalVertexDistance, FogEnvironmentalStart, FogEnvironmentalEnd, FogRenderDistanceStart, FogRenderDistanceEnd, FogColor)",
        "apply_fog(ColorModulator, sphericalVertexDistance, cylindricalVertexDistance, 0.0, FogSkyEnd, FogSkyEnd, FogSkyEnd, FogColor)")
    return {vertex_path: vertex.encode(), fragment_path: fragment.encode()}


def build():
    previous_bytes = PREVIOUS.read_bytes()
    if hashlib.sha256(previous_bytes).hexdigest() != EXPECTED_PREVIOUS_SHA256:
        raise ValueError("Previous pack is not the preserved published v21 archive.")
    source_bytes = SOURCE.read_bytes()
    if git_blob(source_bytes) != EXPECTED_SOURCE_BLOB:
        raise ValueError("Input is not the preserved repaired resource pack.")
    with zipfile.ZipFile(SOURCE) as pack, zipfile.ZipFile(CLIENT) as client:
        source = {entry.filename: pack.read(entry) for entry in pack.infolist() if not entry.is_dir()}
        if len(source) != len([entry for entry in pack.infolist() if not entry.is_dir()]):
            raise ValueError("Duplicate resource names in source archive.")
        version = json.loads(client.read("version.json"))
        if version["id"] != "26.2" or version["pack_version"]["resource_major"] != 88:
            raise ValueError("Expected the cached official Minecraft 26.2 client.")
        patches = {}
        metadata = json.loads(source["pack.mcmeta"])
        metadata["pack"]["description"] = "Star Program - Minecraft 26.2"
        metadata["pack"]["min_format"] = [88, 0]
        metadata["pack"]["max_format"] = [88, 0]
        patches["pack.mcmeta"] = (json.dumps(metadata, indent=2) + "\n").encode()

        particle_path = "assets/minecraft/shaders/core/particle.vsh"
        particle = source[particle_path].decode()
        particle = changed_once(particle, "#moj_import <minecraft:globals.glsl>", "#moj_import <minecraft:globals.glsl>\n#moj_import <minecraft:sample_lightmap.glsl>")
        particle = changed_once(particle, "Color * texelFetch(Sampler2, UV2 / 16, 0)", "Color * sample_lightmap(Sampler2, UV2)")
        # 26.2 reverses depth: zero is now the far plane. Keep the control
        # pixel in front of scene geometry so the post pass receives it.
        particle = changed_once(particle,
            "corners[gl_VertexID % 4]) * markerSize, 0.0, 1.0)",
            "corners[gl_VertexID % 4]) * markerSize, 1.0, 1.0)")
        patches[particle_path] = particle.encode()

        # PostPass in 26.2 draws three vertices without a Position attribute.
        # Use the same procedural full-screen triangle as vanilla screenquad.
        blit_path = "assets/shader_selector/shaders/post/internal/blit.vsh"
        patches[blit_path] = client.read("assets/minecraft/shaders/core/screenquad.vsh")

        shake_path = "assets/shader_selector/shaders/post/shader.vsh"
        shake = source[shake_path].decode()
        shake = changed_once(shake, "in vec4 Position;", "// 26.2 post passes have no vertex buffer; use gl_VertexID below.")
        start = shake.index("    // REQUIRED Blit Copy Statement")
        end = shake.index("    float t = GameTime;", start)
        shake = shake[:start] + """    vec2 uv = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(uv * 2.0 - 1.0, 0.2, 1.0);
    texCoord = uv;

""" + shake[end:]
        patches[shake_path] = shake.encode()

        # GLSL 330 does not require the later line-continuation extension.
        # Flatten this macro without changing its marker channel definitions.
        marker_path = "assets/shader_selector/shaders/include/marker_settings.glsl"
        marker = source[marker_path].decode()
        marker = re.sub(r"\\\r?\n", " ", marker)
        patches[marker_path] = marker.encode()

        patches.update(sign_model_patches(client, source))
        patches.update(sky_shader_patches(source))
        # Speech lives in its own namespace. Existing sound events and assets
        # retain their exact bytes, including the v14 sky repair.
        speech_patches, speech_report = tts_patches(ROOT / "tts")
        if set(speech_patches) & (set(source) | set(patches)):
            raise ValueError("TTS overlay would overwrite an existing resource.")
        patches.update(speech_patches)

        chime_patches, intercom_report = intercom_patches(ROOT / "intercom")
        if set(chime_patches) & (set(source) | set(patches)):
            raise ValueError("Elevator audio overlay would overwrite an existing resource.")
        patches.update(chime_patches)
        turbine_assets, turbine_report = turbine_patches(ROOT / "turbines")
        if set(turbine_assets) & (set(source) | set(patches)):
            raise ValueError("Turbine audio overlay would overwrite an existing resource.")
        patches.update(turbine_assets)
        core_assets, core_report = core_audio_patches(ROOT / "core-audio", source)
        if set(core_assets) != CHANGED_FILES or set(core_assets) & set(patches):
            raise ValueError("Core mono overlay must replace only its six original recordings.")
        patches.update(core_assets)
        combined = {**source, **patches}
        with zipfile.ZipFile(PREVIOUS) as previous:
            previous_names = set(previous.namelist())
            previous_added = set(combined) - previous_names
            previous_removed = previous_names - set(combined)
            previous_changed = {
                name for name in previous_names & set(combined)
                if combined[name] != previous.read(name)
            }
            if (previous_added != EXPECTED_PREVIOUS_ADDED or previous_removed
                    or previous_changed != EXPECTED_PREVIOUS_CHANGED):
                raise ValueError(
                    "Only the six inherited stereo core recordings may change from published v21; no resources may be added or removed. "
                    f"Added: {sorted(previous_added)}; removed: {sorted(previous_removed)}; "
                    f"changed: {sorted(previous_changed)}"
                )

        for name, data in patches.items():
            destination = OVERRIDES / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as result:
            for name, data in {**source, **patches}.items():
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError(f"Unsafe archive path: {name}")
                info = zipfile.ZipInfo(name, date_time=(2026, 10, 14, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                result.writestr(info, patches.get(name, data))

        if OUTPUT.stat().st_size > MAX_PACK_BYTES:
            raise ValueError(f"Resource pack exceeds the plot's 40 MiB limit: {OUTPUT.stat().st_size} bytes")

        for name, data in combined.items():
            if name.endswith(".json") or name == "pack.mcmeta":
                json.loads(data)

        # Resolve imports from the output overlay and the matching official
        # client for a CPU-only GLSL compile; never launch a game/GL context.
        def expand(name, seen):
            if name in seen:
                return ""
            seen.add(name)
            data = combined.get(name)
            if data is None:
                data = client.read(name)
            text = data.decode()

            def include(match):
                identifier = match.group(1)
                namespace, path = identifier.split(":", 1) if ":" in identifier else ("minecraft", identifier)
                return expand(f"assets/{namespace}/shaders/include/{path}", seen)

            text = re.sub(r"#moj_import\s+<([^>]+)>", include, text)
            return re.sub(r"^\s*#version\s+\d+.*$", "", text, flags=re.MULTILINE)

        shaders = []
        VALIDATION.mkdir(parents=True, exist_ok=True)
        for name in combined:
            if name.endswith((".vsh", ".fsh")):
                path = VALIDATION / name.replace("/", "_")
                path.write_text("#version 330\n" + expand(name, set()), encoding="utf-8")
                shaders.append(path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(OUTPUT) as result:
            changed = [name for name, data in source.items() if result.read(name) != data]
            added = sorted(set(patches) - set(source))
            if set(changed) != set(patches) & set(source):
                raise AssertionError("Unexpected asset modification.")
            if set(result.namelist()) != set(source) | set(patches):
                raise AssertionError("An asset was lost or added unexpectedly.")
            if result.testzip() is not None:
                raise AssertionError("Output ZIP CRC check failed.")
        report = {
            "source": {"file": SOURCE.name, "gitBlob": EXPECTED_SOURCE_BLOB, "sha256": hashlib.sha256(source_bytes).hexdigest()},
            "targetMinecraft": version["id"], "resourceFormat": [88, 0],
            "output": OUTPUT.name, "sha1": hashlib.sha1(OUTPUT.read_bytes()).hexdigest(),
            "sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), "size": OUTPUT.stat().st_size,
            "sizeLimitBytes": MAX_PACK_BYTES, "remainingBytes": MAX_PACK_BYTES - OUTPUT.stat().st_size,
            "assets": len(combined) - 1, "changedFiles": changed, "addedFiles": added,
            "preservedFiles": len(source) - len(changed),
            "shaderFiles": shaders, "jsonFilesValidated": sum(name.endswith(".json") or name == "pack.mcmeta" for name in combined),
            "checks": {"sourceBlobMatched": True, "zipCrc": True, "assetSetPreserved": True, "unrelatedBytesPreserved": True},
            "tts": speech_report, "elevatorChime": intercom_report["chime"],
            "elevatorDoors": intercom_report["doors"],
            "turbines": turbine_report,
            "coreAudio": core_report,
            "previousPack": {"file": PREVIOUS.name, "sha256": EXPECTED_PREVIOUS_SHA256,
                             "preservedFiles": len(previous_names) - len(previous_changed),
                             "addedFiles": sorted(previous_added),
                             "changedFiles": sorted(previous_changed),
                             "bytesPreserved": not previous_changed,
                             "unrelatedBytesPreserved": True},
        }
        report_version = OUTPUT.stem.split("-", 1)[0].removeprefix("sp_")
        (ROOT / f"build-report-{report_version}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "shaderFiles"}, indent=2))
        return report


if __name__ == "__main__":
    build()
