"""Prepare, commit, publish, verify, or pin the additive ESRI resource pack.

Each action is explicit. prepare and commit are local. Nothing connects to
Minecraft, sends game code, scans the plot, or removes native templates.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from zipfile import ZipFile

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
HERE = ROOT / 'esri'
SOURCE = ROOT / 'diphone-tts-publication'
CHECKOUT = ROOT / 'esri-publication'
CONFIG = GAME / 'config/resource-pack.json'
PARENT = '6b018f52d6b6abe942e7c3692b84a52012e7d409'
BASE_SHA256 = 'cdf0eadf6a9c75d94ec87162e0db75ac171ede6eddab880017764f239922e7dc'
BASE_SHA1 = 'e43a1db6df63d57968a0616158d544f2edb70285'
BASE_SIZE = 28034996
BASE_NAME = 'sp_diphone-tts-mc26.3.zip'
LOCAL_PACK = HERE / 'star-program-esri-mc26.3.zip'
PACK = 'sp_esri-mc26.3.zip'
PREFIX = 'compatibility/esri/'
MANIFEST = PREFIX + 'publication-manifest.json'
BRANCH = 'codex/star-program-esri'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
PROJECT = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
LIMIT = 41943040
BACKUP = CONFIG.parent / 'backups/resource-pack-before-esri-cdf0eadf6a9c.json'


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


def git(repo, *args, raw=False, check=True):
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'safe.directory=' + repo.as_posix(), '-C', str(repo), *args], capture_output=True)
    if not check:
        return result
    require(result.returncode == 0, result.stderr.decode(errors='replace').strip() or 'Git operation failed')
    return result.stdout if raw else result.stdout.decode().strip()


def assert_parent(pin):
    require(pin.get('projectId') == PROJECT and pin.get('targetMinecraft') == '26.3'
            and pin.get('resourceFormat') == [97, 1], 'Wrong project or Minecraft format')
    require(pin.get('url') == f'{RAW}/{PARENT}/{BASE_NAME}' and pin.get('sha256') == BASE_SHA256
            and pin.get('sha1') == BASE_SHA1 and pin.get('size') == BASE_SIZE
            and pin.get('publication', {}).get('commit') == PARENT, 'Current pinned base pack changed')


def prepare():
    before = CONFIG.read_bytes()
    assert_parent(json.loads(before))
    require(before == (HERE / 'base-resource-pack.snapshot.json').read_bytes(), 'Preserve changed resource configuration')
    report = read(HERE / 'build-report.json')
    data = LOCAL_PACK.read_bytes()
    require(report.get('status') == 'prepared-local-not-published' and sha(data) == report['sha256']
            and hashlib.sha1(data).hexdigest() == report['sha1'] and len(data) == report['bytes'] <= LIMIT,
            'Prepared ESRI pack changed')
    require(report['base']['sha256'] == BASE_SHA256 and report['base']['configSha256'] == sha(before), 'Different prepared base')
    with ZipFile(ROOT / 'diphone-tts' / BASE_NAME) as base, ZipFile(BytesIO(data)) as merged:
        base_names, names = set(base.namelist()), set(merged.namelist())
        require(len(merged.namelist()) == len(names) and merged.testzip() is None and base_names <= names,
                'Invalid prepared ESRI ZIP')
        modified = {name for name in base_names if base.read(name) != merged.read(name)}
        require(modified == {'assets/minecraft/font/default.json', 'assets/shader_selector/shaders/post/shader.fsh'},
                'Unexpected existing pack modifications')
        for row in report['addedEntries']:
            require(row['file'] in names and sha(merged.read(row['file'])) == row['sha256'], 'Added ESRI asset changed')
        require(names - base_names == {row['file'] for row in report['addedEntries']}, 'Unexpected added ZIP entries')
    audio = (HERE / 'audio-manifest.json').read_bytes()
    publication = {
        'version': 1, 'projectId': PROJECT, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
        'baseCommit': PARENT, 'baseSHA256': BASE_SHA256, 'baseSize': BASE_SIZE,
        'baseConfigSHA256': sha(before), 'packFile': PACK, 'sha256': sha(data),
        'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data), 'sizeLimitBytes': LIMIT,
        'remainingBytes': LIMIT - len(data), 'preservation': report['preservation'],
        'audioManifestSHA256': sha(audio), 'builderSHA256': sha(Path(__file__).read_bytes()),
        'sourceBuildReportSHA256': sha((HERE / 'build-report.json').read_bytes()),
        'publicationPaths': [PACK, MANIFEST, PREFIX + 'audio-manifest.json', PREFIX + 'builder/esri-pack.py'],
        'runtimePinUnchanged': True,
    }
    for name, value in {
        'publication-base-pin.json': before,
        'publication-manifest.json': encoded(publication),
        'publication-builder.py': Path(__file__).read_bytes(),
        'publication-audio-manifest.json': audio,
    }.items():
        preserve(HERE / name, value)
    require(CONFIG.read_bytes() == before, 'Concurrent resource configuration edit preserved')
    return {'status': 'prepared', 'size': len(data), 'sha256': sha(data), 'remainingBytes': LIMIT - len(data)}


def payload():
    report = read(HERE / 'publication-manifest.json')
    data, builder = LOCAL_PACK.read_bytes(), (HERE / 'publication-builder.py').read_bytes()
    audio = (HERE / 'publication-audio-manifest.json').read_bytes()
    require(sha(data) == report['sha256'] and len(data) == report['size'] <= LIMIT
            and sha(builder) == report['builderSHA256'] and sha(audio) == report['audioManifestSHA256'],
            'Prepared publication artifacts changed')
    require(builder == Path(__file__).read_bytes(), 'Publication builder changed after preparation')
    files = {PACK: data, MANIFEST: encoded(report), PREFIX + 'audio-manifest.json': audio,
             PREFIX + 'builder/esri-pack.py': builder}
    require(set(files) == set(report['publicationPaths']), 'Publication scope changed')
    return report, files


def check_commit(files):
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE
            and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    revision = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(git(CHECKOUT, 'rev-parse', revision + '^') == PARENT, 'Unexpected publication parent')
    changed = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files), 'Unexpected publication paths')
    require(all(git(CHECKOUT, 'show', revision + ':' + name, raw=True) == value for name, value in files.items()),
            'Committed publication bytes differ')
    require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'',
            'Publication checkout changed')
    return revision


def commit():
    assert_parent(read(CONFIG))
    require(CONFIG.read_bytes() == (HERE / 'publication-base-pin.json').read_bytes(), 'Base resource configuration changed')
    report, files = payload()
    before = (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True))
    require(before == (PARENT, b''), 'Preserve changed source publication checkout')
    if not CHECKOUT.exists():
        CHECKOUT.mkdir(parents=True)
        subprocess.run(['git', 'init', '--quiet', str(CHECKOUT)], check=True, capture_output=True)
        alternates = CHECKOUT / '.git/objects/info/alternates'
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_bytes(((SOURCE / '.git/objects').resolve().as_posix() + '\n').encode())
        git(CHECKOUT, 'remote', 'add', 'origin', REMOTE)
        git(CHECKOUT, 'config', 'core.autocrlf', 'false')
        git(CHECKOUT, 'sparse-checkout', 'init', '--no-cone')
        git(CHECKOUT, 'sparse-checkout', 'set', '--no-cone', '/' + PACK, '/' + PREFIX)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for name in ['user.name', 'user.email']:
            value = git(SOURCE, 'config', '--get', name, check=False)
            if value.returncode == 0 and value.stdout.strip():
                git(CHECKOUT, 'config', name, value.stdout.decode().strip())
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE
            and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    if git(CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'',
                'Preserve changed publication checkout')
        require(git(CHECKOUT, 'ls-tree', '-r', '--name-only', PARENT, '--', PACK, PREFIX) == '',
                'Publication paths already exist')
        for name, value in files.items():
            preserve(CHECKOUT / name, value)
        git(CHECKOUT, 'add', '--', *files.keys())
        git(CHECKOUT, 'commit', '-m', 'Add ESRI laser audio, wormhole marker and impact frames for Minecraft 26.3')
    revision = check_commit(files)
    require((git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True)) == before,
            'Source publication checkout changed')
    return {'status': 'committed', 'commit': revision, 'branch': BRANCH, 'size': report['size']}


def context():
    report, files = payload()
    return report, files, check_commit(files)


def publish():
    assert_parent(read(CONFIG))
    report, _, revision = context()
    remote = git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH)
    if remote:
        require(remote.split()[0] == revision, 'Preserve differing remote branch')
    else:
        git(CHECKOUT, 'push', '--set-upstream', 'origin', BRANCH + ':refs/heads/' + BRANCH)
    require(git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH).split()[0] == revision, 'Remote publication differs')
    result = {'status': 'pushed', 'branch': BRANCH, 'commit': revision, 'size': report['size']}
    preserve(HERE / 'publication-push.json', encoded(result))
    return result


def verify():
    report, files, revision = context()
    for name, data in files.items():
        request = urllib.request.Request(f'{RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-ESRI'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(LIMIT + 1) == data,
                    'Immutable hosted artifact differs: ' + name)
    result = {'version': 1, 'status': 'published', 'commit': revision, 'branch': BRANCH,
              'url': f'{RAW}/{revision}/{PACK}', 'sha1': report['sha1'], 'sha256': report['sha256'], 'size': report['size'],
              'gitBlob': hashlib.sha1(f'blob {len(files[PACK])}\0'.encode() + files[PACK]).hexdigest(),
              'manifestFile': MANIFEST, 'manifestSha256': sha(files[MANIFEST]),
              'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'httpStatus': 200, 'matchesLocalArtifact': True, 'remoteFilesVerified': list(files)}
    destination = HERE / 'publication-verification.json'
    if destination.exists():
        previous = read(destination)
        require(all(previous.get(key) == value for key, value in result.items() if key != 'verifiedAt'), 'Preserve differing verification')
        return previous
    preserve(destination, encoded(result))
    return result


def pin():
    report, files, revision = context()
    verified = read(HERE / 'publication-verification.json')
    require(verified.get('status') == 'published' and verified.get('commit') == revision
            and verified.get('sha256') == report['sha256'] and verified.get('sha1') == report['sha1']
            and verified.get('size') == report['size'] and verified.get('matchesLocalArtifact') is True
            and verified.get('url') == f'{RAW}/{revision}/{PACK}'
            and verified.get('manifestSha256') == sha(files[MANIFEST]), 'Verify exact hosted artifacts before pinning')
    before = CONFIG.read_bytes()
    config = json.loads(before)
    if config.get('sha256') == report['sha256']:
        require(config['publication']['commit'] == revision and config.get('esri', {}).get('packCommit') == revision,
                'Inconsistent existing ESRI pin')
        return {'status': 'already-pinned', 'commit': revision}
    assert_parent(config)
    require(before == (HERE / 'publication-base-pin.json').read_bytes(), 'Preserve changed runtime resource configuration')
    preserve(BACKUP, before)
    original = deepcopy(config)
    advanced = []

    def advance(value, prefix=''):
        if isinstance(value, dict):
            for key, child in value.items():
                position = prefix + '.' + key if prefix else key
                if key == 'packCommit' and child == PARENT:
                    value[key] = revision
                    advanced.append(position)
                else:
                    advance(child, position)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                advance(child, f'{prefix}[{index}]')

    advance(config)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['esri'] = {'version': 1, 'packCommit': revision, 'namespace': 'star_program_esri',
                      'manifestFile': 'compatibility/esri/manifest.json',
                      'audioManifestFile': 'compatibility/esri/audio-manifest.json',
                      'wormholeFont': 'star_wormhole:portal', 'wormholeCodepoint': 'U+E770',
                      'impactControlChannel': 7, 'impactControlBytes': [0, 1, 2, 3],
                      'monoVorbis': True, 'sourcePitch': 1}
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    # Only resource pin fields, new ESRI metadata, and containing packCommit
    # values advance. Every unrelated field must retain its original value.
    restored = deepcopy(config)

    def restore(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'packCommit' and child == revision:
                    value[key] = PARENT
                else:
                    restore(child)
        elif isinstance(value, list):
            for child in value:
                restore(child)

    restore(restored)
    allowed = {'previousUrls', 'url', 'sha1', 'sha256', 'size', 'publication', 'esri'}
    require(all(restored[key] == value for key, value in original.items() if key not in allowed), 'Unrelated pin metadata changed')
    temporary = CONFIG.with_name(CONFIG.name + '.esri-pinning')
    require(not temporary.exists() and CONFIG.read_bytes() == before, 'Concurrent resource edit preserved')
    with temporary.open('xb') as target:
        target.write(encoded(config))
        target.flush()
        os.fsync(target.fileno())
    require(CONFIG.read_bytes() == before, 'Concurrent resource edit preserved')
    os.replace(temporary, CONFIG)
    result = {'status': 'pinned', 'commit': revision, 'url': verified['url'], 'size': report['size'],
              'sha1': report['sha1'], 'sha256': report['sha256'], 'backup': str(BACKUP), 'advancedContainment': advanced}
    preserve(HERE / 'pin-verification.json', encoded(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'commit', 'publish', 'verify', 'pin'])
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](), indent=2))
