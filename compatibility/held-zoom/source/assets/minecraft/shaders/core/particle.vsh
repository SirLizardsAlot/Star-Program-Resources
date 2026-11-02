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


mat3 spSkyClipMatrix(mat4 projection) {
    // Rows x, y and w of the complete projection. Bobbing, hurt rotation and
    // other affine camera effects may be part of this matrix, not view alone.
    return mat3(
        vec3(projection[0][0], projection[0][1], projection[0][3]),
        vec3(projection[1][0], projection[1][1], projection[1][3]),
        vec3(projection[2][0], projection[2][1], projection[2][3]));
}

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
        } else if (iColor.r >= 0 && iColor.r < 128) {
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
        }
    }
    if (isMarker == 1) {
        bool carrier = iColor.r == MARKER_RED && iColor.g == 253;
        vec2 pixel;
        if (carrier) {
            // Send current-frame rays only once per marker set. Map NDC x/y/1
            // directly to world direction, including projection-side bobbing.
            mat3 clip = spSkyClipMatrix(ProjMat);
            mat3 map = inverse(mat3(ModelViewMat)) * inverse(clip);
            vec3 maximum = max(max(abs(map[0]), abs(map[1])), abs(map[2]));
            float scale = max(max(maximum.x, maximum.y), maximum.z);
            spCameraRotation = !isnan(scale) && !isinf(scale) && scale > 0.0
                ? map / scale : mat3(0.0);
            // Orthonormal view/bob rotations preserve column lengths.
            // Their ratio recovers the original focal scales even when bobbing
            // rotates the projection and changes its diagonal components.
            vec3 mapLengths = vec3(length(spCameraRotation[0]),
                length(spCameraRotation[1]), length(spCameraRotation[2]));
            spCameraProjection = all(greaterThan(mapLengths, vec3(0.0)))
                ? mapLengths.zz / mapLengths.xy : vec2(0.0);
            pixel = corners[gl_VertexIndex % 4] * vec2(40.0, 8.0);
        } else {
            // Every non-carrier covers only its control pixel. Previously all
            // seven particles covered 104 by 8 pixels in every OIT phase.
            pixel = vec2(spMarkerPixel) + corners[gl_VertexIndex % 4];
        }
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
