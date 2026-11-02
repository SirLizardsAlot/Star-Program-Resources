"""Build particle control transport without changing unrelated pack entries.

New marker generations occupy separate pixels because entity-effect particles
retain their vanilla lifetime. Their sequence selects the freshest generation,
so old particle quads cannot average a later target's payload.
"""
from __future__ import annotations

import math


PREFIX = 'assets/shader_selector/shaders/'
PARTICLE = 'assets/minecraft/shaders/core/particle.'

SETTINGS = r'''
// Legacy marker identities remain unchanged.
#define SCREENSHAKE_FREQUENCY 1
#define SCREENSHAKE_MAGNITUDE 2
#define ALARM_EFFECTS 3
#define SKY_TIME_HIGH 4
#define SKY_TIME_LOW 5
#define RECOIL_PITCH 6
#define RECOIL_YAW 7
#define SP_CHANNEL_COUNT 7
#define MARKER_RED 254
#define LIST_MARKERS ADD_MARKER(SCREENSHAKE_FREQUENCY,253,0,1,10) ADD_MARKER(SCREENSHAKE_MAGNITUDE,252,0,1,10) ADD_MARKER(ALARM_EFFECTS,251,0,0,10)
#define MARKER_POS(k) (ivec2(2*int(ceil(sqrt(float(k)))-1.0),0)+(k-int((ceil(sqrt(float(k)))-1.0)*(ceil(sqrt(float(k)))-1.0))-1)*ivec2(-1,1))
#define SP_MARKER_POS(channel,sequence) ivec2(40+(sequence)%64,((channel)-4)*2+(sequence)/64)
'''.lstrip()

READER = r'''
const float CONTROL_PERIOD = 1200.0;
const float CONTROL_TIMEOUT = 0.4;
const float SP_REBASE_TIMEOUT = 2.5;

bool controlFiniteUnit(float value) {
    return !isnan(value) && !isinf(value) && value >= 0.0 && value <= 1.0;
}
bool controlFiniteTime(float value) {
    return !isnan(value) && !isinf(value) && value >= 0.0 && value < CONTROL_PERIOD;
}
float controlElapsed(float now, float previous) {
    return mod(now - previous + CONTROL_PERIOD, CONTROL_PERIOD);
}
float controlNeutral(int channel) {
    if (channel == ALARM_EFFECTS) return 0.0;
    if (channel == SKY_TIME_HIGH) return 23.0 / 255.0;
    if (channel == SKY_TIME_LOW) return 112.0 / 255.0;
    if (channel == RECOIL_PITCH || channel == RECOIL_YAW) return 128.0 / 255.0;
    return 1.0;
}
bool controlStateValid() {
    ivec4 header = ivec4(round(texelFetch(DataSampler, ivec2(4, 0), 0) * 255.0));
    return all(equal(header, ivec4(83, 80, 51, 2)));
}
float readChannel(int channel) {
    if (channel < 1 || channel > SP_CHANNEL_COUNT) return 0.0;
    if (!controlStateValid()) return controlNeutral(channel);
    float value = decodeColor(texelFetch(DataSampler, ivec2(4, channel), 0));
    return controlFiniteUnit(value) ? value : controlNeutral(channel);
}
ivec4 spCameraCell(int index) {
    return ivec4(round(texelFetch(DataSampler, ivec2(index % 5, 8 + index / 5), 0) * 255.0));
}
float spCameraByte(int index) { return float(spCameraCell(index).b); }
float spCameraWord(int component) {
    return spCameraByte(component * 2) * 256.0 + spCameraByte(component * 2 + 1);
}
vec2 spProjectionScale() {
    return vec2(spCameraWord(9), spCameraWord(10)) * (16.0 / 65535.0);
}
mat3 spWorldFromView() {
    mat3 result;
    for (int column = 0; column < 3; ++column)
        for (int row = 0; row < 3; ++row)
            result[column][row] = spCameraWord(column * 3 + row) * (2.0 / 65535.0) - 1.0;
    return result;
}
bool spCameraValid() {
    if (!controlStateValid()) return false;
    for (int index = 0; index < 23; ++index) {
        ivec4 wire = spCameraCell(index);
        if (wire.r != 255 || wire.g != 0 || wire.a != 255) return false;
    }
    if (spCameraCell(22).b != 171) return false;
    vec2 scale = spProjectionScale();
    if (any(lessThan(scale, vec2(0.05))) || any(greaterThanEqual(scale, vec2(16.0)))) return false;
    mat3 rotation = spWorldFromView();
    for (int column = 0; column < 3; ++column)
        if (abs(dot(rotation[column], rotation[column]) - 1.0) > 0.05) return false;
    return abs(determinant(rotation) - 1.0) < 0.05;
}
float spSkyTime() {
    if (!controlStateValid()) return 6000.0;
    float value = decodeColor(texelFetch(DataSampler, ivec2(4, 13), 0));
    return !isnan(value) && !isinf(value) && value >= 0.0 && value < 24000.0 ? value : 6000.0;
}
'''.lstrip()

