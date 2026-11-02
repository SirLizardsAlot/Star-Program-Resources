"""Remove large shader constants and move frame-uniform sky work to vertices.

This module only returns scoped resource replacements. The caller supplies the
matching texture-backed vanilla_data.glsl and data PNGs, and binds the static
SkyData texture in the post chain. No Minecraft or publication is performed.
"""
from __future__ import annotations

import re


SKY = 'assets/dfsky/shaders/include/sky.glsl'
SETTINGS = 'assets/dfsky/shaders/include/settings.glsl'
POST = 'assets/shader_selector/shaders/post/shader.'


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError('Expected exactly one shader patch point: ' + old)
    return source.replace(old, new, 1)


def noon_constructor(settings: str) -> str:
    """Retain the exact original fixed-noon initializer, including rounding."""
    match = re.search(r'DfSkyState\s+dfskyState\s*=\s*(DfSkyState\s*\()', settings)
    if not match:
        raise ValueError('Missing fixed-noon DfSkyState initializer')
    start = match.start(1)
    opening = settings.index('(', match.start(1))
    depth = 0
    for index in range(opening, len(settings)):
        depth += (settings[index] == '(') - (settings[index] == ')')
        if depth == 0:
            if not settings[index + 1:].lstrip().startswith(';'):
                raise ValueError('Unexpected fixed-noon initializer terminator')
            return settings[start:index + 1]
    raise ValueError('Unclosed fixed-noon DfSkyState initializer')


MARKER = '''bool dfsky_marker(sampler2D atlas, vec2 uv, out float cloudOffset) {
    // The marker's RG bytes are its integer offset inside the marker region.
    // Subtract them to find this sprite anywhere in the block atlas. This does
    // not assume any alignment for this 256 by 128 pixel atlas sprite.
    ivec2 size = textureSize(atlas, 0);
    ivec2 pixel = clamp(ivec2(uv * vec2(size)), ivec2(0), size - 1);
    ivec4 c = ivec4(round(texelFetch(atlas, pixel, 0) * 255.0));
    cloudOffset = 0.0;
    if (c.b != 173 || c.a != 255 || any(lessThan(c.rg, ivec2(0)))
        || any(greaterThanEqual(c.rg, ivec2(16)))) return false;
    ivec2 origin = pixel - c.rg;
    if (any(lessThan(origin, ivec2(0)))
        || any(greaterThan(origin + ivec2(256, 128), size))) return false;
    ivec4 headerA = ivec4(round(texelFetch(atlas, origin + ivec2(16, 0), 0) * 255.0));
    ivec4 headerB = ivec4(round(texelFetch(atlas, origin + ivec2(17, 0), 0) * 255.0));
    if (any(notEqual(headerA, ivec4(17, 239, 173, 255)))
        || any(notEqual(headerB, ivec4(91, 37, 211, 255)))) return false;
    dfskyDataOrigin = origin;
    return true;
}
'''


def make_shaders(base: dict[str, bytes]) -> dict[str, bytes]:
    """Return the sky include, two post stages and four geometry fragments."""
    result: dict[str, bytes] = {}
    sky = base[SKY].decode('utf-8')
    sky = replace_once(sky, '#include <dfsky:runtime.glsl>',
                       '#ifdef DFSKY_RUNTIME\n#include <dfsky:runtime.glsl>\n#endif')
    start = sky.index('bool dfsky_marker(')
    end = sky.index('float dfsky_stars(', start)
    sky = sky[:start] + MARKER + '\n' + sky[end:]
    result[SKY] = sky.encode()

    # Geometry already has the atlas binding. Declare it before the shared sky
    # functions so texture-backed data adds no sampler or uniform requirement.
    geometry = [(f'assets/minecraft/shaders/core/{kind}.fsh', 'Sampler0')
                for kind in ('terrain', 'block', 'item')]
    geometry.append(('assets/sodium/shaders/blocks/block_layer_opaque.fsh', 'u_BlockTex'))
    for name, sampler in geometry:
        source = base[name].decode('utf-8')
        pattern = r'^uniform sampler2D ' + re.escape(sampler) + r';[^\r\n]*(?:\r?\n|$)'
        source, count = re.subn(pattern, '', source, flags=re.MULTILINE)
        if count != 1:
            raise ValueError('Expected exactly one existing atlas sampler: ' + name)
        source = replace_once(source, '#include <dfsky:sky.glsl>',
            f'uniform sampler2D {sampler};\n#define DFSKY_SAMPLER {sampler}\n#include <dfsky:sky.glsl>')
        result[name] = source.encode()

    vertex = base[POST + 'vsh'].decode('utf-8')
    vertex = replace_once(vertex, '#include <star_program:recoil.glsl>',
        '#include <star_program:recoil.glsl>\n#define DFSKY_RUNTIME 1\n'
        '#include <dfsky:settings.glsl>\n#include <dfsky:runtime.glsl>')
    vertex = replace_once(vertex, 'layout(location = 8) flat out int spHasCamera;', '''layout(location = 8) flat out int spHasCamera;
// All selected-time fields are constant across this full-screen triangle.
layout(location = 9) flat out vec4 spSkyA;
layout(location = 10) flat out vec4 spSkyB;
layout(location = 11) flat out vec4 spSkyC;
layout(location = 12) flat out vec4 spSkyD;''')
    vertex = replace_once(vertex, '    spTime = spSkyTime();', '''    spTime = spSkyTime();
    dfsky_setTime(spTime);
    spSkyA = vec4(dfskyState.sunAngle, dfskyState.starBrightness, dfskyState.skyColor.rg);
    spSkyB = vec4(dfskyState.skyColor.b, dfskyState.fogColor);
    spSkyC = dfskyState.cloudColor;
    spSkyD = dfskyState.sunsetColor;''')
    result[POST + 'vsh'] = vertex.encode()

    fragment = base[POST + 'fsh'].decode('utf-8')
    fragment = replace_once(fragment, '#include <dfsky:sky.glsl>',
        'uniform sampler2D SkyDataSampler;\n#define DFSKY_SAMPLER SkyDataSampler\n#include <dfsky:sky.glsl>')
    fragment = replace_once(fragment, 'layout(location = 8) flat in int spHasCamera;', '''layout(location = 8) flat in int spHasCamera;
layout(location = 9) flat in vec4 spSkyA;
layout(location = 10) flat in vec4 spSkyB;
layout(location = 11) flat in vec4 spSkyC;
layout(location = 12) flat in vec4 spSkyD;''')
    helper = 'DfSkyState spNoonState() {\n    return ' + noon_constructor(base[SETTINGS].decode('utf-8')) + ';\n}\n\n'
    fragment = replace_once(fragment, 'vec4 spScene(vec2 uv) {', helper + 'vec4 spScene(vec2 uv) {')
    fragment = replace_once(fragment, '        dfsky_setTime(6000.0);',
                            '        dfskyState = spNoonState();')
    fragment = replace_once(fragment, '        dfsky_setTime(spTime);',
        '        dfskyState = DfSkyState(spTime, spSkyA.x, spSkyA.y,\n'
        '            vec3(spSkyA.zw, spSkyB.x), spSkyB.yzw, spSkyC, spSkyD);')
    if 'dfsky_setTime(' in fragment or '#define DFSKY_RUNTIME' in fragment:
        raise ValueError('Per-fragment time calculation remains')
    result[POST + 'fsh'] = fragment.encode()
    return result
