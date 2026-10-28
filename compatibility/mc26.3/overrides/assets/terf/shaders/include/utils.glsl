bool is_sky_color(vec3 FogColor, vec3 SkyColor, vec3 targetColor) {
    vec3 activator = FogColor.rgb;

    return (targetColor/255. == activator);
}