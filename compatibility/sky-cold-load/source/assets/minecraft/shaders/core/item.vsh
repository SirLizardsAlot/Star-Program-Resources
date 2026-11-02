#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:light.glsl>
#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>
#include <minecraft:sample_lightmap.glsl>

layout(location = 0) in vec3 Position;
layout(location = 1) in vec4 Color;
layout(location = 2) in vec2 UV0;
layout(location = 3) in ivec2 UV1;
layout(location = 4) in ivec2 UV2;
#ifdef GLINT_SPECIAL
layout(location = 5) in vec2 UV3;
#endif
layout(location = 6) in vec3 Normal;

#ifndef OIT_ALPHA_ONLY
uniform sampler2D Sampler1;
uniform sampler2D Sampler2;

layout(location = 0) out float sphericalVertexDistance;
layout(location = 1) out float cylindricalVertexDistance;
#endif
layout(location = 2) out vec4 vertexColor;
#ifndef OIT_ALPHA_ONLY
layout(location = 3) out vec4 lightMapColor;
layout(location = 4) out vec4 overlayColor;
#endif

layout(location = 5) out vec2 texCoord0;
#ifdef GLINT
layout(location = 6) out vec2 texCoordGlint;
#endif

layout(location = 7) out vec3 dfskyRay;

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
    dfskyRay = spSkyWorldRay(Position, ProjMat, ModelViewMat);
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

    #ifndef OIT_ALPHA_ONLY
    sphericalVertexDistance = fog_spherical_distance(Position);
    cylindricalVertexDistance = fog_cylindrical_distance(Position);
    #endif
    vertexColor = minecraft_mix_light(Light0_Direction, Light1_Direction, Normal, Color);
    #ifndef OIT_ALPHA_ONLY
    lightMapColor = sample_lightmap(Sampler2, UV2);
    overlayColor = texelFetch(Sampler1, UV1, 0);
    #endif

    texCoord0 = UV0;
    #ifdef GLINT
    #ifdef GLINT_SPECIAL
    texCoordGlint = (TextureMat * vec4(UV3, 0.0, 1.0)).xy;
    #else
    texCoordGlint = (TextureMat * vec4(UV0, 0.0, 1.0)).xy;
    #endif
    #endif
}
