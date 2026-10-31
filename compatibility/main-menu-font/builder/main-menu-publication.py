"""Guarded publication of the isolated additive STAR PROGRAM menu font pack.

Each command is separate. prepared, stage and commit are local. publish pushes
only the dedicated branch. verify checks immutable hosted bytes. pin requires
that successful verification and atomically updates the resource configuration.
The existing forklift checkout and every inherited pack entry remain intact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import urllib.request


GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
MENU = ROOT / 'main-menu'
CONFIG = GAME / 'config/resource-pack.json'
SOURCE = ROOT / 'forklift-smooth-audio-publication'
CHECKOUT = ROOT / 'main-menu-publication'
PREFIX = 'compatibility/main-menu-font/'
MANIFEST_PATH = PREFIX + 'manifest.json'
GLYPH_PATH = PREFIX + 'glyph-map.json'
PACK = MENU / 'sp_main-menu-font-mc26.3.zip'
BASE_NAME = 'sp_forklift-smooth-audio-mc26.3.zip'
PARENT = 'd61073f6eabdaddc366d57ec516ab2e691619c6f'
BASE_SHA = '8a51e54b0879fec375ddc5040144ea3ae8b74474524998fb8827cd6df6c42c4c'
BRANCH = 'codex/star-program-main-menu'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW_BASE = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
PROJECT = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
BACKUP = CONFIG.parent / 'backups/resource-pack-before-main-menu-8a51e54b0879.json'
UPLOAD = MENU / 'publication-verification.json'
LIMIT = 41943040


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


font = module('star_program_menu_font_builder', Path(__file__).with_name('main-menu-font-pack.py'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing existing file: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as target:
        target.write(data)


def git(repo, *args, raw=False, check=True):
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'safe.directory=' + repo.as_posix(),
                             '-C', str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not check:
        return result
    require(result.returncode == 0, result.stderr.decode(errors='replace').strip() or 'Git command failed')
    return result.stdout if raw else result.stdout.decode().strip()


def source_state():
    return (git(SOURCE, 'rev-parse', 'HEAD'),
            git(SOURCE, 'symbolic-ref', '-q', '--short', 'HEAD', raw=True, check=False).stdout,
            git(SOURCE, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True))


def assert_parent(config):
    require(config.get('projectId') == PROJECT and config.get('targetMinecraft') == '26.3'
            and config.get('resourceFormat') == [97, 1], 'Wrong resource project or Minecraft format')
    require(config.get('sha256') == BASE_SHA and config.get('publication', {}).get('commit') == PARENT
            and config.get('url') == f'{RAW_BASE}/{PARENT}/{BASE_NAME}',
            'Runtime pack changed. Rebase and review the menu overlay against its current pin.')


def base_config():
    current = read(CONFIG)
    if current.get('sha256') == BASE_SHA:
        assert_parent(current)
        return current
    # After a successful pin the immutable backup retains the exact base
    # publication provenance, keeping prepared/verify/pin safely repeatable.
    require(BACKUP.exists() and UPLOAD.exists(), 'Current pin differs and no matching menu publication backup exists')
    verified = read(UPLOAD)
    require(current.get('sha256') == verified.get('sha256')
            and current.get('publication', {}).get('commit') == verified.get('commit')
            and current.get('publication', {}).get('branch') == BRANCH,
            'Current resource pin is unrelated to this menu publication')
    original = read(BACKUP)
    assert_parent(original)
    return original


def base_bytes():
    for path in [ROOT / BASE_NAME, SOURCE / BASE_NAME]:
        if path.exists() and sha(path.read_bytes()) == BASE_SHA:
            return path.read_bytes()
    raise ValueError('The exact pinned forklift-smooth-audio base archive is unavailable locally')


def prepared_data():
    config = base_config()
    build_report, glyph_bytes = read(MENU / 'build-report.json'), (MENU / 'glyph-map.json').read_bytes()
    sources, glyphs, ascii_sha, _ = font.make_sources()
    require(glyph_bytes == font.encoded(glyphs, compact=True), 'Menu glyph map differs from the reviewed builder')
    for name, content in sources.items():
        require((MENU / name).read_bytes() == content, 'Generated menu asset changed: ' + name)
    overlay = font.archive_of(sources)
    require((MENU / 'menu-font-overlay.zip').read_bytes() == overlay, 'Generated menu font overlay changed')
    data, base = PACK.read_bytes(), base_bytes()
    expected, retained = font.additive_archive(base, overlay, sources)
    require(data == expected, 'Complete menu pack is not the exact additive archive over the pinned base')
    details = build_report['merged']
    require(build_report['mode'] == 'build' and details['written'] is True
            and details['path'] == PACK.name and details['sha256'] == sha(data)
            and details['sha1'] == hashlib.sha1(data).hexdigest() and details['size'] == len(data)
            and build_report['baseSHA256'] == BASE_SHA and build_report['retainedEntries'] == retained
            and build_report['vanillaASCIITextureSHA256'] == ascii_sha
            and build_report['designSHA256'] == sha(font.PLAN.read_bytes())
            and build_report['overlay']['sha256'] == sha(overlay)
            and all(value is True for value in build_report['checks'].values()), 'Menu build evidence changed')
    manifest = {
        'version': 1, 'projectId': PROJECT, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
        'revision': 'native-main-menu-colored-font-panels', 'baseCommit': PARENT,
        'basePack': BASE_NAME, 'baseURL': config['url'], 'baseSHA256': BASE_SHA,
        'basePublication': deepcopy(config['publication']), 'packFile': PACK.name,
        'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data), 'gitBlob': blob(data),
        'fonts': glyphs['fonts'], 'glyphMapFile': GLYPH_PATH, 'glyphMapSHA256': sha(glyph_bytes),
        'glyphCount': 90, 'spaceGlyphCount': 513, 'bitmapCellLimit': 256,
        'paintWidths': {'card': 56, 'panel': 220}, 'smallTextHeight': 6,
        'noImportedIconAssets': True, 'vanillaSpriteObjects': glyphs['sprites'],
        'sourceBuilderFile': PREFIX + 'builder/main-menu-font-pack.py',
        'sourceBuilderSHA256': sha(Path(font.__file__).read_bytes()),
        'publicationRecipeSHA256': sha(Path(__file__).read_bytes()),
        'designSHA256': build_report['designSHA256'],
        'addedFiles': sorted(sources), 'changedExistingFiles': [], 'removedFiles': [],
        'existingEntryCount': retained, 'allExistingEntriesByteIdentical': True,
        'allExistingCompressedRecordsByteIdentical': True, 'allExistingCentralRecordsByteIdentical': True,
        'assets': [{'file': name, 'sha256': sha(value), 'size': len(value)} for name, value in sorted(sources.items())],
    }
    payload = {PACK.name: data, GLYPH_PATH: glyph_bytes, MANIFEST_PATH: encoded(manifest),
               PREFIX + 'pack-build-report.json': (MENU / 'build-report.json').read_bytes(),
               PREFIX + 'builder/main-menu-font-pack.py': Path(font.__file__).read_bytes(),
               PREFIX + 'builder/main-menu-publication.py': Path(__file__).read_bytes(),
               PREFIX + 'README.md': (MENU / 'README.md').read_bytes(),
               **{PREFIX + 'source/' + name: value for name, value in sources.items()}}
    require(len(payload) == 39 and len(data) <= LIMIT, 'Unexpected publication payload or ZIP size')
    require(all(name == PACK.name or name.startswith(PREFIX) for name in payload), 'Unexpected publication path')
    return manifest, payload


def prepared():
    manifest, payload = prepared_data()
    return {'status': 'prepared', 'sha256': manifest['sha256'], 'sha1': manifest['sha1'],
            'gitBlob': manifest['gitBlob'], 'size': manifest['size'], 'files': len(payload),
            'manifestSha256': sha(payload[MANIFEST_PATH]), 'runtimePinUnchanged': True}


def check_checkout():
    require(Path(git(CHECKOUT, 'rev-parse', '--show-toplevel')).resolve() == CHECKOUT.resolve(),
            'Publication directory is not an isolated checkout')
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE
            and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Unexpected publication branch or remote')
    git(CHECKOUT, 'merge-base', '--is-ancestor', PARENT, 'HEAD')


def ensure_checkout():
    before = source_state()
    require(git(SOURCE, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected source repository remote')
    require(git(SOURCE, 'rev-parse', PARENT + '^{commit}') == PARENT, 'Pinned base commit is missing locally')
    require(sha(git(SOURCE, 'show', PARENT + ':' + BASE_NAME, raw=True)) == BASE_SHA,
            'Pinned source commit contains a different base pack')
    require(git(SOURCE, 'ls-tree', '-r', '--name-only', PARENT, '--', PREFIX, PACK.name) == '',
            'Preserve existing base publication paths')
    if not (CHECKOUT / '.git').exists():
        require(not CHECKOUT.exists() or not any(CHECKOUT.iterdir()), 'Preserve the existing publication directory')
        objects = SOURCE / '.git/objects'
        require(objects.is_dir(), 'Expected the source repository local object database')
        result = subprocess.run(['git', 'init', str(CHECKOUT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        require(result.returncode == 0, result.stderr.decode(errors='replace'))
        preserve(CHECKOUT / '.git/objects/info/alternates', (objects.resolve().as_posix() + '\n').encode())
        git(CHECKOUT, 'remote', 'add', 'origin', REMOTE)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for key in ['user.name', 'user.email']:
            inherited = git(SOURCE, 'config', '--get', key, check=False)
            if inherited.returncode == 0:
                git(CHECKOUT, 'config', key, inherited.stdout.decode().strip())
    check_checkout()
    require(source_state() == before, 'The original forklift publication checkout changed during preparation')


def changes():
    data = git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True)
    result = []
    for record in data.split(b'\0'):
        if record:
            status, name = record[:2].decode(), record[3:].decode()
            require('R' not in status and 'C' not in status, 'Preserve renamed/copied publication files')
            result.append((status, name))
    return result


def check_commit(payload):
    check_checkout()
    commit_id = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(re.fullmatch('[a-f0-9]{40}', commit_id) is not None, 'An immutable full commit is required')
    require(git(CHECKOUT, 'rev-list', '--count', PARENT + '..' + commit_id) == '1',
            'Expected exactly one reviewed commit on the pinned base')
    paths = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, commit_id, raw=True).decode().rstrip('\0').split('\0')
    require(set(paths) == set(payload), 'Unexpected publication commit paths')
    for name, value in payload.items():
        require(git(CHECKOUT, 'show', commit_id + ':' + name, raw=True) == value,
                'Committed publication bytes differ: ' + name)
    require(not changes(), 'Preserve uncommitted publication checkout changes')
    return commit_id


def stage():
    assert_parent(read(CONFIG))
    manifest, payload = prepared_data()
    ensure_checkout()
    if git(CHECKOUT, 'rev-parse', 'HEAD') != PARENT:
        return {'status': 'already-committed', 'commit': check_commit(payload), 'branch': BRANCH,
                'sha256': manifest['sha256'], 'size': manifest['size'], 'published': False}
    require(all(name in payload and status in ['??', 'A '] for status, name in changes()),
            'Preserve unrelated or modified publication checkout files')
    for name, value in payload.items():
        preserve(CHECKOUT / name, value)
    git(CHECKOUT, 'add', '--', *payload)
    require(set(changes()) == {('A ', name) for name in payload}, 'Stage exactly the additive menu payload')
    for name, value in payload.items():
        require(git(CHECKOUT, 'show', ':' + name, raw=True) == value, 'Staged bytes differ: ' + name)
    return {'status': 'staged', 'branch': BRANCH, 'checkout': str(CHECKOUT), 'files': len(payload),
            'sha256': manifest['sha256'], 'size': manifest['size'], 'published': False}


def commit():
    result = stage()
    if result['status'] != 'already-committed':
        git(CHECKOUT, 'commit', '-m', 'Add isolated colored font panels for native STAR PROGRAM menus')
    manifest, payload = prepared_data()
    return {'status': 'committed', 'commit': check_commit(payload), 'branch': BRANCH,
            'sha256': manifest['sha256'], 'sha1': manifest['sha1'], 'gitBlob': manifest['gitBlob'],
            'size': manifest['size'], 'published': False}


def context():
    manifest, payload = prepared_data()
    commit_id = check_commit(payload)
    return manifest, payload, commit_id, f'{RAW_BASE}/{commit_id}/{PACK.name}'


def publish():
    assert_parent(read(CONFIG))
    manifest, _, commit_id, url = context()
    ref = 'refs/heads/' + BRANCH
    remote = git(CHECKOUT, 'ls-remote', '--exit-code', '--heads', 'origin', ref, check=False)
    require(remote.returncode in (0, 2), remote.stderr.decode(errors='replace') or 'Cannot inspect remote branch')
    if remote.returncode == 0:
        require(remote.stdout.decode().split()[0] == commit_id, 'Preserve the different existing remote menu branch')
    else:
        git(CHECKOUT, 'push', '--set-upstream', 'origin', BRANCH + ':' + ref)
    require(git(CHECKOUT, 'ls-remote', '--exit-code', '--heads', 'origin', ref).split()[0] == commit_id,
            'Published branch points to a different commit')
    result = {'status': 'pushed', 'branch': BRANCH, 'commit': commit_id, 'url': url,
              'sha256': manifest['sha256'], 'size': manifest['size'], 'runtimePinUnchanged': True}
    preserve(MENU / 'publication-push.json', encoded(result))
    return result


def hosted_bytes(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'STAR-Program-main-menu-verification'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data, status = response.read(limit + 1), response.status
    require(status == 200 and len(data) <= limit, 'Immutable hosted resource failed its HTTP or length check')
    return data


def verify():
    manifest, payload, commit_id, url = context()
    require(hosted_bytes(url, LIMIT) == payload[PACK.name], 'Immutable hosted menu ZIP differs from local bytes')
    for path in [MANIFEST_PATH, GLYPH_PATH]:
        require(hosted_bytes(f'{RAW_BASE}/{commit_id}/{path}', 262144) == payload[path],
                'Immutable hosted menu metadata differs: ' + path)
    result = {'version': 1, 'status': 'published', 'commit': commit_id, 'branch': BRANCH, 'url': url,
              'httpStatus': 200, 'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'sha1': manifest['sha1'], 'sha256': manifest['sha256'], 'size': manifest['size'],
              'gitBlob': manifest['gitBlob'], 'manifestFile': MANIFEST_PATH,
              'manifestSha256': sha(payload[MANIFEST_PATH]), 'glyphMapSHA256': sha(payload[GLYPH_PATH]),
              'matchesLocalArtifact': True, 'allExistingAssetsByteIdentical': True,
              'remoteFilesVerified': [PACK.name, MANIFEST_PATH, GLYPH_PATH]}
    if UPLOAD.exists():
        old = read(UPLOAD)
        require(all(old.get(key) == value for key, value in result.items() if key != 'verifiedAt'),
                'Preserve differing existing immutable verification report')
        return old
    preserve(UPLOAD, encoded(result))
    return result


def pin():
    manifest, payload, commit_id, url = context()
    require(UPLOAD.exists(), 'Run immutable hosted verification before pinning')
    verified = read(UPLOAD)
    expected = {'status': 'published', 'commit': commit_id, 'branch': BRANCH, 'url': url, 'httpStatus': 200,
                'sha1': manifest['sha1'], 'sha256': manifest['sha256'], 'size': manifest['size'],
                'gitBlob': manifest['gitBlob'], 'manifestFile': MANIFEST_PATH,
                'manifestSha256': sha(payload[MANIFEST_PATH]), 'glyphMapSHA256': sha(payload[GLYPH_PATH]),
                'matchesLocalArtifact': True, 'allExistingAssetsByteIdentical': True,
                'remoteFilesVerified': [PACK.name, MANIFEST_PATH, GLYPH_PATH]}
    require(all(verified.get(key) == value for key, value in expected.items()) and verified.get('verifiedAt'),
            'Successful immutable-host verification does not match this exact artifact')
    before = CONFIG.read_bytes()
    current = json.loads(before)
    metadata = {'version': 1, 'fonts': manifest['fonts'], 'glyphMapFile': GLYPH_PATH,
                'glyphMapSHA256': manifest['glyphMapSHA256'], 'manifestFile': MANIFEST_PATH,
                'manifestSha256': sha(payload[MANIFEST_PATH]), 'packCommit': commit_id}
    if current.get('url') == url and current.get('sha256') == manifest['sha256']:
        require(current.get('mainMenuFont') == metadata and current['publication']['commit'] == commit_id
                and current['publication']['manifestFile'] == MANIFEST_PATH
                and current['publication']['manifestSha256'] == sha(payload[MANIFEST_PATH]),
                'Existing menu pin has inconsistent metadata')
        return {'status': 'already-pinned', 'commit': commit_id, 'url': url,
                'sha256': manifest['sha256'], 'configurationRewritten': False}
    assert_parent(current)
    original = deepcopy(current)
    require(current['publication'] == manifest['basePublication'], 'Inherited publication provenance changed')
    preserve(BACKUP, before)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    advanced = []
    for name, component in current.items():
        if isinstance(component, dict) and component.get('packCommit') == PARENT:
            component['packCommit'] = commit_id
            advanced.append(name)
    current['mainMenuFont'] = metadata
    current['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    current['publication'].update({'verifiedBlob': verified['gitBlob'], 'manifestFile': MANIFEST_PATH,
                                   'manifestSha256': sha(payload[MANIFEST_PATH])})
    allowed = {'url', 'sha1', 'sha256', 'size', 'previousUrls', 'publication', 'mainMenuFont', *advanced}
    require(all(current.get(key) == value for key, value in original.items() if key not in allowed),
            'Unrelated resource metadata changed')
    for name in advanced:
        require({key: value for key, value in current[name].items() if key != 'packCommit'}
                == {key: value for key, value in original[name].items() if key != 'packCommit'},
                'Inherited component metadata changed beyond its containment commit: ' + name)
    temporary = CONFIG.with_suffix('.main-menu-pinning.json')
    preserve(temporary, encoded(current))
    require(CONFIG.read_bytes() == before, 'Runtime resource configuration changed before atomic pin')
    temporary.replace(CONFIG)
    return {'status': 'pinned', 'commit': commit_id, 'url': url, 'sha256': manifest['sha256'],
            'sha1': manifest['sha1'], 'size': manifest['size'], 'backup': str(BACKUP),
            'advancedComponentContainment': advanced, 'configurationRewritten': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](), indent=2))
