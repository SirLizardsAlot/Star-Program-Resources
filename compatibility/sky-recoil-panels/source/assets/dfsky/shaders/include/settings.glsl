#ifndef DFSKY_SETTINGS_GLSL
#define DFSKY_SETTINGS_GLSL
// Static geometry matches the successful DF Sky Window build.
// Runtime state starts at its exact fixed-noon values.
#define DFSKY_SUN_SIZE 0.3000000000
#define DFSKY_MOON_SIZE 0.2000000000
#define DFSKY_SKY_FOG_END 352.0000000000
#define DFSKY_CLOUD_FOG_END 992.0000000000
#define DFSKY_CLOUD_HEIGHT 192.3300000000
#define DFSKY_VIRTUAL_EYE_HEIGHT 65.6200000000
#define DFSKY_CLOUD_OFFSET_X 0.0000000000
#define DFSKY_CLOUD_OFFSET_Z 3.9600000000
#define DFSKY_FOG_BLEND 0.0645856533
#define DFSKY_CLOUDS 1
#define DFSKY_STARS 1

struct DfSkyState {
    float timeTicks;
    float sunAngle;
    float starBrightness;
    vec3 skyColor;
    vec3 fogColor;
    vec4 cloudColor;
    vec4 sunsetColor;
};
DfSkyState dfskyState = DfSkyState(
    6000.0000000000,
    0.0000000000,
    0.0000000000,
    vec3(0.4705882353, 0.6549019608, 1.0000000000),
    vec3(0.7347052273, 0.8346482470, 1.0000000000),
    vec4(1.0000000000, 1.0000000000, 1.0000000000, 0.8000000000),
    vec4(1.0000000000, 0.8980392157, 0.2000000000, 0.0000000000)
);
#define DFSKY_TIME_TICKS (dfskyState.timeTicks)
#define DFSKY_SUN_ANGLE (dfskyState.sunAngle)
#define DFSKY_STAR_BRIGHTNESS (dfskyState.starBrightness)
#define DFSKY_SKY_COLOR (dfskyState.skyColor)
#define DFSKY_FOG_COLOR (dfskyState.fogColor)
#define DFSKY_CLOUD_COLOR (dfskyState.cloudColor)
#define DFSKY_SUNSET_COLOR (dfskyState.sunsetColor)
#endif
