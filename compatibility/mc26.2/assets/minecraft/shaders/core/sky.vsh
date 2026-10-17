#version 330

#moj_import <minecraft:fog.glsl>
#moj_import <minecraft:dynamictransforms.glsl>
#moj_import <minecraft:projection.glsl>
#moj_import <terf:utils.glsl>

in vec3 Position;

out mat4 ProjInv;
out float sphericalVertexDistance;
out float cylindricalVertexDistance;

#define BOTTOM -32.0
#define SCALE 0.01
#define SKYHEIGHT 16.0
#define SKYRADIUS 512.0
#define FUDGE 0.004

void main() {
    if (is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(1.,1.,1.)) || is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(2.,1.,1.)) || is_sky_color(FogColor.rgb,ColorModulator.rgb,vec3(1.,1.,2.))) {
        vec3 scaledPos = Position;
        ProjInv = inverse(ProjMat * ModelViewMat);
        sphericalVertexDistance = length((ModelViewMat * vec4(Position, 1.0)).xyz);
        cylindricalVertexDistance = sphericalVertexDistance;

        // sky disk is by default 16.0 units above with radius of 512.0 around the camera at all times.
        if (abs(scaledPos.y - SKYHEIGHT) < FUDGE && (length(scaledPos.xz) <= FUDGE || abs(length(scaledPos.xz) - SKYRADIUS) < FUDGE)) {

            // Make sky into a cone by bringing down edges of the disk.
            if (length(scaledPos.xz) > 1.0) {
                scaledPos.y = BOTTOM;
            }

            // Make it big so it does not interfere with void plane.
            scaledPos.xyz *= SCALE;

            // rotate to z axis
            scaledPos = scaledPos.xzy;
            scaledPos.z *= -1;

            // ignore model view so the cone follows the camera angle.
            gl_Position = ProjMat * vec4(scaledPos, 1.0);
        } 
        else 
        {
            gl_Position = ProjMat * ModelViewMat * vec4(scaledPos, 1.0);
        }
    }
    else
    {
        // vanilla code
        gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

        sphericalVertexDistance = fog_spherical_distance(Position);
        cylindricalVertexDistance = fog_cylindrical_distance(Position);
    }
}