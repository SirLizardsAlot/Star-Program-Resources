"""Build, publish and pin wider menu cards over the exact held-zoom pack.

Only fifteen existing menu card PNGs change. Unrelated compressed ZIP records
are retained, and immutable hosted bytes are verified before the local pin.
No Minecraft connection or game-code transfer is performed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import urllib.request
from zipfile import ZipFile

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
HERE = ROOT / 'menu-full-size'
CONFIG = GAME / 'config/resource-pack.json'
GLYPH = ROOT / 'main-menu/glyph-map.json'
SOURCE = ROOT / 'held-zoom-publication'
CHECKOUT = ROOT / 'menu-full-size-publication'
PARENT = 'f40b69de7512f1b3381745c0e8ae47f34f06e7b1'
BASE_SHA = '3841384c9214d983d0978a2f56c4806eae74b52c72353a5469b329d862424cb4'
BASE_NAME = 'sp_held-zoom-mc26.3.zip'
PACK = 'sp_menu-full-size-mc26.3.zip'
BRANCH = 'codex/star-program-menu-full-size'
PREFIX = 'compatibility/menu-full-size/'
MANIFEST = PREFIX + 'manifest.json'
GLYPH_PATH = PREFIX + 'glyph-map.json'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
LIMIT = 41943040
BACKUP = CONFIG.parent / 'backups/resource-pack-before-menu-full-size-3841384c9214.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode()


def read(path):
    return json.loads(path.read_bytes())


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing existing file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


font = module('menu_full_size_original_font', GAME / 'tools/main-menu-font-pack.py')


def git(repo, *args, raw=False):
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'safe.directory=' + repo.as_posix(),
                             '-C', str(repo), *args], capture_output=True)
    require(result.returncode == 0, result.stderr.decode(errors='replace').strip())
    return result.stdout if raw else result.stdout.decode().strip()


def central_entries(data):
    parts, cursor, entries = font.zip_parts(data), 0, {}
    while cursor < len(parts['central']):
        record = parts['central'][cursor:]
        require(record[:4] == b'PK\x01\x02', 'Invalid central record')
        name_size, extra_size, comment_size = struct.unpack_from('<3H', record, 28)
        size = 46 + name_size + extra_size + comment_size
        name = record[46:46 + name_size].decode('utf-8')
        require(name not in entries, 'Duplicate ZIP member')
        entries[name] = {'central': record[:size], 'offset': struct.unpack_from('<I', record, 42)[0]}
        cursor += size
    ordered = sorted(entries.values(), key=lambda entry: entry['offset'])
    for index, entry in enumerate(ordered):
        end = ordered[index + 1]['offset'] if index + 1 < len(ordered) else parts['offset']
        entry['local'] = data[entry['offset']:end]
    return parts, entries


def replace_archive(base, patches):
    old, entries = central_entries(base)
    _, replacements = central_entries(font.archive_of(patches))
    require(set(replacements) == set(patches) and set(patches) <= set(entries), 'Unexpected replacement members')
    local, central = bytearray(), bytearray()
    for name, original in entries.items():
        entry = replacements.get(name, original)
        record = bytearray(entry['central'])
        struct.pack_into('<I', record, 42, len(local))
        local.extend(entry['local'])
        central.extend(record)
    count = len(entries)
    result = bytes(local + central) + struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, count, count,
                                                 len(central), len(local), len(old['comment'])) + old['comment']
    _, after = central_entries(result)
    require(all(after[name]['local'] == entry['local'] for name, entry in entries.items() if name not in patches),
            'An unrelated compressed resource changed')
    with ZipFile(BytesIO(base)) as before, ZipFile(BytesIO(result)) as built:
        require(built.testzip() is None and built.namelist() == before.namelist(), 'ZIP membership or CRC failure')
        require({name for name in before.namelist() if before.read(name) != built.read(name)} == set(patches),
                'Unexpected changed resources')
        require(all(built.read(name) == data for name, data in patches.items()), 'A replacement resource differs')
    require(len(result) <= LIMIT, 'Pack exceeds 40 MiB')
    return result, count - len(patches)


def build():
    pin_bytes = CONFIG.read_bytes()
    pin = json.loads(pin_bytes)
    require(pin['projectId'] == 'c2090ff7-7646-43f5-a2c5-7398d88f4487' and pin['targetMinecraft'] == '26.3', 'Wrong project')
    if pin['sha256'] != BASE_SHA:
        require(BACKUP.exists() and pin['sha256'] == read(HERE / 'build-report.json')['sha256'], 'Current pin changed')
        pin_bytes = BACKUP.read_bytes()
        pin = json.loads(pin_bytes)
    require(pin['sha256'] == BASE_SHA and pin['publication']['commit'] == PARENT, 'Wrong publication parent')
    base_path = next((path for path in [ROOT / BASE_NAME, ROOT / 'sky-recoil' / BASE_NAME, SOURCE / BASE_NAME]
                      if path.exists() and sha(path.read_bytes()) == BASE_SHA), None)
    require(base_path is not None, 'Exact pinned base archive unavailable')
    preserve(HERE / 'base-pin.json', pin_bytes)
    old_glyph = (HERE / 'glyph-map-before.json').read_bytes() if (HERE / 'glyph-map-before.json').exists() else GLYPH.read_bytes()
    require(sha(old_glyph) == pin['mainMenuFont']['glyphMapSHA256'], 'Base glyph map changed')
    preserve(HERE / 'glyph-map-before.json', old_glyph)
    glyph = json.loads(old_glyph)
    glyph['widths']['card'].update({'paint': 66, 'advance': 67, 'step': 68})
    glyph['widths']['fiveCards'] = 338
    glyph['rows']['text'] = {'height': 8, 'ascent': 7}
    glyph['composition']['backgroundReset']['card'] = glyph['spaces']['-67']
    glyph['composition']['lastCellGap'] = 2
    glyph['composition']['wrap'] = 'Five full-size text cards paint 338 GUI pixels and retain their final two-pixel gutter for native height measurement. Finished row width is 340.'
    glyph['composition']['smallText'] = 'All visible menu text uses minecraft:default at its native 8-pixel height. The unused legacy small font is retained for archive compatibility.'
    glyph_bytes = font.encoded(glyph, compact=True)
    patches = {f'assets/star_program/textures/font/menu/card_{role}_{state}.png': font.strip_texture(66, colors, state)
               for role, colors in font.ROLES.items() for state in font.STATES}
    require(len(patches) == 15, 'Expected fifteen card atlases')
    data, retained = replace_archive(base_path.read_bytes(), patches)
    for name, content in patches.items():
        preserve(HERE / 'overrides' / name, content)
    report = {'version': 1, 'projectId': pin['projectId'], 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
              'revision': 'full-size-menu-text', 'baseCommit': PARENT, 'baseURL': pin['url'], 'baseSHA256': BASE_SHA,
              'basePack': BASE_NAME, 'packFile': PACK, 'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(),
              'size': len(data), 'sizeLimit': LIMIT, 'changedExistingFiles': sorted(patches), 'addedFiles': [], 'removedFiles': [],
              'unchangedEntries': retained, 'unrelatedResourcesByteIdentical': True, 'unrelatedCompressedRecordsByteIdentical': True,
              'fonts': glyph['fonts'], 'glyphMapFile': GLYPH_PATH, 'glyphMapSHA256': sha(glyph_bytes),
              'paintWidths': {'card': 66, 'panel': 220}, 'textFont': 'minecraft:default', 'textHeight': 8,
              'sourceBuilderFile': PREFIX + 'builder/menu-full-size-pack.py', 'sourceBuilderSHA256': sha(Path(__file__).read_bytes())}
    preserve(HERE / PACK, data)
    preserve(HERE / 'glyph-map.json', glyph_bytes)
    preserve(HERE / 'build-report.json', encoded(report))
    require(CONFIG.read_bytes() == (HERE / 'base-pin.json').read_bytes() or read(CONFIG)['sha256'] == report['sha256'], 'Pin changed during build')
    require(GLYPH.read_bytes() in [old_glyph, glyph_bytes], 'Preserve manually changed glyph map')
    GLYPH.write_bytes(glyph_bytes)
    return report


def payload():
    report = read(HERE / 'build-report.json')
    data = (HERE / PACK).read_bytes()
    glyph = (HERE / 'glyph-map.json').read_bytes()
    require(sha(data) == report['sha256'] and sha(glyph) == report['glyphMapSHA256'], 'Prepared artifacts changed')
    require(sha(Path(__file__).read_bytes()) == report['sourceBuilderSHA256'], 'Builder changed after preparation')
    files = {PACK: data, MANIFEST: encoded(report), GLYPH_PATH: glyph,
             PREFIX + 'builder/menu-full-size-pack.py': Path(__file__).read_bytes(),
             PREFIX + 'builder/main-menu-font-pack.py': Path(font.__file__).read_bytes()}
    files.update({PREFIX + 'source/' + path.relative_to(HERE / 'overrides').as_posix(): path.read_bytes()
                  for path in (HERE / 'overrides').rglob('*') if path.is_file()})
    return report, files


def commit():
    report, files = payload()
    before = (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', raw=True))
    require(before[0] == PARENT and git(SOURCE, 'remote', 'get-url', 'origin') == REMOTE, 'Wrong source checkout')
    if not (CHECKOUT / '.git').exists():
        require(not CHECKOUT.exists() or not any(CHECKOUT.iterdir()), 'Preserve publication directory')
        result = subprocess.run(['git', 'init', str(CHECKOUT)], capture_output=True)
        require(result.returncode == 0, 'Cannot initialize publication checkout')
        objects = [SOURCE / '.git/objects', *[Path(line) for line in (SOURCE / '.git/objects/info/alternates').read_text().splitlines() if line]]
        preserve(CHECKOUT / '.git/objects/info/alternates', ('\n'.join(dict.fromkeys(path.resolve().as_posix() for path in objects)) + '\n').encode())
        git(CHECKOUT, 'remote', 'add', 'origin', REMOTE)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for name in ['user.name', 'user.email']:
            git(CHECKOUT, 'config', name, git(SOURCE, 'config', '--get', name))
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    if git(CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(not git(CHECKOUT, 'status', '--porcelain=v1'), 'Preserve uncommitted publication edits')
        for name, content in files.items():
            preserve(CHECKOUT / name, content)
        git(CHECKOUT, 'add', '--', *files)
        git(CHECKOUT, 'commit', '-m', 'Widen menu job cards for full-size native text')
    revision = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(git(CHECKOUT, 'rev-list', '--count', PARENT + '..' + revision) == '1', 'Unexpected publication history')
    changed = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files) and not git(CHECKOUT, 'status', '--porcelain=v1'), 'Publication scope changed')
    for name, content in files.items():
        require(git(CHECKOUT, 'show', revision + ':' + name, raw=True) == content, 'Committed bytes differ: ' + name)
    require(before == (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', raw=True)), 'Source checkout changed')
    return report, files, revision


def publish():
    report, files, revision = commit()
    remote = git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH)
    require(not remote or remote.split()[0] == revision, 'Preserve differing remote branch')
    if not remote:
        git(CHECKOUT, 'push', '--set-upstream', 'origin', BRANCH + ':refs/heads/' + BRANCH)
    require(git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH).split()[0] == revision, 'Published ref differs')
    return {'status': 'pushed', 'commit': revision, 'branch': BRANCH, 'size': report['size']}


def verify():
    report, files, revision = commit()
    for name in [PACK, MANIFEST, GLYPH_PATH]:
        request = urllib.request.Request(f'{RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-menu-full-size'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(LIMIT + 1) == files[name], 'Immutable hosted bytes differ: ' + name)
    result = {'version': 1, 'status': 'published', 'commit': revision, 'branch': BRANCH,
              'url': f'{RAW}/{revision}/{PACK}', 'sha1': report['sha1'], 'sha256': report['sha256'], 'size': report['size'],
              'gitBlob': hashlib.sha1(f'blob {len(files[PACK])}\0'.encode() + files[PACK]).hexdigest(),
              'manifestFile': MANIFEST, 'manifestSha256': sha(files[MANIFEST]), 'glyphMapSHA256': sha(files[GLYPH_PATH]),
              'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'httpStatus': 200,
              'matchesLocalArtifact': True, 'remoteFilesVerified': [PACK, MANIFEST, GLYPH_PATH]}
    path = HERE / 'publication-verification.json'
    if path.exists():
        old = read(path)
        require(all(old.get(key) == value for key, value in result.items() if key != 'verifiedAt'), 'Preserve differing verification')
        return old
    preserve(path, encoded(result))
    return result


def pin():
    report, files, revision = commit()
    verified = read(HERE / 'publication-verification.json')
    require(verified['commit'] == revision and verified['sha256'] == report['sha256'] and verified['matchesLocalArtifact']
            and verified['manifestSha256'] == sha(files[MANIFEST]) and verified['glyphMapSHA256'] == sha(files[GLYPH_PATH]), 'Verify exact hosted artifacts first')
    before = CONFIG.read_bytes()
    config = json.loads(before)
    if config['sha256'] == report['sha256']:
        require(config['publication']['commit'] == revision, 'Inconsistent existing pin')
        return {'status': 'already-pinned', 'commit': revision}
    require(config['sha256'] == BASE_SHA and config['publication']['commit'] == PARENT
            and before == (HERE / 'base-pin.json').read_bytes(), 'Current pin changed')
    preserve(BACKUP, before)
    original = deepcopy(config)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    advanced = []
    for key, component in config.items():
        if isinstance(component, dict) and component.get('packCommit') == PARENT:
            component['packCommit'] = revision
            advanced.append(key)
    config['mainMenuFont'].update({'glyphMapFile': GLYPH_PATH, 'glyphMapSHA256': report['glyphMapSHA256'],
                                  'manifestFile': MANIFEST, 'manifestSha256': verified['manifestSha256']})
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    allowed = {'previousUrls', 'url', 'sha1', 'sha256', 'size', 'publication', 'mainMenuFont', *advanced}
    require(all(config[key] == value for key, value in original.items() if key not in allowed), 'Unrelated pin metadata changed')
    temporary = CONFIG.with_suffix('.menu-full-size-pinning.json')
    preserve(temporary, encoded(config))
    require(CONFIG.read_bytes() == before and GLYPH.read_bytes() == files[GLYPH_PATH], 'Concurrent resource edit preserved')
    temporary.replace(CONFIG)
    return {'status': 'pinned', 'commit': revision, 'url': verified['url'], 'size': report['size'], 'backup': str(BACKUP), 'advancedContainment': advanced}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'commit', 'publish', 'verify', 'pin'])
    args = parser.parse_args()
    result = globals()[args.action]()
    if args.action == 'commit':
        result = {'status': 'committed', 'commit': result[2], 'size': result[0]['size']}
    print(json.dumps(result, indent=2))
