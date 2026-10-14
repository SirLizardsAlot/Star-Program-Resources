#version 330

#moj_import <minecraft:fog.glsl>
#moj_import <minecraft:globals.glsl>
#moj_import <minecraft:dynamictransforms.glsl>
#moj_import <terf:utils.glsl>

in float sphericalVertexDistance;
in float cylindricalVertexDistance;
in mat4 ProjInv;

out vec4 fragColor;

#define GRIDOFFSET 0.05
#define GRIDDENSITY 5.0

vec3 hash( vec3 p ) 
{
	p = vec3( dot(p,vec3(127.1,311.7, 74.7)),
			  dot(p,vec3(269.5,183.3,246.1)),
			  dot(p,vec3(113.5,271.9,124.6)));

	return -1.0 + 2.0*fract(sin(p)*43758.5453123);
}

float noise( in vec3 p )
{
    vec3 i = floor( p );
    vec3 f = fract( p );
	
	vec3 u = f * f * (3.0 - 2.0 * f);

    return mix( mix( mix( dot( hash( i + vec3(0.0,0.0,0.0) ), f - vec3(0.0,0.0,0.0) ), 
                          dot( hash( i + vec3(1.0,0.0,0.0) ), f - vec3(1.0,0.0,0.0) ), u.x),
                     mix( dot( hash( i + vec3(0.0,1.0,0.0) ), f - vec3(0.0,1.0,0.0) ), 
                          dot( hash( i + vec3(1.0,1.0,0.0) ), f - vec3(1.0,1.0,0.0) ), u.x), u.y),
                mix( mix( dot( hash( i + vec3(0.0,0.0,1.0) ), f - vec3(0.0,0.0,1.0) ), 
                          dot( hash( i + vec3(1.0,0.0,1.0) ), f - vec3(1.0,0.0,1.0) ), u.x),
                     mix( dot( hash( i + vec3(0.0,1.0,1.0) ), f - vec3(0.0,1.0,1.0) ), 
                          dot( hash( i + vec3(1.0,1.0,1.0) ), f - vec3(1.0,1.0,1.0) ), u.x), u.y), u.z );
}

void main() {
    if (is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(1.,1.,1.)) || is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(2.,1.,1.)) || is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(1.,1.,2.))) {
        // get player space view vector
        vec4 screenPos = gl_FragCoord;
        screenPos.xy = (screenPos.xy / ScreenSize - vec2(0.5)) * 2.0;
        screenPos.zw = vec2(1.0);
        vec3 view = normalize((ProjInv * screenPos).xyz);

        // sun angle
        float angle = GameTime * 5.;

        float vdn = dot(view, vec3(0.0, cos(angle), sin(angle)));
        float vdb = dot(view, vec3(1.0, 0.0, 0.0));
        float vdt = dot(view, vec3(0.0, sin(-angle), cos(-angle)));

        // stars
        vec3 stars_direction = normalize(vec3(vdn, vdt, vdb));
        float stars_threshold = 10.0f;
        float stars_exposure = 200.0f;
        float stars = pow(clamp(noise(stars_direction * 250.0f), 0.0f, 1.0f), stars_threshold) * stars_exposure;
        stars += pow(clamp(noise(stars_direction * 150.0f), 0.0f, 1.0f), stars_threshold) * stars_exposure;

        fragColor = mix(vec4(255.0, 255.0, 172.0, 255.0)/255.0, vec4(vec3(stars), 1.0), 1.0);

        vec3 nebulaColor = vec3(1);
        for (float i = 1; i < 6; i++) {
            float nebulas = clamp(noise(stars_direction * pow(i,3.)), 0.0f, 1.0f);
            nebulaColor *= vec3(nebulas/(i/11.+.8), (pow(nebulas+1.,(9-i)/2.)-1.)/10., nebulas)+1.;
        }

        fragColor += vec4(nebulaColor-1. ,0.)/20.;

        // Render additional stuff
        if (is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(1.,1.,1.))) {
            // Earth
            float globalRes = 100.;
            vec2 scaledView = view.xz * (0.3-pow(view.y+2.,3.));
            vec2 pixelView = floor(scaledView.xy*globalRes)/globalRes;
            float dist = distance(pixelView.xy,vec2(0.))/5.;
            if (dist < .1 && view.y < .5) {
                if (dist < .09) {
                    float res = 20.0+pow(dist+1.0,30.0);
                    float map = noise(vec3(pixelView.x*res+1.6, 0., pixelView.y*res));
                    float clouds = clamp(noise(vec3( pixelView.x*res/2+GameTime*100, 0., pixelView.y*res/2+GameTime*200)), 0.0, 1.0);

                    float deserts = noise(vec3(0., pixelView.x*res*1.2, pixelView.y*res*1.2));

                    float fade = -pixelView.x + pow(dist+1.0,6.5)-1.0;
                    float red = clamp(deserts*5.0-0.5, 0.0, 1.0) + (clamp(map*100.0-10.0, 0.0, 1.0) - clamp(map*5.0-0.5, 0.0, 1.0))/1.5;
                    float green = clamp(map*1000.0-100.0, 0.0, 1.0);

                    fragColor = vec4(vec3(min(green*red,1.0), green-red/7.0, 1.0-clamp(map*100.0-10.0, 0.0, 1.0)) - vec3(fade) + vec3(clouds), 1.0);
                } else {
                    float fade = (.1-dist)*80.0;
                    fragColor += vec4(0.0, 0.4*fade, 1.0*fade, .5-dist);
                }
            }
        } else if (is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(2.,1.,1.))) {
            // End (is almost perfectly how it actually looks https://www.youtube.com/watch?app=desktop&v=91Feq0dHw28&t)
            float dist = view.y + 1.0;
            if (dist < .6) {
                float res = 1000.0+pow(dist+1.0,20.0);

                float x = dist*30000000./6.; //size of the minecraft world
                float small_island_noise = max(noise(vec3(view.y*res, view.x*res, view.z*res))+.5,0.);
                float large_island_noise = max(noise(vec3(view.y*res/3., view.x*res/3., view.z*res/3.))+.15,0.);
                float end_rings = sin(x * x * 0.0000000000228580929) * 250000.0;

                float map = min(end_rings ,1.) - small_island_noise + large_island_noise;

                if (map > .7) {
                    fragColor = vec4(217.0, 220.0, 156.0, 255.0)/255.;
                }
            }
        } else {
            // Interdimensional warp
            float s = 0.0, v = 0.0;
            vec3 col = vec3(0);
            for (int r = 0; r < 50; r++) {
                vec3 power = vec3(0.0, 0.0, GameTime*1000.0) + s / -view;
                power.z = noise(vec3(power.z));
                for (int i=0; i < 10; i++)	power = abs(power * 2.04) / dot(power, power) - 0.9;
                v += pow(dot(power, power), 0.6) * 0.1;
                col += vec3(v * 0.2+0.4, 1.-s*2., 0.1 + v * 1.0) * v * 0.00003;
                s += 0.01;
            }

            float power = (noise(vec3(GameTime*532.0))+1.3)/5.;
            float flash = max(1.-pow(abs(view.y),power),0.);
            flash += max(1.-pow(abs(view.x),power),0.);

            col += pow(flash,2.);
            fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
        }
    } else {
        fragColor = apply_fog(ColorModulator, sphericalVertexDistance, cylindricalVertexDistance, 0.0, FogSkyEnd, FogSkyEnd, FogSkyEnd, FogColor);
    }
}
