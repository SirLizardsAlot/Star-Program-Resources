"""Prepare isolated menu font assets, or add them to the current pinned pack.

No publication, resource-pack pin, portal state, game source, or shared build is
changed. `prepare` writes only the additive source/overlay ZIP in main-menu/.
`build` rereads the current pin and creates a complete staged pack there.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
from urllib.parse import unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageDraw


GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
OUT = ROOT / 'main-menu'
PIN = GAME / 'config/resource-pack.json'
CLIENT = GAME.parent / 'plot-locations/.local/gradle-home/caches/fabric-loom/26.3/minecraft-client.jar'
PLAN = GAME.parent / 'ui-design/main-menu-2026-10-30/design-plan-v3.json'
LIMIT = 41943040
FONT = 'star_program:menu'
SMALL_FONT = 'star_program:menu_small'
STAMP = (1980, 1, 1, 0, 0, 0)
ROLES = {
    'operator': {'color': '#5555ff', 'surface': '#202b50', 'edge': '#465d9c'},
    'scientist': {'color': '#55ffff', 'surface': '#17434b', 'edge': '#3a7f87'},
    'maintenance': {'color': '#ffaa00', 'surface': '#4b381b', 'edge': '#97703c'},
    'security': {'color': '#3333bd', 'surface': '#17213e', 'edge': '#354674'},
    'raider': {'color': '#ff5555', 'surface': '#492329', 'edge': '#944750'},
}
SPRITES = {
    'operator': '<sprite:"minecraft:items":item/redstone>',
    'scientist': '<sprite:"minecraft:items":item/brewing_stand>',
    'maintenance': '<sprite:"minecraft:items":item/iron_pickaxe>',
    'security': '<sprite:"minecraft:items":item/iron_chestplate>',
    'raider': '<sprite:"minecraft:items":item/crossbow_standby>',
    'lock': '<sprite:"minecraft:gui":container/cartography_table/locked>',
    'star': '<sprite:"minecraft:items":item/nether_star>',
}
STATES = ('normal', 'selected', 'locked')
STRIPS = ('top', 'middle', 'bottom')
KINDS = {'card': 56, 'panel': 220}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value, compact=False):
    kwargs = {'ensure_ascii': True, 'sort_keys': True}
    if compact:
        kwargs['separators'] = (',', ':')
    else:
        kwargs['indent'] = 2
    return (json.dumps(value, **kwargs) + '\n').encode('utf-8')


def rgb(color):
    return tuple(bytes.fromhex(color.removeprefix('#')))


def darken(color):
    # Same black-blue 74 percent lock veil as the approved colored-card mockup.
    return tuple(int(a * .26 + b * .74 + .5) for a, b in zip(rgb(color), (4, 6, 10)))


def strip_texture(width, colors, state):
    surface, edge, accent = (rgb(colors[k]) for k in ('surface', 'edge', 'color'))
    if state == 'selected':
        edge = rgb('#d1e3f2')
    if state == 'locked':
        surface, edge, accent = (darken(colors[k]) for k in ('surface', 'edge', 'color'))
    image = Image.new('RGBA', (width, 30))
    draw = ImageDraw.Draw(image)
    for index, strip in enumerate(STRIPS):
        y = index * 10
        draw.rectangle((0, y, width - 1, y + 9), fill=surface + (255,))
        draw.line((0, y, 0, y + 9), fill=edge + (255,))
        draw.line((width - 1, y, width - 1, y + 9), fill=edge + (255,))
        if strip == 'top':
            draw.line((0, y, width - 1, y), fill=edge + (255,))
            draw.line((1, y + 1, width - 2, y + 1), fill=accent + (255,))
        if strip == 'bottom':
            draw.line((0, y + 9, width - 1, y + 9), fill=edge + (255,))
    target = BytesIO()
    image.save(target, format='PNG', optimize=False, compress_level=9)
    return target.getvalue()


def ascii_source():
    with ZipFile(CLIENT) as client:
        version = json.loads(client.read('version.json'))
        require(version['id'] == '26.3', 'Expected the local Minecraft 26.3 client')
        default = json.loads(client.read('assets/minecraft/font/include/default.json'))
        provider = next(p for p in default['providers'] if p.get('file') == 'minecraft:font/ascii.png')
        pixels = client.read('assets/minecraft/textures/font/ascii.png')
    image = Image.open(BytesIO(pixels)).convert('RGBA')
    require(image.size == (128, 128), 'Unexpected vanilla ASCII texture dimensions')
    widths = {}
    for char in map(chr, range(33, 127)):
        index = ord(char)
        tile = image.crop((index % 16 * 8, index // 16 * 8, index % 16 * 8 + 8, index // 16 * 8 + 8))
        box = tile.getbbox()
        require(box is not None, 'Missing vanilla ASCII glyph: ' + char)
        widths[char] = box[2]
    # BitmapProvider.Definition native formula: int(.5 + pixelWidth * height / cellHeight) + 1.
    small = {char: int(.5 + width * .75) + 1 for char, width in widths.items()}
    normal = {char: width + 1 for char, width in widths.items()}
    small[' '], normal[' '] = 3, 4
    return provider, small, normal, sha(pixels), image


def make_sources():
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    require(plan['revision'] == 3, 'Expected the approved colored-card design revision')
    require(plan['visualDirection']['sprites'] == SPRITES, 'Approved native sprite mapping changed')
    ascii_provider, small, normal, ascii_sha, ascii_image = ascii_source()
    sources, providers, glyphs = {}, [], {}
    codepoint = 0xE000
    for kind, width in KINDS.items():
        glyphs[kind] = {}
        for role, colors in ROLES.items():
            glyphs[kind][role] = {}
            for state in STATES:
                chars = [chr(codepoint + i) for i in range(3)]
                codepoint += 3
                glyphs[kind][role][state] = dict(zip(STRIPS, chars))
                name = f'assets/star_program/textures/font/menu/{kind}_{role}_{state}.png'
                sources[name] = strip_texture(width, colors, state)
                providers.append({'type': 'bitmap', 'file': f'star_program:font/menu/{kind}_{role}_{state}.png',
                                  'height': 10, 'ascent': 8, 'chars': chars})
    spaces = {str(advance): chr(0xE100 + advance + 256) for advance in range(-256, 257)}
    require(codepoint <= 0xE100, 'Bitmap PUA overlaps the spacing PUA range')
    providers.append({'type': 'space', 'advances': {char: int(advance) for advance, char in spaces.items()}})
    sources['assets/star_program/font/menu.json'] = encoded({'providers': providers}, compact=True)
    small_provider = dict(ascii_provider, height=6, ascent=5)
    sources['assets/star_program/font/menu_small.json'] = encoded({'providers': [
        {'type': 'space', 'advances': {' ': 3}}, small_provider,
        {'type': 'reference', 'id': 'minecraft:default'},
    ]}, compact=True)
    glyph_map = {
        'version': 1,
        'fonts': {'panel': FONT, 'small': SMALL_FONT, 'space': FONT, 'default': 'minecraft:default'},
        'glyphs': glyphs,
        'spaces': spaces,
        'widths': {'card': {'paint': 56, 'advance': 57, 'step': 58, 'gap': 2, 'padding': 3},
                   'panel': {'paint': 220, 'advance': 221, 'padding': 6},
                   'fiveCards': 288, 'sprite': 8, 'compactBar': 40, 'wideBar': 100},
        'rows': {'height': 10, 'ascent': 8, 'lineHeight': 9, 'overlap': 1,
                 'cardLines': 12, 'cardVisibleHeight': 109,
                 'text': {'height': 6, 'ascent': 5}},
        'metrics': {'small': small, 'default': normal, 'boldExtraAdvance': 1},
        'colors': ROLES,
        'sprites': SPRITES,
        'composition': {
            'backgroundReset': {'card': spaces['-57'], 'panel': spaces['-221']},
            'rowFormula': 'background + space[-advance] + space[left] + content + space[paint-left-contentWidth] + gap',
            'centerLeftFormula': 'floor((paint-contentWidth)/2)',
            'lastCellGap': 0,
            'styles': 'Panel and spacing components: font star_program:menu, white, bold false, italic false, shadow false. Text uses its own explicit font and color. Apply one card click event to all components in that card.',
            'wrap': 'Wrap between complete card components or construct separate centered card rows. Do not insert ordinary spaces inside a cell to position text. A five-card line measures 288 GUI pixels.',
            'lineHeight': 'Native plain_message advances 9 GUI pixels per newline. Twelve 10-pixel strips overlap by 1 pixel, painting 109 GUI pixels. Reserve at least 1 extra bottom pixel to avoid clipping.',
            'smallText': 'Width metrics assume no bold or italic. Use small font only for compact labels, not bar output. Long ranks require manual line breaks within their card.',
            'progress': 'Call the existing progress bar helper with length40 or100. Keep the returned bar component in minecraft:default. Its | plus U+EEFE primitive advances1. Do not recolor its inherited child runs or rewrite the helper.',
            'objects': 'Render the provided MiniMessage sprite objects directly at native8x8 size. No icon textures are supplied by this overlay.',
        },
    }
    validate_sources(sources, glyph_map)
    return sources, glyph_map, ascii_sha, ascii_image


def validate_sources(sources, glyph_map):
    require(set(sources) == {name for name in sources if name.startswith('assets/star_program/font/menu')
                             or name.startswith('assets/star_program/textures/font/menu/')}, 'Unexpected overlay namespace')
    require(not any('/minecraft/' in name for name in sources), 'Must not edit default or vanilla resources')
    all_chars = []
    for kind, roles in glyph_map['glyphs'].items():
        for role, states in roles.items():
            for state, strips in states.items():
                all_chars.extend(strips.values())
                image = Image.open(BytesIO(sources[f'assets/star_program/textures/font/menu/{kind}_{role}_{state}.png']))
                require(image.size == (KINDS[kind], 30), 'Unexpected strip atlas dimensions')
                require(KINDS[kind] <= 256 and 10 <= 256, 'Glyph cell exceeds the native atlas limit')
                require(image.getextrema()[3] == (255, 255), 'Panel strip must be fully opaque')
    all_chars.extend(glyph_map['spaces'].values())
    require(len(all_chars) == len(set(all_chars)), 'Menu PUA collision')
    require(sum(glyph_map['metrics']['small'][c] for c in 'Maintenance') <= 56 - 6, 'Maintenance does not fit its compact card')
    require(40 <= 56 - 6 and 100 <= 220 - 12, 'Core bars do not fit their panel padding')


def archive_of(sources):
    buffer = BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(sources.items()):
            info = ZipInfo(name, STAMP)
            info.compress_type = ZIP_DEFLATED
            info.create_system, info.external_attr = 3, 0o100644 << 16
            archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def zip_parts(data):
    start = max(0, len(data) - 65557)
    pos = data.rfind(b'PK\x05\x06', start)
    require(pos >= 0, 'Missing ZIP end record')
    values = struct.unpack_from('<4s4H2IH', data, pos)
    _, disk, central_disk, disk_count, count, size, offset, comment_len = values
    require(pos + 22 + comment_len == len(data), 'Unsupported trailing data or false ZIP end record')
    require(disk == central_disk == 0 and disk_count == count, 'Multidisk ZIP is unsupported')
    require(count < 65535 and offset + size == pos, 'ZIP64 or nonstandard central directory is unsupported')
    return {'count': count, 'offset': offset, 'size': size, 'comment': data[pos + 22:],
            'local': data[:offset], 'central': data[offset:pos]}


def relocate_central(data, offset):
    result, cursor, count = bytearray(), 0, 0
    while cursor < len(data):
        require(data[cursor:cursor + 4] == b'PK\x01\x02', 'Invalid central-directory entry')
        name_len, extra_len, comment_len = struct.unpack_from('<3H', data, cursor + 28)
        size = 46 + name_len + extra_len + comment_len
        entry = bytearray(data[cursor:cursor + size])
        old_offset = struct.unpack_from('<I', entry, 42)[0]
        struct.pack_into('<I', entry, 42, old_offset + offset)
        result.extend(entry)
        cursor += size
        count += 1
    require(cursor == len(data), 'Truncated central-directory entry')
    return bytes(result), count


def additive_archive(base, overlay, sources):
    old, new = zip_parts(base), zip_parts(overlay)
    with ZipFile(BytesIO(base)) as before, ZipFile(BytesIO(overlay)) as additions:
        names = before.namelist()
        require(len(names) == len(set(names)), 'Base archive contains duplicate names')
        require(before.testzip() is None, 'Base archive failed its CRC check')
        require(not set(names).intersection(additions.namelist()), 'Menu assets already exist in pinned base, refusing to overwrite')
    added_central, count = relocate_central(new['central'], len(old['local']))
    require(count == new['count'], 'Additive central entry count mismatch')
    local = old['local'] + new['local']
    central = old['central'] + added_central
    total = old['count'] + new['count']
    require(total < 65535, 'ZIP entry count would require ZIP64')
    end = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, total, total, len(central), len(local), len(old['comment']))
    combined = local + central + end + old['comment']
    require(len(combined) <= LIMIT, 'Merged menu pack exceeds the40 MiB DiamondFire limit')
    with ZipFile(BytesIO(base)) as before, ZipFile(BytesIO(combined)) as after:
        require(after.testzip() is None, 'Merged archive failed its CRC check')
        require(set(after.namelist()) == set(before.namelist()) | set(sources), 'Unexpected merged pack membership')
        require(all(before.read(name) == after.read(name) for name in before.namelist()), 'An existing resource changed')
        require(all(after.read(name) == value for name, value in sources.items()), 'An added resource differs')
    require(combined[:old['offset']] == base[:old['offset']], 'Existing compressed ZIP bytes changed')
    merged_parts = zip_parts(combined)
    require(merged_parts['central'][:len(old['central'])] == old['central'], 'Existing ZIP metadata changed')
    return combined, old['count']


def pinned_base(explicit=None):
    pin_bytes = PIN.read_bytes()
    pin = json.loads(pin_bytes)
    require(pin['projectId'] == 'c2090ff7-7646-43f5-a2c5-7398d88f4487', 'Wrong portal resource-pack project')
    require(pin['targetMinecraft'] == '26.3', 'Menu sources currently target Minecraft26.3')
    name = PurePosixPath(unquote(urlparse(pin['url']).path)).name
    require(name.endswith('.zip'), 'Current pack pin does not name a ZIP')
    candidates = [Path(explicit)] if explicit else [ROOT / name, *sorted(ROOT.glob('*/' + name))]
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            if sha(data) == pin['sha256']:
                require(hashlib.sha1(data).hexdigest() == pin['sha1'] and len(data) == pin['size'], 'Pinned base hash or length mismatch')
                return data, pin, pin_bytes, path
    raise ValueError('Current pinned archive is not available locally with the expected hash: ' + name)


def write_generated(files):
    manifest_path = OUT / 'generated-files.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, value in files.items():
        path = OUT / name
        require(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts, 'Unsafe generated path')
        if path.exists() and path.read_bytes() != value:
            require(previous.get(name) == sha(path.read_bytes()), 'Preserve manually changed or unowned output: ' + str(path))
    for name, value in files.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != value:
            path.write_bytes(value)
    manifest_path.write_bytes(encoded({**previous, **{name: sha(value) for name, value in files.items()}}))


def prepare(build_pack=False, base_path=None):
    sources, glyph_map, ascii_sha, ascii_image = make_sources()
    overlay = archive_of(sources)
    require(overlay == archive_of(sources), 'Overlay ZIP is not reproducible')
    base, pin, pin_bytes, path = pinned_base(base_path)
    merged, retained_count = additive_archive(base, overlay, sources)
    report = {
        'version': 1, 'mode': 'build' if build_pack else 'prepare',
        'projectId': pin['projectId'], 'targetMinecraft': pin['targetMinecraft'],
        'baseUrl': pin['url'], 'basePath': path.relative_to(GAME.parent).as_posix() if path.is_relative_to(GAME.parent) else path.as_posix(),
        'baseSHA256': sha(base), 'baseSize': len(base), 'retainedEntries': retained_count,
        'overlay': {'path': 'menu-font-overlay.zip', 'sha256': sha(overlay), 'size': len(overlay), 'addedEntries': len(sources)},
        'merged': {'written': build_pack, 'path': 'sp_main-menu-font-mc26.3.zip' if build_pack else None,
                   'sha256': sha(merged), 'sha1': hashlib.sha1(merged).hexdigest(), 'size': len(merged), 'limit': LIMIT},
        'designSHA256': sha(PLAN.read_bytes()), 'vanillaASCIITextureSHA256': ascii_sha,
        'glyphCount': 90, 'spaceGlyphCount': 513, 'bitmapCellLimit': 256,
        'checks': {'uniqueNames': True, 'allBaseEntriesByteIdentical': True,
                   'allBaseCompressedRecordsByteIdentical': True, 'allBaseCentralRecordsByteIdentical': True,
                   'namespacedOnly': True, 'noDefaultFontChanges': True, 'noImportedIconAssets': True,
                   'compactMaintenanceFits': True, 'nativeBarFits': True, 'cellBounds': True,
                   'crc': True, 'withinPackLimit': True, 'reproducibleOverlay': True},
    }
    files = {**sources, 'glyph-map.json': encoded(glyph_map, compact=True),
             'menu-font-overlay.zip': overlay, 'build-report.json': encoded(report)}
    if build_pack:
        files['sp_main-menu-font-mc26.3.zip'] = merged
    require(PIN.read_bytes() == pin_bytes, 'Resource-pack pin changed during preparation. Rerun against the current pin.')
    write_generated(files)
    print(json.dumps({'mode': report['mode'], 'addedEntries': len(sources), 'glyphs': 90,
                      'overlayBytes': len(overlay), 'mergedBytes': len(merged),
                      'baseSHA256': sha(base), 'glyphMap': str(OUT / 'glyph-map.json'),
                      'report': str(OUT / 'build-report.json')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'build'], nargs='?', default='prepare')
    parser.add_argument('--base', help='Optional local archive. Its hash must match the current resource-pack pin.')
    args = parser.parse_args()
    prepare(args.action == 'build', args.base)
