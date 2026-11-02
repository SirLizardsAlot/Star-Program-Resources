const float CONTROL_PERIOD = 1200.0;
const float CONTROL_TIMEOUT = 0.4;
const float SP_REBASE_TIMEOUT = 2.5;

bool controlFiniteUnit(float value) {
    return !isnan(value) && !isinf(value) && value >= 0.0 && value <= 1.0;
}
bool controlFiniteTime(float value) {
    return !isnan(value) && !isinf(value) && value >= 0.0 && value < CONTROL_PERIOD;
}
float controlElapsed(float now, float previous) {
    return mod(now - previous + CONTROL_PERIOD, CONTROL_PERIOD);
}
float controlNeutral(int channel) {
    if (channel == ALARM_EFFECTS) return 0.0;
    if (channel == SKY_TIME_HIGH) return 23.0 / 255.0;
    if (channel == SKY_TIME_LOW) return 112.0 / 255.0;
    if (channel == ZOOM_AMOUNT || channel == RESERVED_CONTROL) return 0.0;
    return 1.0;
}
bool controlStateValid() {
    ivec4 header = ivec4(round(texelFetch(DataSampler, ivec2(4, 0), 0) * 255.0));
    return all(equal(header, ivec4(83, 80, 90, 4)));
}
float readChannel(int channel) {
    if (channel < 1 || channel > SP_CHANNEL_COUNT) return 0.0;
    if (!controlStateValid()) return controlNeutral(channel);
    float value = decodeColor(texelFetch(DataSampler, ivec2(4, channel), 0));
    return controlFiniteUnit(value) ? value : controlNeutral(channel);
}
ivec4 spCameraCell(int index) {
    return ivec4(round(texelFetch(DataSampler, ivec2(index % 5, 8 + index / 5), 0) * 255.0));
}
float spCameraByte(int index) { return float(spCameraCell(index).b); }
float spCameraWord(int component) {
    return spCameraByte(component * 2) * 256.0 + spCameraByte(component * 2 + 1);
}
vec2 spProjectionScale() {
    return vec2(spCameraWord(9), spCameraWord(10)) * (16.0 / 65535.0);
}
mat3 spWorldFromView() {
    mat3 result;
    for (int column = 0; column < 3; ++column)
        for (int row = 0; row < 3; ++row)
            result[column][row] = spCameraWord(column * 3 + row) * (2.0 / 65535.0) - 1.0;
    return result;
}
bool spCameraValid() {
    if (!controlStateValid()) return false;
    for (int index = 0; index < 23; ++index) {
        ivec4 wire = spCameraCell(index);
        if (wire.r != 255 || wire.g != 0 || wire.a != 255) return false;
    }
    if (spCameraCell(22).b != 171) return false;
    vec2 scale = spProjectionScale();
    if (any(lessThan(scale, vec2(0.05))) || any(greaterThanEqual(scale, vec2(16.0)))) return false;
    mat3 map = spWorldFromView();
    for (int column = 0; column < 3; ++column) {
        if (any(isnan(map[column])) || any(isinf(map[column]))
            || any(greaterThan(abs(map[column]), vec3(1.0)))) return false;
    }
    return abs(determinant(map)) > 0.000001;
}
float spSkyTime() {
    if (!controlStateValid()) return 6000.0;
    float value = decodeColor(texelFetch(DataSampler, ivec2(4, 13), 0));
    return !isnan(value) && !isinf(value) && value >= 0.0 && value < 24000.0 ? value : 6000.0;
}
