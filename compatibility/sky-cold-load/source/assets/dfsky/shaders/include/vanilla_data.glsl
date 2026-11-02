// Generated from the archived native sky data. Bitmap data lives in
// texture storage instead of dynamically indexed shader constant arrays.
#ifndef DFSKY_VANILLA_DATA_GLSL
#define DFSKY_VANILLA_DATA_GLSL
#ifndef DFSKY_SAMPLER
#error Define DFSKY_SAMPLER before including the sky data helpers.
#endif

// Geometry selects the marker sprite's origin in the block atlas. The post
// effect binds the identical standalone data texture and leaves this at zero.
ivec2 dfskyDataOrigin = ivec2(0);

bool dfsky_cloudCell(ivec2 cell) {
    ivec2 wrapped = cell & ivec2(255);
    int cellIndex = wrapped.x + wrapped.y * 256;
    int byteIndex = cellIndex >> 3;
    ivec2 pixel = ivec2(byteIndex & 127, 16 + (byteIndex >> 7));
    int bits = int(round(texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + pixel, 0).r * 255.0));
    return (bits & (1 << (cellIndex & 7))) != 0;
}

vec4 dfsky_sunTexture(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    ivec2 pixel = min(ivec2(floor(uv * 32.0)), ivec2(31));
    vec3 rgb = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(128, 16) + pixel, 0).rgb;
    float alpha = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(160, 16) + pixel, 0).r;
    return vec4(rgb, alpha);
}

vec4 dfsky_moonTexture(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    ivec2 pixel = min(ivec2(floor(uv * 32.0)), ivec2(31));
    vec3 rgb = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(192, 16) + pixel, 0).rgb;
    float alpha = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(224, 16) + pixel, 0).r;
    return vec4(rgb, alpha);
}
#endif
