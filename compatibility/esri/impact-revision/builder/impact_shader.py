"""Add ESRI's explicitly triggered hit frames to the accepted post shader.

The additive pack builder calls patch_entries(entries). Only the existing
shader.fsh entry changes. Neutral byte zero returns the exact existing color.
"""
from hashlib import sha256
import re

SHADER_PATH = 'assets/shader_selector/shaders/post/shader.fsh'
BEGIN = '// STAR_ESRI_IMPACT_BEGIN'
END = '// STAR_ESRI_IMPACT_END'
LEGACY_HELPER_SHA256 = '8b92b22e5f6a14d33e6ff69ea33ed26064648cc0eb983982413897bbfa4ce995'
HELPER = '''// STAR_ESRI_IMPACT_BEGIN
float spEsriImpactControl() {
    if (!controlStateValid()) return 0.0;
    ivec4 packet = ivec4(round(texelFetch(DataSampler, ivec2(0, RESERVED_CONTROL), 0) * 255.0));
    if (packet.r != MARKER_RED || packet.g != 1 || packet.a != 255 || packet.b < 1 || packet.b > 3) return 0.0;
    float seen = decodeColor(texelFetch(DataSampler, ivec2(1, RESERVED_CONTROL), 0));
    float clock = GameTime * CONTROL_PERIOD;
    if (!controlFiniteTime(seen) || !controlFiniteTime(clock) || controlElapsed(clock, seen) > 0.05) return 0.0;
    // Hit-frame identities are discrete. They bypass the generic held-control
    // interpolation and expire after one native tick without fresh packets.
    return float(packet.b) / 255.0;
}

vec3 spEsriSample(vec2 uv, vec2 pixel) {
    return texture(MainSampler, clamp(uv, pixel * 0.5, 1.0 - pixel * 0.5)).rgb;
}

float spEsriLuma(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

vec4 spEsriImpact(vec4 source, vec2 uv, float wire) {
    int phase = int(floor(wire * 255.0 + 0.5));
    if (phase < 1 || phase > 3) return source;

    // View-relative pressure. The machine's separate display flare owns the
    // world-space epicenter and ordinary depth testing at the aperture.
    vec2 size = vec2(textureSize(MainSampler, 0));
    vec2 pixel = 1.0 / size;
    vec2 aspect = size / min(size.x, size.y);
    vec2 view = (uv - 0.5) * aspect;
    float radius = length(view);
    vec2 direction = view / max(radius, 0.001);
    float angle = radius > 0.0 ? atan(direction.y, direction.x) : 0.0;
    float sector = (angle + 3.141593) * (56.0 / 6.283186);
    float variation = random(floor(sector) + 0.7);

    if (phase == 1) {
        // Two-tone contact drawing with a pale tear and tapering radial ink.
        vec2 dx = vec2(1.5 * pixel.x, 0.0);
        vec2 dy = vec2(0.0, 1.5 * pixel.y);
        float edge = abs(spEsriLuma(spEsriSample(uv + dx, pixel)) - spEsriLuma(spEsriSample(uv - dx, pixel)))
                   + abs(spEsriLuma(spEsriSample(uv + dy, pixel)) - spEsriLuma(spEsriSample(uv - dy, pixel)));
        float contour = smoothstep(0.065, 0.23, edge);
        float lit = smoothstep(0.32, 0.48, spEsriLuma(source.rgb));
        float rim = 1.0 - smoothstep(0.08, 0.58, radius);
        float streak = 1.0 - smoothstep(0.025, 0.10 + 0.12 * variation, abs(fract(sector) - 0.5));
        streak *= smoothstep(0.09 + 0.24 * variation, 0.32 + 0.24 * variation, radius);
        streak *= 1.0 - smoothstep(0.36 + 0.36 * variation, 0.54 + 0.36 * variation, radius);
        float tear = 1.0 - smoothstep(0.015, 0.095, radius + sin(angle * 7.0) * radius * 0.25);
        float ink = max(0.02 + lit * (0.10 + 0.40 * rim), max(contour * (0.45 + 0.30 * rim), streak * 0.68));
        return vec4(vec3(max(ink, tear * 0.86)), source.a);
    }

    // A narrow, broken pressure front kicks scene detail outward. Adding the
    // sample delta to the composed frame retains the underlying facility tint.
    bool recoil = phase == 2;
    float front = (recoil ? 0.30 : 0.61) + 0.012 * sin(angle * 7.0) + 0.008 * sin(angle * 19.0);
    float offset = radius - front;
    float band = 1.0 - smoothstep(0.010, recoil ? 0.095 : 0.055, abs(offset));
    if (band <= 0.0) return source;
    float crest = (1.0 - smoothstep(0.002, recoil ? 0.014 : 0.010, abs(offset)))
        * (0.48 + 0.52 * variation);
    vec2 pull = direction / aspect * band * (recoil ? 0.046 : 0.012);
    vec3 original = spEsriSample(uv, pixel);
    vec3 compressed = spEsriSample(uv - pull, pixel);
    vec3 fringe = spEsriSample(uv + pull * 0.35, pixel);
    vec3 rgb = source.rgb + (vec3(fringe.r, compressed.g, compressed.b) - original) * (recoil ? 0.80 : 0.36);
    rgb += vec3(0.08, 0.52, 0.68) * crest * (recoil ? 0.52 : 0.17);
    return vec4(clamp(rgb, 0.0, 1.0), source.a);
}
// STAR_ESRI_IMPACT_END
'''
CALL = '    fragColor = spEsriImpact(fragColor, texCoord, spEsriImpactControl());'


