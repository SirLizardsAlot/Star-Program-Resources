#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>
#include <minecraft:globals.glsl>
#include <minecraft:sample_lightmap.glsl>

layout(location = 0) in vec3 Position;
layout(location = 1) in vec2 UV0;
layout(location = 2) in vec4 Color;
layout(location = 3) in ivec2 UV2;

uniform sampler2D Sampler2;

layout(location = 0) out float sphericalVertexDistance;
layout(location = 1) out float cylindricalVertexDistance;
layout(location = 2) out vec2 texCoord0;
layout(location = 3) out vec4 vertexColor;

// ShaderSelector
#include <shader_selector:marker_settings.glsl>

layout(location = 4) flat out int isMarker;
layout(location = 5) flat out ivec4 iColor;
layout(location = 6) flat out ivec2 spMarkerPixel;
layout(location = 7) flat out mat3 spCameraRotation;
layout(location = 10) flat out vec2 spCameraProjection;

vec2[] corners = vec2[](
    vec2(0.0, 1.0),
    vec2(0.0, 0.0),
    vec2(1.0, 0.0),
    vec2(1.0, 1.0)
);


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

    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

    sphericalVertexDistance = fog_spherical_distance(Position);
    cylindricalVertexDistance = fog_cylindrical_distance(Position);
    texCoord0 = UV0;
    vertexColor = Color * sample_lightmap(Sampler2, UV2);
}
