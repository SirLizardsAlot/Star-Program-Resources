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
