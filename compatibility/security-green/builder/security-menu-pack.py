"""Prepare and publish a six-texture Security palette layer over the current pack.

prepare and commit are local. publish, verify and pin are explicit later steps.
Only pin changes the runtime resource configuration and live glyph metadata.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from zipfile import ZipFile

from PIL import Image, ImageDraw

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
HERE = ROOT / 'security-green'
SOURCE = ROOT / 'menu-full-size-publication'
CHECKOUT = ROOT / 'security-green-publication'
CONFIG = GAME / 'config/resource-pack.json'
GLYPH = ROOT / 'main-menu/glyph-map.json'
PARENT = '887ff0c7277c63c6479d82b54ca761c9b649f464'
BASE_NAME = 'sp_menu-full-size-mc26.3.zip'
BASE_SHA256 = '6a6295e2cf588a1f1a3cabdbdeedeba2f46258d2de4461dfea9c97c26ffdce71'
BASE_SHA1 = '7000c7fc4b1ab2711502a806fa163f97cbac0171'
BASE_SIZE = 16277189
BASE_GLYPH_SHA = '7a781274f822eb35bcb453991c695e3b8b9dc462a8d7f880ffc21806f0e94fff'
BASE_MANIFEST_SHA = 'a046361397e9c485d26092f3563f622afa06c007843e309be2612e2fcef00884'
PACK = 'sp_security-green-mc26.3.zip'
PREFIX = 'compatibility/security-green/'
MANIFEST = PREFIX + 'manifest.json'
GLYPH_PATH = PREFIX + 'glyph-map.json'
BRANCH = 'codex/star-program-security-green'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
LIMIT = 41943040
PROJECT = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
PALETTE = {'color': '#55ff55', 'surface': '#173b27', 'edge': '#3f8656'}
BACKUP = CONFIG.parent / 'backups/resource-pack-before-security-green-6a6295e2cf58.json'
GLYPH_BACKUP = HERE / 'glyph-map-before.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def read(path):
    return json.loads(path.read_bytes())


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing existing file: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as target:
        target.write(data)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


font = module('security_menu_font', GAME / 'tools/main-menu-font-pack.py')
archive = module('security_menu_zip', GAME / 'tools/menu-full-size-pack.py')


def git(repo, *args, raw=False, check=True):
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'safe.directory=' + repo.as_posix(), '-C', str(repo), *args], capture_output=True)
    if not check:
        return result
    require(result.returncode == 0, result.stderr.decode(errors='replace').strip() or 'Git operation failed')
    return result.stdout if raw else result.stdout.decode().strip()


def source_state():
    return (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'symbolic-ref', '-q', '--short', 'HEAD', raw=True, check=False).stdout,
            git(SOURCE, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True))


def assert_parent(pin):
    require(pin.get('projectId') == PROJECT and pin.get('targetMinecraft') == '26.3' and pin.get('resourceFormat') == [97, 1], 'Wrong pack project or format')
    require(pin.get('url') == f'{RAW}/{PARENT}/{BASE_NAME}' and pin.get('sha256') == BASE_SHA256 and pin.get('sha1') == BASE_SHA1
            and pin.get('size') == BASE_SIZE and pin.get('publication', {}).get('commit') == PARENT, 'Current pack pin changed')
    require(pin.get('mainMenuFont', {}).get('glyphMapSHA256') == BASE_GLYPH_SHA
            and pin['mainMenuFont'].get('manifestSha256') == BASE_MANIFEST_SHA, 'Current menu metadata changed')


def base_archive():
    for path in [ROOT / 'menu-full-size' / BASE_NAME, SOURCE / BASE_NAME, ROOT / BASE_NAME]:
        if path.is_file():
            data = path.read_bytes()
            if sha(data) == BASE_SHA256:
                require(len(data) == BASE_SIZE and hashlib.sha1(data).hexdigest() == BASE_SHA1, 'Base pack size or SHA-1 differs')
                return path, data
    raise ValueError('Exact current pinned archive is unavailable locally')


def text(image, xy, value, ascii_image, color):
    x, y = xy
    for char in value:
        code = ord(char)
        tile = ascii_image.crop((code % 16 * 8, code // 16 * 8, code % 16 * 8 + 8, code // 16 * 8 + 8))
        bounds = tile.getbbox()
        for py in range(8):
            for px in range(8):
                if tile.getpixel((px, py))[3] > 127:
                    image.putpixel((x + px, y + py), (*font.rgb(color), 255))
        x += bounds[2] + 1 if bounds else 4


def native_card(atlas, state, ascii_image, metrics, icon, lock):
    image = Image.new('RGBA', (66, 109))
    for line in range(12):
        offset = 0 if line == 0 else 20 if line == 11 else 10
        image.alpha_composite(atlas.crop((0, offset, 66, offset + 10)), (0, line * 9))
    def centered(value, row, color='#eeeeee'):
        width = sum(metrics.get(char, metrics['?']) for char in value)
        text(image, ((66 - width) // 2, row * 9), value, ascii_image, color)
    image.alpha_composite(icon.resize((8, 8), Image.Resampling.NEAREST), (29, 18))
    centered('Security', 4)
    centered('Cadet', 5)
    if state == 'locked':
        image.alpha_composite(lock.resize((8, 8), Image.Resampling.NEAREST), (29, 54))
        centered('LVL 2', 7, '#aaaaaa')
    else:
        draw = ImageDraw.Draw(image)
        draw.rectangle((13, 63, 52, 67), fill='#555555')
        draw.rectangle((13, 63, 32, 67), fill='#55ffff')
        centered('125 XP', 8)
        if state == 'selected':
            centered('Current', 9)
    return image


def previews(base, patches, glyph):
    _, _, metrics, _, ascii_image = font.ascii_source()
    with ZipFile(font.CLIENT) as client:
        icon = Image.open(BytesIO(client.read('assets/minecraft/textures/item/iron_chestplate.png'))).convert('RGBA')
        lock = Image.open(BytesIO(client.read('assets/minecraft/textures/gui/sprites/container/cartography_table/locked.png'))).convert('RGBA')
    output = {}
    sheet = Image.new('RGBA', (228, 254), '#17191c')
    with ZipFile(BytesIO(base)) as old:
        for column, state in enumerate(font.STATES):
            name = f'assets/star_program/textures/font/menu/card_security_{state}.png'
            before = native_card(Image.open(BytesIO(old.read(name))).convert('RGBA'), state, ascii_image, metrics, icon, lock)
            after = native_card(Image.open(BytesIO(patches[name])).convert('RGBA'), state, ascii_image, metrics, icon, lock)
            sheet.alpha_composite(before, (6 + column * 76, 16))
            sheet.alpha_composite(after, (6 + column * 76, 139))
            text(sheet, (6 + column * 76, 3), state.title(), ascii_image, '#eeeeee')
            target = BytesIO(); after.resize((198, 327), Image.Resampling.NEAREST).save(target, format='PNG')
            output[f'preview/security-{state}.png'] = target.getvalue()
    target = BytesIO(); sheet.resize((684, 762), Image.Resampling.NEAREST).save(target, format='PNG')
    output['preview/security-blue-green-comparison.png'] = target.getvalue()
    return output


def prepare():
    pin_bytes = CONFIG.read_bytes(); pin = json.loads(pin_bytes); assert_parent(pin)
    glyph_before = GLYPH.read_bytes(); require(sha(glyph_before) == BASE_GLYPH_SHA, 'Preserve changed live glyph metadata')
    require(font.ROLES['security'] == PALETTE, 'Canonical generator Security palette differs')
    base_path, base = base_archive()
    glyph = json.loads(glyph_before); glyph['colors']['security'] = deepcopy(PALETTE)
    require(glyph['widths']['card']['paint'] == 66 and glyph['widths']['panel']['paint'] == 220, 'Preserve current full-size menu geometry')
    glyph_bytes = font.encoded(glyph, compact=True)
    patches = {f'assets/star_program/textures/font/menu/{kind}_security_{state}.png': font.strip_texture(width, PALETTE, state)
               for kind, width in [('card', 66), ('panel', 220)] for state in font.STATES}
    require(len(patches) == 6, 'Expected exactly six Security textures')
    for name, data in patches.items():
        image = Image.open(BytesIO(data)); require(image.size == (66 if '/card_' in name else 220, 30), 'Generated atlas dimensions changed')
    data, retained = archive.replace_archive(base, patches)
    _, before_entries = archive.central_entries(base); _, after_entries = archive.central_entries(data)
    require(all(before_entries[name]['local'] == after_entries[name]['local'] for name in before_entries if name not in patches), 'Unrelated compressed bytes changed')
    with ZipFile(BytesIO(base)) as before, ZipFile(BytesIO(data)) as after:
        require(after.testzip() is None and after.namelist() == before.namelist(), 'Pack membership or CRC changed')
        require({name for name in before.namelist() if before.read(name) != after.read(name)} == set(patches), 'Unexpected changed resource')
        require(all(Image.open(BytesIO(before.read(name))).size == Image.open(BytesIO(value)).size for name, value in patches.items()), 'Atlas dimensions changed')
    require(archive.replace_archive(base, patches)[0] == data, 'Pack build is not reproducible')
    builders = {name: (GAME / 'tools' / name).read_bytes() for name in ['security-menu-pack.py', 'main-menu-font-pack.py', 'menu-full-size-pack.py']}
    report = {'version': 1, 'projectId': PROJECT, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1], 'revision': 'green-security-menu',
              'baseCommit': PARENT, 'baseURL': pin['url'], 'basePack': BASE_NAME, 'baseSHA256': BASE_SHA256, 'baseSize': BASE_SIZE,
              'packFile': PACK, 'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data), 'sizeLimitBytes': LIMIT,
              'paletteBefore': json.loads(glyph_before)['colors']['security'], 'paletteAfter': PALETTE,
              'changedExistingFiles': sorted(patches), 'addedFiles': [], 'removedFiles': [], 'unchangedEntries': retained,
              'unrelatedResourcesByteIdentical': True, 'unrelatedCompressedRecordsByteIdentical': True, 'membershipPreserved': True,
              'crc': True, 'reproducible': True, 'fontsAndProvidersUnchanged': True, 'glyphIDsAndMetricsUnchanged': True,
              'atlasSizes': {'card': [66, 30], 'panel': [220, 30]}, 'glyphMapFile': GLYPH_PATH, 'glyphMapSHA256': sha(glyph_bytes),
              'glyphMapBeforeSHA256': BASE_GLYPH_SHA, 'manifestFile': MANIFEST,
              'builderSHA256': {name: sha(value) for name, value in builders.items()}, 'runtimePinUnchanged': True}
    before_without_palette = deepcopy(json.loads(glyph_before)); before_without_palette['colors']['security'] = PALETTE
    require(glyph == before_without_palette, 'Unrelated glyph metadata changed')
    files = {'base-pin.json': pin_bytes, 'glyph-map-before.json': glyph_before, 'glyph-map.json': glyph_bytes,
             PACK: data, 'build-report.json': encoded(report), **previews(base, patches, glyph),
             **{'overrides/' + name: value for name, value in patches.items()},
             **{'builder/' + name: value for name, value in builders.items()}}
    for name, value in files.items():
        preserve(HERE / name, value)
    require(CONFIG.read_bytes() == pin_bytes and GLYPH.read_bytes() == glyph_before, 'Concurrent runtime resource edit preserved')
    return {'status': 'prepared', 'stage': str(HERE), 'baseArchive': str(base_path), 'size': len(data), 'sha256': sha(data),
            'changedTextures': 6, 'unchangedEntries': retained, 'runtimePinUnchanged': True, 'published': False}


def payload():
    report = read(HERE / 'build-report.json'); data = (HERE / PACK).read_bytes(); glyph = (HERE / 'glyph-map.json').read_bytes()
    require(report['baseCommit'] == PARENT and report['baseSHA256'] == BASE_SHA256 and sha(data) == report['sha256']
            and sha(glyph) == report['glyphMapSHA256'] and len(data) <= LIMIT, 'Prepared Security artifacts changed')
    files = {PACK: data, MANIFEST: encoded(report), GLYPH_PATH: glyph}
    for name, digest in report['builderSHA256'].items():
        value = (HERE / 'builder' / name).read_bytes(); require(sha(value) == digest, 'Prepared builder changed')
        files[PREFIX + 'builder/' + name] = value
    with ZipFile(BytesIO(data)) as pack:
        for name in report['changedExistingFiles']:
            value = (HERE / 'overrides' / name).read_bytes()
            require(pack.read(name) == value, 'Prepared source texture differs from its pack entry')
            files[PREFIX + 'source/' + name] = value
    return report, files


def check_commit(files):
    require(CHECKOUT.is_dir() and git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE
            and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong Security publication checkout')
    revision = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(git(CHECKOUT, 'rev-list', '--count', PARENT + '..' + revision) == '1', 'Expected exactly one publication commit')
    require(git(CHECKOUT, 'rev-parse', revision + '^') == PARENT, 'Unexpected publication parent')
    changed = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files), 'Unexpected publication paths')
    require(all(git(CHECKOUT, 'show', revision + ':' + name, raw=True) == value for name, value in files.items()), 'Committed publication bytes differ')
    require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'', 'Publication checkout is not clean')
    return revision


def commit():
    pin = read(CONFIG); assert_parent(pin)
    report, files = payload(); before = source_state()
    require(before[0] == PARENT and before[2] == b'' and git(SOURCE, 'remote', 'get-url', 'origin') == REMOTE, 'Preserve changed source publication checkout')
    if not CHECKOUT.exists():
        CHECKOUT.mkdir(parents=True)
        subprocess.run(['git', 'init', '--quiet', str(CHECKOUT)], check=True, capture_output=True)
        objects = SOURCE / '.git/objects'; require(objects.is_dir(), 'Missing local parent object database')
        alternates = CHECKOUT / '.git/objects/info/alternates'; alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_bytes((objects.resolve().as_posix() + '\n').encode('utf-8'))
        git(CHECKOUT, 'remote', 'add', 'origin', REMOTE)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for name in ['user.name', 'user.email']:
            value = git(SOURCE, 'config', '--get', name, check=False)
            if value.returncode == 0 and value.stdout.strip(): git(CHECKOUT, 'config', name, value.stdout.decode().strip())
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    if git(CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'', 'Preserve changed publication checkout')
        require(git(CHECKOUT, 'ls-tree', '-r', '--name-only', PARENT, '--', PACK, PREFIX) == '', 'Publication paths already exist at parent')
        for name, value in files.items(): preserve(CHECKOUT / name, value)
        git(CHECKOUT, 'add', '--', *files.keys())
        git(CHECKOUT, 'commit', '-m', 'Use green Security menu cards and panels')
    revision = check_commit(files)
    require(source_state() == before, 'Original source checkout changed')
    return {'status': 'committed', 'commit': revision, 'branch': BRANCH, 'checkout': str(CHECKOUT), 'size': report['size'], 'published': False}


def context():
    report, files = payload(); revision = check_commit(files)
    return report, files, revision


def publish():
    assert_parent(read(CONFIG)); report, _, revision = context()
    remote = git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH)
    if remote: require(remote.split()[0] == revision, 'Preserve a differing remote Security branch')
    else: git(CHECKOUT, 'push', '--set-upstream', 'origin', BRANCH + ':refs/heads/' + BRANCH)
    require(git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH).split()[0] == revision, 'Remote publication differs')
    result = {'status': 'pushed', 'branch': BRANCH, 'commit': revision, 'size': report['size']}
    preserve(HERE / 'publication-push.json', encoded(result)); return result


def verify():
    report, files, revision = context()
    for name in [PACK, MANIFEST, GLYPH_PATH]:
        request = urllib.request.Request(f'{RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-Security-menu'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(LIMIT + 1) == files[name], 'Immutable hosted artifact differs: ' + name)
    result = {'version': 1, 'status': 'published', 'commit': revision, 'branch': BRANCH, 'url': f'{RAW}/{revision}/{PACK}',
              'sha1': report['sha1'], 'sha256': report['sha256'], 'size': report['size'],
              'gitBlob': hashlib.sha1(f'blob {len(files[PACK])}\0'.encode() + files[PACK]).hexdigest(),
              'manifestFile': MANIFEST, 'manifestSha256': sha(files[MANIFEST]), 'glyphMapSHA256': sha(files[GLYPH_PATH]),
              'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'httpStatus': 200,
              'matchesLocalArtifact': True, 'remoteFilesVerified': [PACK, MANIFEST, GLYPH_PATH]}
    destination = HERE / 'publication-verification.json'
    if destination.exists():
        previous = read(destination); require(all(previous.get(key) == value for key, value in result.items() if key != 'verifiedAt'), 'Preserve differing verification')
        return previous
    preserve(destination, encoded(result)); return result


def atomic_write(path, data, suffix):
    temporary = path.with_name(path.name + suffix)
    require(not temporary.exists(), 'Preserve existing pin temporary file: ' + str(temporary))
    with temporary.open('xb') as target:
        target.write(data); target.flush(); os.fsync(target.fileno())
    os.replace(temporary, path)


def pin():
    report, files, revision = context(); verified = read(HERE / 'publication-verification.json')
    require(verified.get('status') == 'published' and verified.get('commit') == revision and verified.get('sha256') == report['sha256']
            and verified.get('matchesLocalArtifact') is True and verified.get('manifestSha256') == sha(files[MANIFEST])
            and verified.get('glyphMapSHA256') == sha(files[GLYPH_PATH]), 'Verify the exact hosted artifacts before pinning')
    before = CONFIG.read_bytes(); old_glyph = GLYPH.read_bytes(); config = json.loads(before); new_glyph = files[GLYPH_PATH]
    if config.get('sha256') == report['sha256']:
        require(config['publication']['commit'] == revision and old_glyph == new_glyph, 'Inconsistent existing Security pin')
        return {'status': 'already-pinned', 'commit': revision}
    assert_parent(config)
    require(before == (HERE / 'base-pin.json').read_bytes() and old_glyph == GLYPH_BACKUP.read_bytes()
            and sha(old_glyph) == BASE_GLYPH_SHA, 'Preserve changed runtime pin or glyph metadata')
    preserve(BACKUP, before)
    original = deepcopy(config)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    advanced = []
    for key, component in config.items():
        if isinstance(component, dict) and component.get('packCommit') == PARENT:
            component['packCommit'] = revision; advanced.append(key)
    config['mainMenuFont'].update({'glyphMapFile': GLYPH_PATH, 'glyphMapSHA256': report['glyphMapSHA256'], 'manifestFile': MANIFEST, 'manifestSha256': verified['manifestSha256']})
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    allowed = {'previousUrls', 'url', 'sha1', 'sha256', 'size', 'publication', 'mainMenuFont', *advanced}
    require(all(config[key] == value for key, value in original.items() if key not in allowed), 'Unrelated pin metadata changed')
    new_pin = encoded(config)
    # Each replace is atomic. Treat the two files as one guarded transaction:
    # install glyph metadata first, publish its pointer last, roll back on error.
    require(CONFIG.read_bytes() == before and GLYPH.read_bytes() == old_glyph, 'Concurrent resource edit preserved')
    try:
        atomic_write(GLYPH, new_glyph, '.security-green-pinning')
        require(CONFIG.read_bytes() == before, 'Concurrent resource configuration edit preserved')
        atomic_write(CONFIG, new_pin, '.security-green-pinning')
        require(CONFIG.read_bytes() == new_pin and GLYPH.read_bytes() == new_glyph, 'Security pin transaction differs')
    except Exception:
        if CONFIG.read_bytes() == new_pin: atomic_write(CONFIG, before, '.security-green-rollback')
        if GLYPH.read_bytes() == new_glyph: atomic_write(GLYPH, old_glyph, '.security-green-rollback')
        raise
    result = {'status': 'pinned', 'commit': revision, 'url': verified['url'], 'size': report['size'], 'backup': str(BACKUP), 'glyphBackup': str(GLYPH_BACKUP),
              'glyphMapSHA256': report['glyphMapSHA256'], 'advancedContainment': advanced}
    preserve(HERE / 'pin-verification.json', encoded(result)); return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'commit', 'publish', 'verify', 'pin'])
    arguments = parser.parse_args()
    print(json.dumps(globals()[arguments.action](), indent=2))