VERTEX_MARKERS = r'''
void main() {
    iColor = ivec4(round(Color * 255.0));
    isMarker = 0;
    spMarkerPixel = ivec2(0);
    spCameraRotation = mat3(1.0);
    spCameraProjection = vec2(1.0);
    if (iColor.a == 0) {
        if (iColor.r == MARKER_RED) {
            if (iColor.g == 253) { isMarker = 1; spMarkerPixel = MARKER_POS(1); }
            if (iColor.g == 252) { isMarker = 1; spMarkerPixel = MARKER_POS(2); }
            if (iColor.g == 251) { isMarker = 1; spMarkerPixel = MARKER_POS(3); }
        } else if (iColor.r >= 0 && iColor.r < 128 && iColor.g >= 247 && iColor.g <= 250) {
            isMarker = 1;
            spMarkerPixel = SP_MARKER_POS(254 - iColor.g, iColor.r);
        }
    }
    if (isMarker == 1) {
        // All marker quads share current-frame camera metadata. Only their
        // individual control pixel differs. Fragments outside these are cut.
        spCameraRotation = inverse(mat3(ModelViewMat));
        spCameraProjection = vec2(abs(ProjMat[0][0]), abs(ProjMat[1][1]));
        vec2 pixel = corners[gl_VertexIndex % 4] * vec2(104.0, 8.0);
        gl_Position = vec4(-1.0 + pixel * (2.0 / ScreenSize), 1.0, 1.0);
        sphericalVertexDistance = 0.0;
        cylindricalVertexDistance = 0.0;
        texCoord0 = vec2(0.0);
        vertexColor = vec4(0.0);
        return;
    }
    // Vanilla code
'''

FRAGMENT_METADATA = r'''
int spMetadataByte(int index) {
    if (index == 22) return 171;
    int component = index / 2;
    float value = component < 9
        ? spCameraRotation[component / 3][component % 3] * 0.5 + 0.5
        : spCameraProjection[component - 9] / 16.0;
    int word = int(round(clamp(value, 0.0, 1.0) * 65535.0));
    return index % 2 == 0 ? word / 256 : word % 256;
}

void main() {
    if (isMarker == 1) {
        ivec2 pixel = ivec2(gl_FragCoord.xy);
        bool metadata = pixel.y >= 0 && pixel.y < 8 && pixel.x >= 8 && pixel.x <= 30;
        if (!metadata && any(notEqual(pixel, spMarkerPixel))) discard;
        // Binary bitplanes survive arbitrary identical half-float overlaps.
        // Sending complete bytes here would drift in the OIT accumulation.
        int payload = metadata ? ((spMetadataByte(pixel.x - 8) >> pixel.y) & 1) * 255 : iColor.b;
        #ifdef OIT_ALPHA_ONLY
        executeAlphaOnlyPhase(gl_FragCoord.z, 1.0);
        #else
        vec4 markerColor = vec4(1.0, 0.0, float(payload) / 255.0, 1.0);
        #ifdef OIT_ACCUMULATE
        markerColor = sampleColorForAccumulation(markerColor);
        #endif
        fragColor = markerColor;
        #endif
        return;
    }
'''

