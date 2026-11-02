#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:oit.glsl>

uniform sampler2D Sampler0;

layout(location = 0) in float sphericalVertexDistance;
layout(location = 1) in float cylindricalVertexDistance;
layout(location = 2) in vec2 texCoord0;
layout(location = 3) in vec4 vertexColor;

layout(location = 4) flat in int isMarker;
layout(location = 5) flat in ivec4 iColor;
layout(location = 6) flat in ivec2 spMarkerPixel;
layout(location = 7) flat in mat3 spCameraRotation;
layout(location = 10) flat in vec2 spCameraProjection;

#ifndef OIT_ALPHA_ONLY
layout(location = 0) out vec4 fragColor;
#endif

vec4 calculateFinalColor(vec4 color) {
    #ifdef OIT_ACCUMULATE
    color = sampleColorForAccumulation(color);
    vec4 fogColor = vec4(FogColor.rgb * color.a, FogColor.a);
    #else
    vec4 fogColor = FogColor;
    #endif
    return apply_fog(color, sphericalVertexDistance, cylindricalVertexDistance, FogEnvironmentalStart, FogEnvironmentalEnd, FogRenderDistanceStart, FogRenderDistanceEnd, fogColor);
}


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
    vec4 color = texture(Sampler0, texCoord0) * vertexColor * ColorModulator;
    if (color.a < 0.1) {
        discard;
    }
    #ifdef OIT_ALPHA_ONLY
    executeAlphaOnlyPhase(gl_FragCoord.z, color.a);
    #else
    fragColor = calculateFinalColor(color);
    #endif
}
