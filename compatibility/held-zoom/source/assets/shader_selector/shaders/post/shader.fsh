#version 330
#extension GL_ARB_separate_shader_objects : require

uniform sampler2D MainSampler;
uniform sampler2D MainDepthSampler;
uniform sampler2D DataSampler;

#include <shader_selector:marker_settings.glsl>
#include <shader_selector:utils.glsl>
#include <shader_selector:data_reader.glsl>
#include <minecraft:globals.glsl>
uniform sampler2D SkyDataSampler;
#define DFSKY_SAMPLER SkyDataSampler
#include <dfsky:sky.glsl>

layout(location = 0) in vec2 baseTexCoord;
layout(location = 2) flat in mat3 spCameraToWorld;
layout(location = 6) flat in float spCrop;
layout(location = 7) flat in float spTime;
layout(location = 8) flat in int spHasCamera;
layout(location = 9) flat in vec4 spSkyA;
layout(location = 10) flat in vec4 spSkyB;
layout(location = 11) flat in vec4 spSkyC;
layout(location = 12) flat in vec4 spSkyD;
vec2 texCoord;

layout(location = 0) out vec4 fragColor;


DfSkyState spNoonState() {
    return DfSkyState(
    6000.0000000000,
    0.0000000000,
    0.0000000000,
    vec3(0.4705882353, 0.6549019608, 1.0000000000),
    vec3(0.7347052273, 0.8346482470, 1.0000000000),
    vec4(1.0000000000, 1.0000000000, 1.0000000000, 0.8000000000),
    vec4(1.0000000000, 0.8980392157, 0.2000000000, 0.0000000000)
);
}

vec4 spScene(vec2 uv) {
    vec4 source = texture(MainSampler, uv);
    float visibility = clamp(1.0 - source.a, 0.0, 1.0);
    // A cleared background has no world depth. Ordinary opaque geometry has
    // alpha one. Ignore byte-sized incidental coverage errors on cutout edges.
    if (spHasCamera != 0 && visibility > 0.02 && texture(MainDepthSampler, uv).r > 0.0) {
        vec3 ray = normalize(spCameraToWorld * vec3(uv * 2.0 - 1.0, 1.0));
        dfskyState = spNoonState();
        vec3 baseline = dfsky_render(ray, 0.0);
        dfskyState = DfSkyState(spTime, spSkyA.x, spSkyA.y,
            vec3(spSkyA.zw, spSkyB.x), spSkyB.yzw, spSkyC, spSkyD);
        float cloudClock = mod(GameTime * 1200.0 * 0.6, 3072.0);
        vec3 replacement = dfsky_render(ray, cloudClock);
        source.rgb = clamp(source.rgb + visibility * (replacement - baseline), 0.0, 1.0);
    }
    return vec4(source.rgb, 1.0);
}

float random(float x) {
    return fract(sin(x * 12.9898) * 43758.5453);
}

vec3 tintScreen(float time) {
    // Normalize time to [0, 1] for the full color cycle
    float hue = mod(time, 1.0);
    
    // Calculate RGB based on the hue value
    vec3 color;
    if (hue < 1.0 / 6.0) {
        color = vec3(0.0, hue * 6.0, 1.0); // Cyan to Green
    } else if (hue < 2.0 / 6.0) {
        color = vec3(0.0, 1.0, 1.0 - (hue - 1.0 / 6.0) * 6.0); // Green to Yellow
    } else if (hue < 3.0 / 6.0) {
        color = vec3((hue - 2.0 / 6.0) * 6.0, 1.0, 0.0); // Yellow to Red
    } else if (hue < 4.0 / 6.0) {
        color = vec3(1.0, 1.0 - (hue - 3.0 / 6.0) * 6.0, 0.0); // Red to Magenta
    } else if (hue < 5.0 / 6.0) {
        color = vec3(1.0, 0.0, (hue - 4.0 / 6.0) * 6.0); // Magenta to Blue
    } else {
        color = vec3(1.0 - (hue - 5.0 / 6.0) * 6.0, 0.0, 1.0); // Blue to Cyan
    }
    
    return color;
}

vec4 demDistortion(float time, float controlStrength) {
    // Fetch the current pixel color from the texture
    vec4 color = spScene(texCoord);

    float t = time;
    float intensity = max(0.,pow(controlStrength+1,3)-1 - random(t)/100.);

    // Get the red component of the color
    float redValue = color.r;

    // Calculate the center of the screen in texture coordinates
    vec2 center = vec2(0.5, 0.5);
    
    // Compute the direction vector from the current pixel to the center
    vec2 direction = center - texCoord;
    
    // Compute the amount to pull the pixel based on the red component
    float pullAmount = redValue * intensity; // Adjust this multiplier to control the strength of the pull
    
    // Calculate the new texture coordinate by pulling towards the center
    vec2 pulledTexCoord = texCoord + direction * pullAmount;
    
    // Fetch the color from the texture at the new coordinate
    vec4 pulledColor = spScene(pulledTexCoord);

    // Output the pulled color
    return pulledColor;
}

void main() {
    texCoord = vec2(0.5) + (baseTexCoord - vec2(0.5)) * spCrop;
    float alarm_effects = readChannel(ALARM_EFFECTS);

    if (alarm_effects > 0.) {
        if (alarm_effects == 1./255.) {
            float temp = (sin(GameTime*5000.)+4.)/30.;
            fragColor = spScene(texCoord) - vec4(0.,temp,temp,0.);
        } else if (alarm_effects == 2./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*2500. ,1.0));
            fragColor = vec4(spScene(texCoord).rgb / (min(tint+temp/5.,.7)+.3) ,1.);

        } else if (alarm_effects == 4./255.) {        
            vec3 tint = tintScreen(mod(GameTime*25000. ,1.0));
            fragColor = vec4(spScene(texCoord).rgb / (min(tint+.2,.7)+.3) ,1.);

        } else if (alarm_effects == 5./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*10000. ,1.0));
            fragColor = vec4(spScene(texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);

        } else if (alarm_effects == 8./255.) {
            float temp = sin(GameTime*100000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*2500. ,1.0));
            fragColor = vec4(spScene(texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);

        } else if (alarm_effects == 10./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*1000. ,1.0));
            fragColor = vec4(spScene(texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);
        } else if (alarm_effects > 10./255.) {      
                  
            fragColor = demDistortion(GameTime, (alarm_effects-10./255.)/2.);
        } else {
            fragColor = spScene(texCoord);
        }
    } else {
        fragColor = spScene(texCoord);
    }
}