DATA = r'''
#version 330
#extension GL_ARB_separate_shader_objects : require
#include <shader_selector:marker_settings.glsl>
#include <shader_selector:utils.glsl>
uniform sampler2D ParticlesSampler;
uniform sampler2D DataSampler;
#include <minecraft:globals.glsl>
#include <shader_selector:data_reader.glsl>
layout(location = 0) out vec4 fragColor;

bool spWireValid(ivec4 wire) { return wire.r == 255 && wire.g == 0 && wire.a == 255; }
ivec4 spWire(ivec2 pixel) {
    ivec2 size = textureSize(ParticlesSampler, 0);
    if (any(lessThan(pixel, ivec2(0))) || any(greaterThanEqual(pixel, size))) return ivec4(0);
    return ivec4(round(texelFetch(ParticlesSampler, pixel, 0) * 255.0));
}
ivec4 spMetadataWire(int index) {
    int value = 0;
    for (int bit = 0; bit < 8; ++bit) {
        ivec4 wire = spWire(ivec2(8 + index, bit));
        if (!spWireValid(wire) || wire.b != 0 && wire.b != 255) return ivec4(0);
        if (wire.b == 255) value += 1 << bit;
    }
    return ivec4(255, 0, value, 255);
}
bool spValidSequence(float sequence) {
    return !isnan(sequence) && !isinf(sequence) && sequence >= 0.0 && sequence < 128.0 && sequence == floor(sequence);
}
struct SpMarker { bool fresh; int sequence; int payload; };
SpMarker spNewest(int channel, bool anchored, int oldSequence) {
    SpMarker result = SpMarker(false, oldSequence, 0);
    int bestDistance = 0;
    for (int sequence = 0; sequence < 128; ++sequence) {
        ivec4 wire = spWire(SP_MARKER_POS(channel, sequence));
        if (!spWireValid(wire)) continue;
        if (anchored) {
            int distance = (sequence - oldSequence + 128) % 128;
            if (distance >= 1 && distance <= 64 && distance > bestDistance) {
                result = SpMarker(true, sequence, wire.b);
                bestDistance = distance;
            }
        } else if (!result.fresh || (sequence - result.sequence + 128) % 128 <= 64) {
            result = SpMarker(true, sequence, wire.b);
        }
    }
    return result;
}

void spTimeRow(ivec2 cell, bool initialized, float now, float delta) {
    float oldTarget = decodeColor(texelFetch(DataSampler, ivec2(0, 13), 0));
    float lastSeen = decodeColor(texelFetch(DataSampler, ivec2(1, 13), 0));
    float oldSequence = decodeColor(texelFetch(DataSampler, ivec2(2, 13), 0));
    bool remembered = initialized && oldTarget >= 0.0 && oldTarget < 24000.0
        && controlFiniteTime(lastSeen) && spValidSequence(oldSequence)
        && controlElapsed(now, lastSeen) <= SP_REBASE_TIMEOUT;
    SpMarker high = spNewest(SKY_TIME_HIGH, remembered, remembered ? int(oldSequence) : 0);
    SpMarker low = spNewest(SKY_TIME_LOW, remembered, remembered ? int(oldSequence) : 0);
    bool fresh = high.fresh && low.fresh && high.sequence == low.sequence;
    float target = fresh ? mod(float(high.payload * 256 + low.payload), 24000.0) : (remembered ? oldTarget : 6000.0);
    bool live = fresh || remembered && controlElapsed(now, lastSeen) <= CONTROL_TIMEOUT;
    float wanted = live ? target : 6000.0;
    float oldValue = decodeColor(texelFetch(DataSampler, ivec2(4, 13), 0));
    float value = initialized && !isnan(oldValue) && !isinf(oldValue) && oldValue >= 0.0 && oldValue < 24000.0 ? oldValue : 6000.0;
    float difference = mod(wanted - value + 12000.0, 24000.0) - 12000.0;
    value = mod(value + clamp(difference, -48000.0 * delta, 48000.0 * delta) + 24000.0, 24000.0);
    if (cell.x == 0) fragColor = encodeFloat(target);
    else if (cell.x == 1) fragColor = encodeFloat(fresh ? now : (remembered ? lastSeen : 0.0));
    else if (cell.x == 2) fragColor = encodeFloat(float(fresh ? high.sequence : (remembered ? int(oldSequence) : -1)));
    else if (cell.x == 3) fragColor = encodeFloat(0.0);
    else fragColor = encodeFloat(value);
}

void main() {
    ivec2 cell = ivec2(gl_FragCoord.xy);
    float now = GameTime * CONTROL_PERIOD;
    if (!controlFiniteTime(now)) now = 0.0;
    if (cell.y == 0) {
        fragColor = cell.x == 4 ? vec4(83.0, 80.0, 51.0, 2.0) / 255.0 : encodeFloat(now);
        return;
    }
    if (cell.y >= 8 && cell.y <= 12) {
        int index = (cell.y - 8) * 5 + cell.x;
        ivec4 header = spMetadataWire(22);
        bool headerValid = spWireValid(header) && header.b == 171;
        ivec4 wire = index < 23 ? spMetadataWire(index) : ivec4(0);
        fragColor = headerValid && spWireValid(wire) ? vec4(wire) / 255.0 : vec4(0.0);
        return;
    }
    bool initialized = controlStateValid();
    float previousTime = decodeColor(texelFetch(DataSampler, ivec2(0, 0), 0));
    initialized = initialized && controlFiniteTime(previousTime);
    float delta = initialized ? min(controlElapsed(now, previousTime), 1.0) : 0.0;
    if (cell.y == 13) { spTimeRow(cell, initialized, now, delta); return; }
    int channel = cell.y;
    int operation = channel == ALARM_EFFECTS || channel == SKY_TIME_HIGH || channel == SKY_TIME_LOW ? 0 : 1;
    ivec4 previous = ivec4(round(texelFetch(DataSampler, ivec2(0, channel), 0) * 255.0));
    float lastSeen = decodeColor(texelFetch(DataSampler, ivec2(1, channel), 0));
    float oldSequence = decodeColor(texelFetch(DataSampler, ivec2(2, channel), 0));
    bool headerValid = initialized && previous.r == MARKER_RED && previous.g == operation && previous.a == 255 && controlFiniteTime(lastSeen);
    bool remembered = headerValid && controlElapsed(now, lastSeen) <= SP_REBASE_TIMEOUT;
    SpMarker marker = SpMarker(false, 0, 0);
    if (channel <= ALARM_EFFECTS) {
        ivec4 wire = spWire(MARKER_POS(channel));
        marker = SpMarker(spWireValid(wire), 0, wire.b);
    } else {
        remembered = remembered && spValidSequence(oldSequence);
        marker = spNewest(channel, remembered, remembered ? int(oldSequence) : 0);
    }
    bool live = marker.fresh || remembered && controlElapsed(now, lastSeen) <= CONTROL_TIMEOUT;
    float target = marker.fresh ? float(marker.payload) / 255.0 : (remembered ? float(previous.b) / 255.0 : controlNeutral(channel));
    float wanted = live ? target : controlNeutral(channel);
    float oldValue = decodeColor(texelFetch(DataSampler, ivec2(4, channel), 0));
    float value = initialized && controlFiniteUnit(oldValue) ? oldValue : controlNeutral(channel);
    if (operation == 0) value = wanted;
    else if (channel == RECOIL_PITCH || channel == RECOIL_YAW) value += (wanted - value) * (1.0 - exp(-45.0 * delta));
    else value += clamp(wanted - value, -10.0 * min(delta, 0.1), 10.0 * min(delta, 0.1));
    bool keep = marker.fresh || remembered;
    if (cell.x == 0) fragColor = keep ? vec4(float(MARKER_RED), float(operation), round(target * 255.0), 255.0) / 255.0 : vec4(0.0);
    else if (cell.x == 1) fragColor = encodeFloat(marker.fresh ? now : (remembered ? lastSeen : 0.0));
    else if (cell.x == 2) fragColor = encodeFloat(float(marker.fresh ? marker.sequence : (remembered && spValidSequence(oldSequence) ? int(oldSequence) : -1)));
    else if (cell.x == 3) fragColor = encodeFloat(live ? 1.0 : 0.0);
    else fragColor = encodeFloat(clamp(value, 0.0, 1.0));
}
'''.lstrip()

