#version 330
#extension GL_ARB_separate_shader_objects : require

uniform sampler2D MainSampler;
uniform sampler2D DataSampler;
uniform sampler2D BlurSampler;

#include <shader_selector:marker_settings.glsl>
#include <shader_selector:utils.glsl>
#include <shader_selector:data_reader.glsl>
#include <minecraft:globals.glsl>

layout(std140) uniform SamplerInfo {
    vec2 OutSize;
    vec2 InSize;
};

// 26.3 uses ShaderC/SPIR-V for both rendering backends.

layout(location = 0) out vec2 texCoord;

void main(){
    vec2 uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
    gl_Position = vec4(uv * 2.0 - 1.0, 0.2, 1.0);
    texCoord = uv;

    float t = GameTime;
    float freq = (1.-readChannel(SCREENSHAKE_FREQUENCY)) * 65025.; // Channel #2 Controls Shake Freq
    float magnitude = (1.-readChannel(SCREENSHAKE_MAGNITUDE)) * .03; // Channel #1 Controls Shake Magnitude

    // Zoom in to prevent bars
    texCoord *= 1. - magnitude * 2.;
    texCoord.y += magnitude;

    texCoord.x += cos(sin(t * freq) * 3.) * magnitude;
    texCoord.y += sin(cos(t * freq) * 3.) * magnitude;
}

