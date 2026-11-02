"""Move the exact existing sky bitmaps out of GPU shader constant arrays.

Only this directory is written. The archived pack and earlier source remain
read-only. Both PNG resources contain identical, fully opaque texture data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile
import zlib


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'sp_sky-panels-one-way-mc26.3.zip'
SOURCE_SHA256 = 'c9b21a204b8a8b9c6e6e7e2597fb38115750f7ed3651098ce7ac3ecea1fa00f2'
SOURCE_INCLUDE = 'assets/dfsky/shaders/include/vanilla_data.glsl'
WIDTH, HEIGHT = 256, 128
LAYOUT = {
    'marker': [0, 0, 16, 16],
    'header': [[16, 0], [17, 0]],
    'cloud': [0, 16, 128, 64],
    'sunRGB': [128, 16, 32, 32],
    'sunAlpha': [160, 16, 32, 32],
    'moonRGB': [192, 16, 32, 32],
    'moonAlpha': [224, 16, 32, 32],
}


INCLUDE = '''// Generated from the archived native sky data. Bitmap data lives in
// texture storage instead of dynamically indexed shader constant arrays.
#ifndef DFSKY_VANILLA_DATA_GLSL
#define DFSKY_VANILLA_DATA_GLSL
#ifndef DFSKY_SAMPLER
#error Define DFSKY_SAMPLER before including the sky data helpers.
#endif

// Geometry selects the marker sprite's origin in the block atlas. The post
// effect binds the identical standalone data texture and leaves this at zero.
ivec2 dfskyDataOrigin = ivec2(0);

bool dfsky_cloudCell(ivec2 cell) {
    ivec2 wrapped = cell & ivec2(255);
    int cellIndex = wrapped.x + wrapped.y * 256;
    int byteIndex = cellIndex >> 3;
    ivec2 pixel = ivec2(byteIndex & 127, 16 + (byteIndex >> 7));
    int bits = int(round(texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + pixel, 0).r * 255.0));
    return (bits & (1 << (cellIndex & 7))) != 0;
}

vec4 dfsky_sunTexture(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    ivec2 pixel = min(ivec2(floor(uv * 32.0)), ivec2(31));
    vec3 rgb = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(128, 16) + pixel, 0).rgb;
    float alpha = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(160, 16) + pixel, 0).r;
    return vec4(rgb, alpha);
}

vec4 dfsky_moonTexture(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    ivec2 pixel = min(ivec2(floor(uv * 32.0)), ivec2(31));
    vec3 rgb = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(192, 16) + pixel, 0).rgb;
    float alpha = texelFetch(DFSKY_SAMPLER, dfskyDataOrigin + ivec2(224, 16) + pixel, 0).r;
    return vec4(rgb, alpha);
}
#endif
'''


def source_data() -> tuple[bytes, dict[str, list[int]]]:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('The immutable source sky pack changed')
    with ZipFile(SOURCE) as archive:
        include = archive.read(SOURCE_INCLUDE)
    arrays = {}
    pattern = r'const uint (DFSKY_\w+)\[(\d+)\]\s*=\s*uint\[\d+\]\((.*?)\);'
    for name, count, body in re.findall(pattern, include.decode(), re.S):
        values = [int(value, 16) for value in re.findall(r'0x([0-9a-fA-F]+)u', body)]
        if len(values) != int(count):
            raise ValueError('Unexpected source array length: ' + name)
        arrays[name] = values
    expected = {'DFSKY_CLOUD_MASK': 2048, 'DFSKY_SUN_PALETTE': 44,
                'DFSKY_SUN_PIXELS': 256, 'DFSKY_MOON_PALETTE': 48,
                'DFSKY_MOON_PIXELS': 256}
    if {name: len(values) for name, values in arrays.items()} != expected:
        raise ValueError('Unexpected source sky data arrays')
    return include, arrays


def cloud_value(arrays, x: int, y: int) -> bool:
    index = (x & 255) + (y & 255) * 256
    return bool((arrays['DFSKY_CLOUD_MASK'][index >> 5] >> (index & 31)) & 1)


def celestial_value(arrays, kind: str, x: int, y: int) -> tuple[int, int, int, int]:
    index = x + y * 32
    word = arrays[f'DFSKY_{kind}_PIXELS'][index // 4]
    palette_index = (word >> ((index % 4) * 8)) & 255
    rgba = arrays[f'DFSKY_{kind}_PALETTE'][palette_index]
    return tuple((rgba >> shift) & 255 for shift in (0, 8, 16, 24))


def make_pixels(arrays) -> bytes:
    pixels = bytearray(bytes((0, 0, 0, 255)) * WIDTH * HEIGHT)

    def put(x, y, rgba):
        offset = (x + y * WIDTH) * 4
        pixels[offset:offset + 4] = bytes(rgba)

    for y in range(16):
        for x in range(16):
            put(x, y, (x, y, 173, 255))
    put(16, 0, (17, 239, 173, 255))
    put(17, 0, (91, 37, 211, 255))
    for byte_index in range(8192):
        word = arrays['DFSKY_CLOUD_MASK'][byte_index >> 2]
        bits = (word >> ((byte_index & 3) * 8)) & 255
        put(byte_index & 127, 16 + (byte_index >> 7), (bits, 0, 0, 255))
    for kind, rgb_x, alpha_x in [('SUN', 128, 160), ('MOON', 192, 224)]:
        for y in range(32):
            for x in range(32):
                r, g, b, a = celestial_value(arrays, kind, x, y)
                put(rgb_x + x, 16 + y, (r, g, b, 255))
                put(alpha_x + x, 16 + y, (a, 0, 0, 255))
    return bytes(pixels)


def png_rgba(pixels: bytes) -> bytes:
    if len(pixels) != WIDTH * HEIGHT * 4:
        raise ValueError('Expected a 256 by 128 RGBA image')

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))

    stride = WIDTH * 4
    rows = b''.join(b'\0' + pixels[start:start + stride] for start in range(0, len(pixels), stride))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


def decode_generated_png(data: bytes) -> bytes:
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid PNG')
    cursor, compressed = 8, bytearray()
    while cursor < len(data):
        length = struct.unpack_from('>I', data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        body = data[cursor + 8:cursor + 8 + length]
        expected_crc = struct.unpack_from('>I', data, cursor + 8 + length)[0]
        if zlib.crc32(kind + body) != expected_crc:
            raise ValueError('PNG CRC mismatch')
        if kind == b'IHDR' and struct.unpack('>IIBBBBB', body) != (WIDTH, HEIGHT, 8, 6, 0, 0, 0):
            raise ValueError('Unexpected generated PNG layout')
        if kind == b'IDAT':
            compressed += body
        cursor += length + 12
    rows = zlib.decompress(compressed)
    stride = WIDTH * 4 + 1
    if len(rows) != stride * HEIGHT or any(rows[y * stride] != 0 for y in range(HEIGHT)):
        raise ValueError('Unexpected generated PNG filtering')
    return b''.join(rows[y * stride + 1:(y + 1) * stride] for y in range(HEIGHT))


def verify_pixels(pixels: bytes, arrays) -> dict:
    def get(x, y):
        offset = (x + y * WIDTH) * 4
        return tuple(pixels[offset:offset + 4])

    assert len(pixels) == WIDTH * HEIGHT * 4
    assert all(alpha == 255 for alpha in pixels[3::4])
    for y in range(16):
        for x in range(16):
            assert get(x, y) == (x, y, 173, 255)
    assert get(16, 0) == (17, 239, 173, 255)
    assert get(17, 0) == (91, 37, 211, 255)
    occupied = 0
    for y in range(256):
        for x in range(256):
            cell_index = x + y * 256
            byte_index = cell_index >> 3
            bits = get(byte_index & 127, 16 + (byte_index >> 7))[0]
            actual = bool(bits & (1 << (cell_index & 7)))
            assert actual == cloud_value(arrays, x, y), (x, y)
            occupied += actual
    for kind, rgb_x, alpha_x in [('SUN', 128, 160), ('MOON', 192, 224)]:
        for y in range(32):
            for x in range(32):
                actual = get(rgb_x + x, y + 16)[:3] + (get(alpha_x + x, y + 16)[0],)
                assert actual == celestial_value(arrays, kind, x, y), (kind, x, y)
    return {'cloudCellsCompared': 65536, 'occupiedCloudCells': occupied,
            'celestialTexelsCompared': 2048, 'markerTexelsCompared': 256,
            'allOutputAlpha255': True}


def make_data() -> dict[str, bytes]:
    _, arrays = source_data()
    pixels = make_pixels(arrays)
    verify_pixels(pixels, arrays)
    image = png_rgba(pixels)
    assert decode_generated_png(image) == pixels
    return {'assets/dfsky/textures/block/sky_marker.png': image,
            'assets/dfsky/textures/effect/sky_data.png': image,
            SOURCE_INCLUDE: INCLUDE.encode()}


def prepare() -> dict:
    original, arrays = source_data()
    patches = make_data()
    for name, content in patches.items():
        target = HERE / 'overrides' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    image = patches['assets/dfsky/textures/effect/sky_data.png']
    checks = verify_pixels(decode_generated_png(image), arrays)
    report = {'version': 1, 'sourcePack': SOURCE.name, 'sourcePackSHA256': SOURCE_SHA256,
              'sourceIncludeSHA256': hashlib.sha256(original).hexdigest(),
              'sourceIncludeBytes': len(original), 'newIncludeBytes': len(patches[SOURCE_INCLUDE]),
              'textureSize': [WIDTH, HEIGHT], 'texturePNGBytes': len(image),
              'textureSHA256': hashlib.sha256(image).hexdigest(), 'layout': LAYOUT,
              'checks': checks | {'cloudCellsPerDataByte': 8,
                                 'duplicatePNGsByteIdentical': patches['assets/dfsky/textures/block/sky_marker.png'] == image,
                                 'PNGPixelRoundtripExact': True, 'shaderConstantArraysRemoved': 'const uint ' not in INCLUDE}}
    (HERE / 'data-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(prepare(), indent=2))