CLEANUP = r'''
#version 330
#extension GL_ARB_separate_shader_objects : require
#include <shader_selector:marker_settings.glsl>
uniform sampler2D ParticlesSampler;
layout(std140) uniform SamplerInfo { vec2 OutSize; vec2 InSize; };
layout(location = 0) in vec2 texCoord;
layout(location = 0) out vec4 fragColor;
void main() {
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    fragColor = texelFetch(ParticlesSampler, pixel, 0);
    ivec4 wire = ivec4(round(fragColor * 255.0));
    if (wire.r != 255 || wire.g != 0 || wire.a != 255) return;
    bool legacy = all(equal(pixel, MARKER_POS(1))) || all(equal(pixel, MARKER_POS(2))) || all(equal(pixel, MARKER_POS(3)));
    bool metadata = pixel.y >= 0 && pixel.y < 8 && pixel.x >= 8 && pixel.x <= 30;
    bool ring = pixel.x >= 40 && pixel.x < 104 && pixel.y >= 0 && pixel.y < 8;
    ivec2 source = pixel;
    if (legacy) source.x += 1;
    else if (metadata) source.y = 8;
    else if (ring) source.y = 8;
    else return;
    source = clamp(source, ivec2(0), textureSize(ParticlesSampler, 0) - 1);
    fragColor = texelFetch(ParticlesSampler, source, 0);
}
'''.lstrip()


