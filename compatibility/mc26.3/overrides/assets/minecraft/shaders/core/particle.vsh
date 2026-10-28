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

vec2[] corners = vec2[](
    vec2(0.0, 1.0),
    vec2(0.0, 0.0),
    vec2(1.0, 0.0),
    vec2(1.0, 1.0)
);

void main() {
    // ShaderSelector
    iColor = ivec4(round(Color * 255.));
    isMarker = int(
        iColor.r == MARKER_RED
    );
    ivec2 markerPos = ivec2(0, 0);
    if (isMarker == 1) {
        isMarker = 0;
        #define ADD_MARKER(row, green, alpha, op, rate) if (ivec2(green, alpha) == iColor.ga) {isMarker = 1; markerPos = MARKER_POS(row);}
        LIST_MARKERS
    }
    if (isMarker == 1 && (markerPos.x+markerPos.y)%2 == 0) {
        vec2 markerSize = 2.0 / ScreenSize;

        gl_Position = vec4(-1 + (vec2(markerPos) + corners[gl_VertexIndex % 4]) * markerSize, 1.0, 1.0);

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
