#version 330
#extension GL_ARB_separate_shader_objects : require

uniform sampler2D MainSampler;
uniform sampler2D DataSampler;

#include <shader_selector:marker_settings.glsl>
#include <shader_selector:utils.glsl>
#include <shader_selector:data_reader.glsl>
#include <minecraft:globals.glsl>
#include <star_program:recoil.glsl>
#define DFSKY_RUNTIME 1
#include <dfsky:settings.glsl>
#include <dfsky:runtime.glsl>

layout(std140) uniform SamplerInfo {
    vec2 OutSize;
    vec2 InSize;
};

// 26.3 uses ShaderC/SPIR-V for both rendering backends.

layout(location = 0) out vec2 baseTexCoord;


float spAngleDegrees(float controlValue) {
    float value = controlValue * 255.0 - 128.0;
    return value * (value < 0.0 ? 8.0 / 128.0 : 8.0 / 127.0);
}
layout(location = 1) flat out vec2 spProjection;
layout(location = 2) flat out mat3 spCameraToWorld;
layout(location = 5) flat out vec2 spAngles;
layout(location = 6) flat out float spCrop;
layout(location = 7) flat out float spTime;
layout(location = 8) flat out int spHasCamera;
// All selected-time fields are constant across this full-screen triangle.
layout(location = 9) flat out vec4 spSkyA;
layout(location = 10) flat out vec4 spSkyB;
layout(location = 11) flat out vec4 spSkyC;
layout(location = 12) flat out vec4 spSkyD;

void main(){
    spHasCamera = int(spCameraValid());
    spProjection = spProjectionScale();
    spCameraToWorld = spWorldFromView();
    spAngles = radians(vec2(spAngleDegrees(readChannel(RECOIL_PITCH)), spAngleDegrees(readChannel(RECOIL_YAW))));
    if (spHasCamera == 0) spAngles = vec2(0.0);
    spCrop = spRecoilCrop(spProjection, spAngles.x, spAngles.y);
    spTime = spSkyTime();
    dfsky_setTime(spTime);
    spSkyA = vec4(dfskyState.sunAngle, dfskyState.starBrightness, dfskyState.skyColor.rg);
    spSkyB = vec4(dfskyState.skyColor.b, dfskyState.fogColor);
    spSkyC = dfskyState.cloudColor;
    spSkyD = dfskyState.sunsetColor;
    vec2 uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
    gl_Position = vec4(uv * 2.0 - 1.0, 0.2, 1.0);
    baseTexCoord = uv;

    float t = GameTime;
    float freq = (1.-readChannel(SCREENSHAKE_FREQUENCY)) * 65025.; // Channel #2 Controls Shake Freq
    float magnitude = (1.-readChannel(SCREENSHAKE_MAGNITUDE)) * .03; // Channel #1 Controls Shake Magnitude

    // Zoom in to prevent bars
    baseTexCoord *= 1. - magnitude * 2.;
    baseTexCoord.y += magnitude;

    baseTexCoord.x += cos(sin(t * freq) * 3.) * magnitude;
    baseTexCoord.y += sin(cos(t * freq) * 3.) * magnitude;
}

