#ifndef STAR_PROGRAM_RECOIL_GLSL
#define STAR_PROGRAM_RECOIL_GLSL

// Rendered camera offsets only. Minecraft's aim and mouse axes are unchanged.
// Positive pitch looks up. Positive yaw looks right.
// projectionScale is the current world projection's positive (P[0][0], P[1][1]).
const float SP_RECOIL_MAX_RADIANS = 0.13962634015954636; // 8 degrees
const int SP_RECOIL_CROP_STEPS = 22;
const float SP_RECOIL_EDGE = 0.99999;

bool spRecoilFinite(float value) {
    return !isnan(value) && !isinf(value);
}

bool spRecoilProjectionValid(vec2 projectionScale) {
    return spRecoilFinite(projectionScale.x)
        && spRecoilFinite(projectionScale.y)
        && projectionScale.x > 0.00001
        && projectionScale.y > 0.00001;
}

float spRecoilAngle(float radians) {
    return spRecoilFinite(radians)
        ? clamp(radians, -SP_RECOIL_MAX_RADIANS, SP_RECOIL_MAX_RADIANS)
        : 0.0;
}

vec4 spRecoilTrig(float pitchRadians, float yawRadians) {
    return vec4(sin(pitchRadians), cos(pitchRadians),
                sin(yawRadians), cos(yawRadians));
}

vec3 spRecoilSourceRay(vec3 ray, vec4 angles) {
    // Rx(pitch), followed by Ry(-yaw), maps an output ray to the source view.
    vec3 pitched = vec3(ray.x,
        angles.y * ray.y - angles.x * ray.z,
        angles.x * ray.y + angles.y * ray.z);
    return vec3(angles.w * pitched.x - angles.z * pitched.z,
                pitched.y,
                angles.z * pitched.x + angles.w * pitched.z);
}

bool spRecoilCropFits(float crop, vec2 projectionScale, vec4 angles) {
    // With a positive denominator, each coordinate of this homography reaches
    // its extrema at a corner. Checking the corners therefore covers the image.
    for (int corner = 0; corner < 4; ++corner) {
        vec2 ndc = vec2((corner & 1) == 0 ? -1.0 : 1.0,
                        (corner & 2) == 0 ? -1.0 : 1.0);
        vec3 sourceRay = spRecoilSourceRay(
            vec3(ndc * crop / projectionScale, -1.0), angles);
        if (-sourceRay.z <= 0.00001) {
            return false;
        }
        vec2 sourceNdc = projectionScale * sourceRay.xy / -sourceRay.z;
        if (any(greaterThan(abs(sourceNdc), vec2(SP_RECOIL_EDGE)))) {
            return false;
        }
    }
    return true;
}

// Evaluate once per fullscreen vertex and pass the result as a flat varying.
// Do not call the crop search for every fragment. Zero disables an invalid
// configuration safely, including offsets whose centre is outside the source.
float spRecoilCrop(vec2 projectionScale, float pitchRadians, float yawRadians) {
    float pitch = spRecoilAngle(pitchRadians);
    float yaw = spRecoilAngle(yawRadians);
    if (!spRecoilProjectionValid(projectionScale)
        || (pitch == 0.0 && yaw == 0.0)) {
        return 1.0;
    }
    vec4 angles = spRecoilTrig(pitch, yaw);
    if (!spRecoilCropFits(0.0, projectionScale, angles)) {
        return 0.0;
    }
    if (spRecoilCropFits(1.0, projectionScale, angles)) {
        return 1.0;
    }
    float safe = 0.0;
    float unsafe = 1.0;
    for (int step = 0; step < SP_RECOIL_CROP_STEPS; ++step) {
        float candidate = (safe + unsafe) * 0.5;
        if (spRecoilCropFits(candidate, projectionScale, angles)) {
            safe = candidate;
        } else {
            unsafe = candidate;
        }
    }
    return safe;
}

// Evaluate per fragment. The perspective divide cannot be linearly
// interpolated from the fullscreen triangle's three vertices.
vec2 spRecoilUV(vec2 uv, vec2 projectionScale, float pitchRadians,
                float yawRadians, float crop) {
    float pitch = spRecoilAngle(pitchRadians);
    float yaw = spRecoilAngle(yawRadians);
    if (!spRecoilProjectionValid(projectionScale)
        || !spRecoilFinite(crop) || crop <= 0.0
        || (pitch == 0.0 && yaw == 0.0)) {
        return uv;
    }
    vec2 ndc = (uv * 2.0 - 1.0) * min(crop, 1.0);
    vec3 sourceRay = spRecoilSourceRay(
        vec3(ndc / projectionScale, -1.0), spRecoilTrig(pitch, yaw));
    if (-sourceRay.z <= 0.00001) {
        return uv;
    }
    return 0.5 + 0.5 * projectionScale * sourceRay.xy / -sourceRay.z;
}

#endif
