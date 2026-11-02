#ifndef DFSKY_SKY_GLSL
#define DFSKY_SKY_GLSL
#include <dfsky:settings.glsl>
#include <dfsky:runtime.glsl>
#include <dfsky:vanilla_data.glsl>

const float DFSKY_PI = 3.141592653589793;

float dfsky_hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

bool dfsky_marker(sampler2D atlas, vec2 uv, out float cloudOffset) {
    // Level zero avoids lighting, mipmaps and texture filtering changing the ID.
    ivec2 size = textureSize(atlas, 0);
    ivec2 pixel = clamp(ivec2(uv * vec2(size)), ivec2(0), size - 1);
    ivec4 c = ivec4(round(texelFetch(atlas, pixel, 0) * 255.0));
    cloudOffset = 0.0;
    return all(equal(c, ivec4(17, 239, 173, 255)));
}

float dfsky_stars(vec3 ray) {
    // Cubemap coordinates keep star positions fixed in the world.
    vec3 a = abs(ray);
    vec2 uv;
    float face;
    if (a.x >= a.y && a.x >= a.z) {
        uv = ray.yz / a.x;
        face = ray.x > 0.0 ? 0.0 : 1.0;
    } else if (a.y >= a.z) {
        uv = ray.xz / a.y;
        face = ray.y > 0.0 ? 2.0 : 3.0;
    } else {
        uv = ray.xy / a.z;
        face = ray.z > 0.0 ? 4.0 : 5.0;
    }
    vec2 grid = (uv * 0.5 + 0.5) * 105.0;
    vec2 cell = floor(grid);
    float seed = dfsky_hash(cell + vec2(face * 219.0, 11.0));
    vec2 center = vec2(dfsky_hash(cell + face * 51.0), dfsky_hash(cell + 37.0 + face * 81.0));
    center = 0.2 + center * 0.6;
    float radius = mix(0.018, 0.075, seed);
    float d = max(abs(fract(grid).x - center.x), abs(fract(grid).y - center.y));
    float aa = max(fwidth(grid.x), fwidth(grid.y));
    return step(0.945, seed) * (1.0 - smoothstep(radius, radius + aa, d));
}

vec3 dfsky_background(vec3 ray) {
    // Reproduce the vanilla sky disc: center Y=16, octagonal rim radius=512.
    // Its vertex fog distances interpolate from 16 to sqrt(512^2 + 16^2).
    if (ray.y <= 0.0) return DFSKY_FOG_COLOR;
    float radial = length(ray.xz) * 16.0 / ray.y;
    float angle = atan(ray.z, ray.x);
    float wedge = mod(angle, DFSKY_PI * 0.25) - DFSKY_PI * 0.125;
    float rim = 512.0 * cos(DFSKY_PI * 0.125) / cos(wedge);
    float discDistance = mix(16.0, 512.249939, clamp(radial / rim, 0.0, 1.0));
    float fog = clamp(discDistance / DFSKY_SKY_FOG_END, 0.0, 1.0);
    return mix(DFSKY_SKY_COLOR, DFSKY_FOG_COLOR, fog);
}