def patch_shader(source: str) -> str:
    """Return an additive, idempotent shader patch or reject unknown structure."""
    if BEGIN in source or END in source or 'spEsriImpact(' in source:
        if source.count(HELPER) != 1 or source.count(CALL) != 1:
            raise ValueError('Preserve unfamiliar ESRI impact shader implementation')
        return source
    if 'vec4 spScene(vec2 uv)' not in source or '#include <shader_selector:marker_settings.glsl>' not in source:
        raise ValueError('ESRI impact requires the accepted scene and marker shader')
    matches = list(re.finditer(r'void\s+main\s*\(\s*\)\s*\{', source))
    if len(matches) != 1:
        raise ValueError('ESRI impact requires one post shader main function')
    match = matches[0]
    depth = 1
    end = match.end()
    while end < len(source) and depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    if depth or 'fragColor' not in source[match.end():end]:
        raise ValueError('ESRI impact requires a complete output shader')
    return source[:match.start()] + HELPER + '\n' + source[match.start():end - 1] + CALL + '\n' + source[end - 1:]


def upgrade_shader(source: str) -> str:
    """Replace the accepted ESRI helper without changing the surrounding shader."""
    if source.count(BEGIN) != 1 or source.count(END) != 1 or source.count(CALL) != 1:
        raise ValueError('Missing or ambiguous installed ESRI shader')
    start = source.index(BEGIN)
    stop = source.index(END) + len(END)
    if sha256(source[start:stop].encode('utf-8')).hexdigest() != LEGACY_HELPER_SHA256:
        return patch_shader(source)
    return patch_shader(source[:start] + HELPER.rstrip('\n') + source[stop:])


def patch_entries(entries: dict[str, bytes]) -> dict:
    """Mutate the one shader entry and report exact changed paths and protocol."""
    if SHADER_PATH not in entries:
        raise ValueError('Missing existing post shader')
    before = entries[SHADER_PATH]
    after = patch_shader(before.decode('utf-8')).encode('utf-8')
    entries[SHADER_PATH] = after
    return {'changedFiles': [SHADER_PATH] if after != before else [],
            'channel': 7, 'green': 245, 'neutralByte': 0,
            'hitFrameBytes': [1, 2, 3], 'hitFrameTicks': 4,
            'discretePayload': True, 'stalePacketTimeoutSeconds': 0.05,
            'preservesExistingPostEffects': True}
