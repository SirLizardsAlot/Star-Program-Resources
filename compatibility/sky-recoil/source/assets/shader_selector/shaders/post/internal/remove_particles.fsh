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