vec3 dfsky_clouds(vec3 sky, vec3 ray, float cloudOffset) {
    if (abs(ray.y) < 0.00001) return sky;
    float bottom = DFSKY_CLOUD_HEIGHT - DFSKY_VIRTUAL_EYE_HEIGHT;
    float top = bottom + 4.0;
    float nearT = min(bottom / ray.y, top / ray.y);
    float farT = max(bottom / ray.y, top / ray.y);
    float t = max(nearT, 0.0);
    if (farT <= t || t >= DFSKY_CLOUD_FOG_END) return sky;
    farT = min(farT, DFSKY_CLOUD_FOG_END);

    vec2 origin = vec2(DFSKY_CLOUD_OFFSET_X + cloudOffset, DFSKY_CLOUD_OFFSET_Z);
    vec2 point = origin + ray.xz * (t + 0.0001);
    ivec2 cell = ivec2(floor(point / 12.0));
    ivec2 stepCell = ivec2(ray.x >= 0.0 ? 1 : -1, ray.z >= 0.0 ? 1 : -1);
    vec2 boundary = (vec2(cell) + vec2(stepCell.x > 0 ? 1.0 : 0.0, stepCell.y > 0 ? 1.0 : 0.0)) * 12.0;
    vec2 nextT = vec2(
        abs(ray.x) < 0.00001 ? 1e20 : (boundary.x - origin.x) / ray.x,
        abs(ray.z) < 0.00001 ? 1e20 : (boundary.y - origin.y) / ray.z
    );
    vec2 deltaT = 12.0 / max(abs(ray.xz), vec2(0.00001));
    float faceBrightness = ray.y > 0.0 ? 0.7 : 1.0;
    // Traverse the 4-block slab, stopping at the first vanilla cloud cell.
    for (int i = 0; i < 32; ++i) {
        if (t > farT) break;
        if (dfsky_cloudCell(cell)) {
            float opacity = DFSKY_CLOUD_COLOR.a * clamp(1.0 - t / DFSKY_CLOUD_FOG_END, 0.0, 1.0);
            return mix(sky, DFSKY_CLOUD_COLOR.rgb * faceBrightness, opacity);
        }
        if (nextT.x <= nextT.y) {
            t = nextT.x;
            nextT.x += deltaT.x;
            cell.x += stepCell.x;
            faceBrightness = 0.9;
        } else {
            t = nextT.y;
            nextT.y += deltaT.y;
            cell.y += stepCell.y;
            faceBrightness = 0.8;
        }
    }
    return sky;
}

vec3 dfsky_render(vec3 direction, float cloudOffset) {
    vec3 ray = normalize(direction);
    vec3 sunDirection = vec3(-sin(DFSKY_SUN_ANGLE), cos(DFSKY_SUN_ANGLE), 0.0);
    vec3 color = dfsky_background(ray);

    // Dawn/dusk use the native timeline color, applied near the sun's horizon.
    float sunsetSide = pow(max(dot(normalize(vec3(ray.x, 0.0001, ray.z)), normalize(vec3(sunDirection.x, 0.0001, 0.0))), 0.0), 2.0);
    float sunsetBand = 1.0 - smoothstep(0.0, 0.32, abs(ray.y));
    color = mix(color, DFSKY_SUNSET_COLOR.rgb, DFSKY_SUNSET_COLOR.a * sunsetSide * sunsetBand);

#if DFSKY_STARS
    float star = dfsky_stars(ray) * DFSKY_STAR_BRIGHTNESS * smoothstep(-0.02, 0.12, ray.y);
    color += vec3(star);
#endif

    // Native 32-pixel textures and the renderer's complete textured quad sizes.
    vec3 right = vec3(0.0, 0.0, 1.0);
    vec3 up = normalize(cross(right, sunDirection));
    float facingSun = dot(ray, sunDirection);
    vec2 sunUV = vec2(dot(ray, right), dot(ray, up)) / max(abs(facingSun), 0.0001);
    if (facingSun > 0.0) {
        vec4 sun = dfsky_sunTexture(sunUV / DFSKY_SUN_SIZE * 0.5 + 0.5);
        color += sun.rgb * sun.a;
    }

    vec3 moonDirection = -sunDirection;
    float facingMoon = dot(ray, moonDirection);
    vec2 moonUV = vec2(dot(ray, right), -dot(ray, up)) / max(abs(facingMoon), 0.0001);
    if (facingMoon > 0.0) {
        vec4 moon = dfsky_moonTexture(moonUV / DFSKY_MOON_SIZE * 0.5 + 0.5);
        color += moon.rgb * moon.a;
    }

#if DFSKY_CLOUDS
    color = dfsky_clouds(color, ray, cloudOffset);
#endif
    return clamp(color, 0.0, 1.0);
}
#endif