def make_transport(base: dict[str, bytes]) -> dict[str, bytes]:
    """Return only the six particle/control shader resources being replaced."""
    vertex = base[PARTICLE + 'vsh'].decode('utf-8')
    fragment = base[PARTICLE + 'fsh'].decode('utf-8')
    vertex_anchor = 'layout(location = 5) flat out ivec4 iColor;'
    fragment_anchor = 'layout(location = 5) flat in ivec4 iColor;'
    if vertex_anchor not in vertex or fragment_anchor not in fragment:
        raise ValueError('Particle stage interface differs from the pinned 26.3 pack')
    vertex = vertex.replace(vertex_anchor, vertex_anchor + '\nlayout(location = 6) flat out ivec2 spMarkerPixel;\nlayout(location = 7) flat out mat3 spCameraRotation;\nlayout(location = 10) flat out vec2 spCameraProjection;')
    fragment = fragment.replace(fragment_anchor, fragment_anchor + '\nlayout(location = 6) flat in ivec2 spMarkerPixel;\nlayout(location = 7) flat in mat3 spCameraRotation;\nlayout(location = 10) flat in vec2 spCameraProjection;')
    start, end = vertex.index('void main()'), vertex.index('// Vanilla code')
    vertex = vertex[:start] + VERTEX_MARKERS + vertex[end + len('// Vanilla code'):]
    start = fragment.index('void main()')
    normal = fragment.index('    vec4 color = texture(Sampler0, texCoord0) * vertexColor * ColorModulator;', start)
    fragment = fragment[:start] + FRAGMENT_METADATA + fragment[normal:]
    return {
        PARTICLE + 'vsh': vertex.encode(), PARTICLE + 'fsh': fragment.encode(),
        PREFIX + 'include/marker_settings.glsl': SETTINGS.encode(),
        PREFIX + 'include/data_reader.glsl': READER.encode(),
        PREFIX + 'post/data.fsh': DATA.encode(),
        PREFIX + 'post/internal/remove_particles.fsh': CLEANUP.encode(),
    }


def newest(visible: dict[int, int], old_sequence: int | None = None):
    """CPU model of the exact bounded shader sequence-selection loop."""
    result = None
    best_distance = 0
    for sequence in range(128):
        if sequence not in visible:
            continue
        if old_sequence is not None:
            distance = (sequence - old_sequence) % 128
            if 1 <= distance <= 64 and distance > best_distance:
                result, best_distance = (sequence, visible[sequence]), distance
        elif result is None or (sequence - result[0]) % 128 <= 64:
            result = sequence, visible[sequence]
    return result


def control_step(channel, state, visible, now, delta):
    """Small model for sequence freshness, timeout and neutral verification."""
    neutral = {1: 1., 2: 1., 3: 0., 4: 23 / 255, 5: 112 / 255, 6: 128 / 255, 7: 128 / 255}[channel]
    remembered = state is not None and (now - state['seen']) % 1200 <= 2.5
    selected = newest(visible, state['sequence'] if remembered else None)
    target = selected[1] / 255 if selected else state['target'] if remembered else neutral
    seen = now if selected else state['seen'] if remembered else 0.
    live = selected is not None or remembered and (now - seen) % 1200 <= .4
    wanted = target if live else neutral
    value = state['value'] if state else neutral
    if channel in [3, 4, 5]: value = wanted
    elif channel in [6, 7]: value += (wanted - value) * (1 - math.exp(-45 * delta))
    else: value += max(-10 * min(delta, .1), min(10 * min(delta, .1), wanted - value))
    return {'sequence': selected[0] if selected else state['sequence'] if remembered else -1,
            'target': target, 'seen': seen, 'value': value, 'live': live}
