"""Replace the post-process recoil effect with held angular-FOV zoom.

The existing particle ring, camera metadata, sky renderer and legacy alarm /
shake controls remain intact. Native controls supply channel six from zero to
one. No core rendering sampler or client modification is introduced.
"""
from __future__ import annotations


SETTINGS = 'assets/shader_selector/shaders/include/marker_settings.glsl'
READER = 'assets/shader_selector/shaders/include/data_reader.glsl'
DATA = 'assets/shader_selector/shaders/post/data.fsh'
POST_VERTEX = 'assets/shader_selector/shaders/post/shader.vsh'
POST_FRAGMENT = 'assets/shader_selector/shaders/post/shader.fsh'
PARTICLE_VERTEX = 'assets/minecraft/shaders/core/particle.vsh'
HELPER = 'assets/star_program/shaders/include/zoom.glsl'


ZOOM_GLSL = '''#ifndef STAR_PROGRAM_ZOOM_GLSL
#define STAR_PROGRAM_ZOOM_GLSL

// Interpolate the player's current vertical field of view toward zero degrees.
// Uniformly cropping both image axes preserves its aspect ratio. The current
// projection supplies FOV changes from the player's own settings and effects.
float spZoomCropFactor(float projectionY, float strength) {
    float amount = !isnan(strength) && !isinf(strength)
        ? clamp(strength, 0.0, 1.0) : 0.0;
    if (amount == 0.0) return 1.0;
    if (amount == 1.0) return 0.0;
    if (isnan(projectionY) || isinf(projectionY) || projectionY <= 0.00001)
        return 1.0;
    float halfFov = atan(1.0 / projectionY);
    return tan((1.0 - amount) * halfFov) / tan(halfFov);
}

#endif
'''


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError('Expected exactly one zoom patch point: ' + old)
    return source.replace(old, new, 1)


def make_zoom(base: dict[str, bytes]) -> dict[str, bytes]:
    """Return only the seven resources needed to replace recoil with held zoom."""
    result: dict[str, bytes] = {}

    settings = base[SETTINGS].decode('utf-8')
    settings = replace_once(settings, '#define RECOIL_PITCH 6', '#define ZOOM_AMOUNT 6')
    settings = replace_once(settings, '#define RECOIL_YAW 7', '#define RESERVED_CONTROL 7')
    result[SETTINGS] = settings.encode()

    reader = base[READER].decode('utf-8')
    reader = replace_once(reader, 'ivec4(83, 80, 52, 3)', 'ivec4(83, 80, 90, 4)')
    reader = replace_once(reader,
        'if (channel == RECOIL_PITCH || channel == RECOIL_YAW) return 128.0 / 255.0;',
        'if (channel == ZOOM_AMOUNT || channel == RESERVED_CONTROL) return 0.0;')
    result[READER] = reader.encode()

    data = base[DATA].decode('utf-8')
    data = replace_once(data, 'vec4(83.0, 80.0, 52.0, 3.0)', 'vec4(83.0, 80.0, 90.0, 4.0)')
    data = replace_once(data,
        'else if (channel == RECOIL_PITCH || channel == RECOIL_YAW) value += (wanted - value) * (1.0 - exp(-45.0 * delta));',
        '''else if (channel == ZOOM_AMOUNT) {
        value += (wanted - value) * (1.0 - exp(-45.0 * delta));
        if (abs(wanted - value) < 0.000001) value = wanted;
    }''')
    result[DATA] = data.encode()

    vertex = base[POST_VERTEX].decode('utf-8')
    vertex = replace_once(vertex, '#include <star_program:recoil.glsl>',
                          '#include <star_program:zoom.glsl>')
    old_angle = '''float spAngleDegrees(float controlValue) {
    float value = controlValue * 255.0 - 128.0;
    return value * (value < 0.0 ? 8.0 / 128.0 : 8.0 / 127.0);
}
'''
    vertex = replace_once(vertex, old_angle, '')
    vertex = replace_once(vertex, 'layout(location = 1) flat out vec2 spProjection;\n', '')
    vertex = replace_once(vertex, 'layout(location = 5) flat out vec2 spAngles;\n', '')
    vertex = replace_once(vertex, '    spProjection = spProjectionScale();\n', '')
    vertex = replace_once(vertex, '''    spAngles = radians(vec2(spAngleDegrees(readChannel(RECOIL_PITCH)), spAngleDegrees(readChannel(RECOIL_YAW))));
    if (spHasCamera == 0) spAngles = vec2(0.0);
    spCrop = spRecoilCrop(spProjection, spAngles.x, spAngles.y);''',
        '    spCrop = spZoomCropFactor(spProjectionScale().y, readChannel(ZOOM_AMOUNT));')
    result[POST_VERTEX] = vertex.encode()

    fragment = base[POST_FRAGMENT].decode('utf-8')
    fragment = replace_once(fragment, '#include <star_program:recoil.glsl>\n', '')
    fragment = replace_once(fragment, 'layout(location = 1) flat in vec2 spProjection;\n', '')
    fragment = replace_once(fragment, 'layout(location = 5) flat in vec2 spAngles;\n', '')
    fragment = replace_once(fragment,
        'texCoord = spRecoilUV(baseTexCoord, spProjection, spAngles.x, spAngles.y, spCrop);',
        'texCoord = vec2(0.5) + (baseTexCoord - vec2(0.5)) * spCrop;')
    result[POST_FRAGMENT] = fragment.encode()

    particle = base[PARTICLE_VERTEX].decode('utf-8')
    particle = replace_once(particle,
        '''        } else if (iColor.r >= 0 && iColor.r < 128 && iColor.g >= 247 && iColor.g <= 250) {
            isMarker = 1;
            spMarkerPixel = SP_MARKER_POS(254 - iColor.g, iColor.r);
        }''',
        '''        } else if (iColor.r >= 0 && iColor.r < 128) {
            // Zoom uses new wire identities so lingering recoil markers cannot
            // reinterpret their old neutral byte as a half-strength zoom.
            int channel = 0;
            if (iColor.g == 250) channel = SKY_TIME_HIGH;
            else if (iColor.g == 249) channel = SKY_TIME_LOW;
            else if (iColor.g == 246) channel = ZOOM_AMOUNT;
            else if (iColor.g == 245) channel = RESERVED_CONTROL;
            if (channel != 0) {
                isMarker = 1;
                spMarkerPixel = SP_MARKER_POS(channel, iColor.r);
            }
        }''')
    particle = replace_once(particle,
        '            spCameraProjection = vec2(abs(ProjMat[0][0]), abs(ProjMat[1][1]));',
        '''            // Orthonormal view/bob rotations preserve column lengths.
            // Their ratio recovers the original focal scales even when bobbing
            // rotates the projection and changes its diagonal components.
            vec3 mapLengths = vec3(length(spCameraRotation[0]),
                length(spCameraRotation[1]), length(spCameraRotation[2]));
            spCameraProjection = all(greaterThan(mapLengths, vec3(0.0)))
                ? mapLengths.zz / mapLengths.xy : vec2(0.0);''')
    result[PARTICLE_VERTEX] = particle.encode()

    result[HELPER] = ZOOM_GLSL.encode()
    for name, contents in result.items():
        if b'RECOIL_' in contents or b'spRecoil' in contents or b'spAngles' in contents:
            raise ValueError('Obsolete recoil reference remains in ' + name)
    return result
