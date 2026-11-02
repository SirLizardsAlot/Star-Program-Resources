#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>
#include <minecraft:sample_lightmap.glsl>

layout(location = 0) in vec3 Position;
layout(location = 1) in vec4 Color;
layout(location = 2) in vec2 UV0;
layout(location = 3) in ivec2 UV2;

#ifndef OIT_ALPHA_ONLY
uniform sampler2D Sampler2;
#endif

layout(location = 0) out float sphericalVertexDistance;
layout(location = 1) out float cylindricalVertexDistance;
layout(location = 2) out vec4 vertexColor;
layout(location = 3) out vec2 texCoord0;

layout(location = 4) out vec3 dfskyRay;

mat3 spSkyClipMatrix(mat4 projection) {
    // Rows x, y and w of the complete projection. Bobbing, hurt rotation and
    // other affine camera effects may be part of this matrix, not view alone.
    return mat3(
        vec3(projection[0][0], projection[0][1], projection[0][3]),
        vec3(projection[1][0], projection[1][1], projection[1][3]),
        vec3(projection[2][0], projection[2][1], projection[2][3]));
}

vec3 spSkyWorldRay(vec3 position, mat4 projection, mat4 view) {
    vec3 offset = vec3(projection[3][0], projection[3][1], projection[3][3]);
    // Ordinary projections have no shifted eye. Avoid matrix inverses in that
    // common case. An affine projection translation moves the virtual eye.
    if (all(equal(offset, vec3(0.0)))) return position;
    mat3 clip = spSkyClipMatrix(projection);
    vec3 eye = -inverse(clip) * offset;
    return position - inverse(mat3(view)) * eye;
}

void main() {
    vec3 pos = Position + ModelOffset;
    dfskyRay = spSkyWorldRay(pos, ProjMat, ModelViewMat);
    gl_Position = ProjMat * ModelViewMat * vec4(pos, 1.0);

    sphericalVertexDistance = fog_spherical_distance(pos);
    cylindricalVertexDistance = fog_cylindrical_distance(pos);
    #ifndef OIT_ALPHA_ONLY
    vertexColor = Color * sample_lightmap(Sampler2, UV2);
    #else
    vertexColor = Color;
    #endif
    texCoord0 = UV0;
}
