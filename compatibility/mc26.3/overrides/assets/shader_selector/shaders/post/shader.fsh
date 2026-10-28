#version 330
#extension GL_ARB_separate_shader_objects : require

uniform sampler2D MainSampler;
uniform sampler2D DataSampler;

#include <shader_selector:marker_settings.glsl>
#include <shader_selector:utils.glsl>
#include <shader_selector:data_reader.glsl>
#include <minecraft:globals.glsl>

layout(location = 0) in vec2 texCoord;

layout(location = 0) out vec4 fragColor;

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
    vec4 color = texture(MainSampler, texCoord);

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
    vec4 pulledColor = texture(MainSampler, pulledTexCoord);

    // Output the pulled color
    return pulledColor;
}

void main() {
    float alarm_effects = readChannel(ALARM_EFFECTS);

    if (alarm_effects > 0.) {
        if (alarm_effects == 1./255.) {
            float temp = (sin(GameTime*5000.)+4.)/30.;
            fragColor = texture(MainSampler, texCoord) - vec4(0.,temp,temp,0.);
        } else if (alarm_effects == 2./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*2500. ,1.0));
            fragColor = vec4(texture(MainSampler, texCoord).rgb / (min(tint+temp/5.,.7)+.3) ,1.);

        } else if (alarm_effects == 4./255.) {        
            vec3 tint = tintScreen(mod(GameTime*25000. ,1.0));
            fragColor = vec4(texture(MainSampler, texCoord).rgb / (min(tint+.2,.7)+.3) ,1.);

        } else if (alarm_effects == 5./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*10000. ,1.0));
            fragColor = vec4(texture(MainSampler, texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);

        } else if (alarm_effects == 8./255.) {
            float temp = sin(GameTime*100000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*2500. ,1.0));
            fragColor = vec4(texture(MainSampler, texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);

        } else if (alarm_effects == 10./255.) {
            float temp = sin(GameTime*21000.)+1.;
            
            vec3 tint = tintScreen(mod(GameTime*1000. ,1.0));
            fragColor = vec4(texture(MainSampler, texCoord).rgb / (min(tint+temp/5.,.5)+.5) ,1.);
        } else if (alarm_effects > 10./255.) {      
                  
            fragColor = demDistortion(GameTime, (alarm_effects-10./255.)/2.);
        } else {
            fragColor = texture(MainSampler, texCoord);
        }
    } else {
        fragColor = texture(MainSampler, texCoord);
    }
}