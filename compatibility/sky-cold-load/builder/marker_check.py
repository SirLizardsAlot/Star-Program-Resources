"""Check the final pack's small marker quads and camera wire format locally.

This inspects actual generated shader source, exercises raster cell coverage
and binary camera metadata through half-float accumulation, and compiles the
real particle stage pair for opaque/translucent and every OIT phase under both
depth conventions. It never starts or contacts Minecraft.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import struct
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
SKY = HERE.parent
ROOT = SKY.parent
PACK = SKY / 'sp_sky-cold-load-mc26.3.zip'
CLIENT = ROOT / 'mc26.3/reference/minecraft-client.jar'
PARTICLE = 'assets/minecraft/shaders/core/particle.'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def require(value, message):
    if not value:
        raise AssertionError(message)


def brace_body(source, start):
    opening = source.index('{', start)
    depth = 0
    for index in range(opening, len(source)):
        depth += (source[index] == '{') - (source[index] == '}')
        if not depth:
            return source[opening + 1:index], index + 1
    raise ValueError('Unclosed shader branch')


def legacy_pos(channel):
    level = math.ceil(math.sqrt(channel)) - 1
    offset = channel - level * level - 1
    return 2 * level - offset, offset


def half(value):
    return struct.unpack('<e', struct.pack('<e', value))[0]


def determinant(m):
    a, b, c = m[0], m[1], m[2]
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def valid_map(m):
    return (all(math.isfinite(value) and abs(value) <= 1 for column in m for value in column)
            and abs(determinant(m)) > 0.000001)


def check(pack_path=PACK):
    with ZipFile(pack_path) as pack:
        vertex = pack.read(PARTICLE + 'vsh').decode()
        fragment = pack.read(PARTICLE + 'fsh').decode()
        reader = pack.read('assets/shader_selector/shaders/include/data_reader.glsl').decode()
        data = pack.read('assets/shader_selector/shaders/post/data.fsh').decode()
        post = pack.read('assets/shader_selector/shaders/post/shader.fsh').decode()
        require('bool carrier = iColor.r == MARKER_RED && iColor.g == 253;' in vertex,
                'Only the legacy frequency color may carry metadata')
        carrier, end = brace_body(vertex, vertex.index('if (carrier)'))
        other, _ = brace_body(vertex, vertex.index('else', end))
        dimensions = re.search(r'corners\[gl_VertexIndex % 4\]\s*\*\s*vec2\(([0-9.]+),\s*([0-9.]+)\)', carrier)
        require(dimensions is not None, 'Missing carrier rectangle')
        width, height = (int(float(value)) for value in dimensions.groups())
        require((width, height) == (40, 8), 'Unexpected carrier area')
        require('pixel = vec2(spMarkerPixel) + corners[gl_VertexIndex % 4];' in other,
                'Non-carriers must cover their own one-pixel cell')
        require('inverse(' not in other and 'inverse(' in carrier,
                'Non-carriers must not perform camera matrix inverses')
        require('bool metadata = iColor.r == 254 && iColor.g == 253' in fragment,
                'Fragment metadata must use the same sole carrier')
        require('if (!metadata && any(notEqual(pixel, spMarkerPixel))) discard;' in fragment,
                'Carrier padding must never overwrite the world')
        require('((spMetadataByte(pixel.x - 8) >> pixel.y) & 1) * 255' in fragment,
                'Camera transport must use binary bitplanes')

        # Pixel-center raster coverage for the actual axis-aligned rectangles.
        # All rectangles retain near-plane depth one, independently of the
        # player's position, camera projection, or framebuffer dimensions.
        metadata = {(x, y) for x in range(8, 31) for y in range(8)}
        raster = {(x, y) for x in range(width) for y in range(height)}
        carrier_visible = {pixel for pixel in raster if pixel in metadata or pixel == legacy_pos(1)}
        require(len(metadata) == 184 and len(carrier_visible) == 185,
                'Unexpected carrier output cells')
        rings = {(40 + sequence % 64, (channel - 4) * 2 + sequence // 64)
                 for channel in range(4, 8) for sequence in range(128)}
        require(len(rings) == 512 and not rings.intersection(metadata), 'Control rings overlap camera cells')
        require(not rings.intersection({legacy_pos(index) for index in (1, 2, 3)}),
                'New control cells overlap legacy control cells')
        marker_sets = 0
        for sequence in range(128):
            cells = [legacy_pos(1), legacy_pos(2), legacy_pos(3)]
            cells += [(40 + sequence % 64, (channel - 4) * 2 + sequence // 64)
                      for channel in range(4, 8)]
            require(len(set(cells)) == 7, 'A marker generation has colliding controls')
            for pixel in cells[1:]:
                require(pixel not in metadata, 'A non-carrier reaches a metadata cell')
                # A one-pixel quad and its matching fragment filter emit one
                # pixel regardless of whether its X happens to be near metadata.
                require(len({pixel}) == 1, 'Non-carrier area changed')
            marker_sets += 1

        require('ivec4(83, 80, 52, 3)' in reader and 'vec4(83.0, 80.0, 52.0, 3.0)' in data,
                'The map wire format must invalidate the old rotation-only state')
        require('return abs(determinant(map)) > 0.000001;' in reader,
                'Map validation must permit scaled and reflected invertible maps')
        require('abs(dot(rotation[column], rotation[column]) - 1.0)' not in reader,
                'Obsolete orthonormal rotation validation remains')
        require('spCameraToWorld * vec3(uv * 2.0 - 1.0, 1.0)' in post,
                'Post shader must consume the normalized NDC-to-world map')
        require('spCameraRotation[component / 3][component % 3] * 0.5 + 0.5' in fragment,
                'Camera map codec layout changed')
        require('spCameraProjection[component - 9] / 16.0' in fragment,
                'Recoil projection scale codec layout changed')

        # Exercise every byte through actual binary wire semantics, including
        # more overlapping carriers than the 39-tick particle lifespan permits.
        for overlap in (1, 7, 20, 40, 100, 400):
            for value in range(256):
                recovered = 0
                for bit in range(8):
                    payload = (value >> bit) & 1
                    blue = alpha = red = 0.0
                    for _ in range(overlap):
                        blue = half(blue + payload)
                        red = half(red + 1.0)
                        alpha = half(alpha + 1.0)
                    require(red / alpha == 1.0, 'Wire header changed through fp16 accumulation')
                    recovered |= (round(blue / alpha) & 1) << bit
                require(recovered == value, 'A binary camera metadata byte was corrupted')

        rng = random.Random(0x53504D33)
        maximum_error = 0.0
        for _ in range(1000):
            while True:
                matrix = [[rng.uniform(-1, 1) for _ in range(3)] for _ in range(3)]
                scale = max(abs(value) for column in matrix for value in column)
                matrix = [[value / scale for value in column] for column in matrix]
                if abs(determinant(matrix)) > 0.001:
                    break
            words = [round((matrix[column][row] * 0.5 + 0.5) * 65535)
                     for column in range(3) for row in range(3)]
            decoded = [[words[column * 3 + row] * (2 / 65535) - 1 for row in range(3)] for column in range(3)]
            require(valid_map(decoded), 'A valid normalized camera map was rejected')
            maximum_error = max(maximum_error, max(abs(matrix[c][r] - decoded[c][r]) for c in range(3) for r in range(3)))
        require(valid_map([[0.75, 0, 0], [0, 0.5, 0], [0, 0, -1]]),
                'A normal perspective camera map must be accepted')
        require(not valid_map([[0, 0, 0]] * 3), 'A singular map must be rejected')
        require(not valid_map([[math.nan, 0, 0], [0, 1, 0], [0, 0, 1]]), 'A nonfinite map must be rejected')

        # Compile the exact generated pair with the official frontend settings.
        validator = module('marker_shader_validator', SKY / 'validate_shaders.py')
        phases = [('translucent', {})]
        phases += [(name, {'OIT': '1', 'OIT_COEFF_COUNT': '8', 'OIT_WAVELET_RANK': '2',
                          'OIT_COEFF_ATTACHMENT_COUNT': '2', **extra}) for name, extra in (
            ('depth_bounds', {'OIT_DEPTH_BOUNDS': '1', 'OIT_ALPHA_ONLY': '1'}),
            ('transmittance', {'OIT_TRANSMITTANCE': '1', 'OIT_ALPHA_ONLY': '1'}),
            ('accumulation', {'OIT_ACCUMULATE': '1'}),
            ('additive_accumulation', {'OIT_ACCUMULATE': '1', 'OIT_ADDITIVE': '1'}))]
        compiled = []
        with ZipFile(CLIENT) as client:
            compiler = validator.Compiler(pack, client)
            try:
                for phase, variant in phases:
                    for zero_to_one in (False, True):
                        defines = dict(variant)
                        if zero_to_one:
                            defines['RENDERPEARL_DEPTH_IS_ZERO_TO_ONE'] = '1'
                        vs = compiler.compile(PARTICLE + 'vsh', defines)
                        fs = compiler.compile(PARTICLE + 'fsh', defines)
                        validator.stage_pair(vs, fs)
                        require(vs['warnings'] == 0 and fs['warnings'] == 0, 'Particle stage compilation warning')
                        compiled.append({'phase': phase, 'depthZeroToOne': zero_to_one,
                                         'vertexBytes': vs['spirvBytes'], 'fragmentBytes': fs['spirvBytes']})
            finally:
                compiler.close()

    return {
        'packSHA256': hashlib.sha256(Path(pack_path).read_bytes()).hexdigest(),
        'markerGenerationsChecked': marker_sets, 'uniqueRingCells': len(rings),
        'metadataCells': len(metadata), 'carrierRasterPixels': width * height,
        'survivingCarrierPixels': len(carrier_visible),
        'setRasterPixelsBefore': 7 * 104 * 8, 'setRasterPixelsAfter': width * height + 6,
        'binaryByteOverlapCases': 256 * 6, 'cameraMapRoundtrips': 1000,
        'maximumMapComponentError': maximum_error,
        'stagePairs': len(compiled), 'stagesCompiled': len(compiled) * 2,
        'variants': compiled, 'warnings': 0,
        'checks': {'soleMetadataCarrier': True, 'singlePixelOtherMarkers': True,
                   'allControlSequencesDistinct': True, 'carrierPaddingDiscarded': True,
                   'binaryOitCodecStable': True, 'mapValidation': True,
                   'bothDepthConventions': True, 'allOitPhases': True},
        'limits': 'Local raster-cell/codec simulation and exact ShaderC stages, not Minecraft or a live OIT GPU framebuffer.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=PACK)
    args = parser.parse_args()
    report = check(args.pack)
    (HERE / 'marker-check-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'variants'}, indent=2))
