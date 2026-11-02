#ifndef STAR_PROGRAM_ZOOM_GLSL
#define STAR_PROGRAM_ZOOM_GLSL

// Interpolate the player's current vertical field of view toward zero degrees.
// Uniformly cropping both image axes preserves its aspect ratio. The current
// projection supplies FOV changes from the player's own settings and effects.
float spZoomCropFactor(float projectionY, float strength) {
    float amount = !isnan(strength) && !isinf(strength)
        ? clamp(strength, 0.0, 1.0) : 0.0;
    if (amount == 0.0) return 1.0;
    if (amount == 1.0) return 0.0;
    if (isnan(projectionY) || isinf(projectionY) || projectionY <= 0.00001)
        return 1.0;
    float halfFov = atan(1.0 / projectionY);
    return tan((1.0 - amount) * halfFov) / tan(halfFov);
}

#endif
