"""Derive the Sky Block terrain patch from the installed Sodium 26.3 shaders.

The original jar and the earlier Simulation DF plot are read-only. Generated
shader files use only Sodium's existing resource bindings. This does not launch
Minecraft, build a full resource pack, or publish anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
OVERRIDES = HERE / "overrides"
DEFAULT_JAR = (Path.home() / "AppData/Roaming/ModrinthApp/profiles/Fabric 26.2/mods"
               / "sodium-fabric-0.9.2+mc26.3.jar")
VERSION = "0.9.2+mc26.3"
VERTEX = "assets/sodium/shaders/blocks/block_layer_opaque.vsh"
FRAGMENT = "assets/sodium/shaders/blocks/block_layer_opaque.fsh"
INCLUDES = ("globals.glsl", "fog.glsl", "chunk_vertex.glsl", "chunk_material.glsl")


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("The installed Sodium source does not match the expected patch point: " + old)
    return source.replace(old, new, 1)


def write_generated(path: Path, content: bytes) -> None:
    # Repeating the generator is idempotent. Preserve any different existing
    # file so an edited generated shader cannot be silently overwritten.
    if path.exists() and path.read_bytes() != content:
        raise ValueError("Preserving differing existing generated file: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def prepare(jar_path: Path = DEFAULT_JAR) -> dict:
    with ZipFile(jar_path) as jar:
        metadata = json.loads(jar.read("fabric.mod.json"))
        if metadata["id"] != "sodium" or metadata["version"] != VERSION:
            raise ValueError("Expected Sodium " + VERSION)
        original = {name: jar.read(name) for name in (VERTEX, FRAGMENT)}
        vertex = original[VERTEX].decode("utf-8")
        fragment = original[FRAGMENT].decode("utf-8")
        notice = ("// Sky Block overlay: modified from Sodium " + VERSION
                  + ". See SODIUM-LICENSE.md.\n")
        vertex = replace_once(vertex, "#extension GL_ARB_separate_shader_objects : require\n",
                              "#extension GL_ARB_separate_shader_objects : require\n" + notice)
        vertex = replace_once(vertex, "layout(location = 1) out vec2 v_TexCoord;",
                              "layout(location = 1) out vec2 v_TexCoord;\n"
                              "layout(location = 6) out vec3 spSkyRay;")
        vertex = replace_once(vertex, "vec3 position = _vert_position + translation;",
                              "vec3 position = _vert_position + translation;\n"
                              "    // Sodium's region offset is relative to the camera. Keep the ray\n"
                              "    // in world axes so the sky remains level across all block faces.\n"
                              "    spSkyRay = position;")
        fragment = replace_once(fragment, "#version 460 core\n", "#version 460 core\n" + notice)
        fragment = replace_once(fragment, "#include <minecraft:oit.glsl>",
                                "#include <minecraft:oit.glsl>\n#include <dfsky:sky.glsl>")
        fragment = replace_once(fragment, "layout(location = 3) in float fadeFactor;",
                                "layout(location = 3) in float fadeFactor;\n"
                                "layout(location = 6) in vec3 spSkyRay;")
        fragment = replace_once(fragment, "void main() {", """void main() {
    float spCloudOffset;
    if (dfsky_marker(u_BlockTex, v_TexCoord, spCloudOffset)) {
        // This opaque marker texture keeps red glazed terracotta in SOLID.
        // Its normal depth still occludes geometry behind the block. Alpha
        // carries the sky visibility mask for the later controlled sky pass.
        #ifdef OIT_ALPHA_ONLY
        executeAlphaOnlyPhase(gl_FragCoord.z, 1.0);
        #else
        // Sodium does not bind Minecraft's GameTime here. This exact static
        // noon baseline matches vanilla terrain and the post-pass subtraction.
        // The post pass supplies selected time and animated cloud drift.
        fragColor = vec4(dfsky_render(spSkyRay, 0.0), 0.0);
        #endif
        return;
    }
""")
        generated = {VERTEX: vertex.encode(), FRAGMENT: fragment.encode()}
        for name in INCLUDES:
            identifier = "assets/sodium/shaders/include/" + name
            generated[identifier] = jar.read(identifier)
        license_text = jar.read("LICENSE.md")

    # The namespace renderer is supplied by prepare_sky.py. No additional
    # samplers, uniform blocks, or push constants are introduced by this patch.
    for path, content in generated.items():
        write_generated(OVERRIDES / path, content)
    write_generated(OVERRIDES / "SODIUM-LICENSE.md", license_text)
    return {
        "sodiumVersion": VERSION,
        "sourceJar": str(jar_path.resolve()),
        "sourceJarSHA256": hashlib.sha256(jar_path.read_bytes()).hexdigest(),
        "sourceShaders": {name: hashlib.sha256(content).hexdigest()
                          for name, content in original.items()},
        "generatedFiles": sorted([*generated, "SODIUM-LICENSE.md"]),
        "additionalResourceBindings": [],
        "skyBaseline": {"timeTicks": 6000, "cloudOffset": 0.0, "outputAlpha": 0.0},
        "markerRGBA": [17, 239, 173, 255],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=DEFAULT_JAR)
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.jar), indent=2))
