"""Preserve the pinned MC26.3 pack and add the existing diphone speech phases.

prepare/commit are local. publish/verify/pin publish immutable resource bytes.
No Minecraft connection, game-code send, audio synthesis or plot scan is used.
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
import struct
import subprocess
import sys
import urllib.request
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
HERE = ROOT / 'diphone-tts'
SOURCE = ROOT / 'security-green-publication'
CHECKOUT = ROOT / 'diphone-tts-publication'
CONFIG = GAME / 'config/resource-pack.json'
PARENT = 'bfe6b687f06970acbba70c4b2719ce0c843fec81'
BASE_NAME = 'sp_security-green-mc26.3.zip'
BASE_SHA256 = '9cdc20e8d0c377ad4e007b204b4d9946a0deeadd512172c212b96fca81cf2e91'
BASE_SHA1 = 'ef36c94db547e9f498e889f1a24b69df1a6fa0aa'
BASE_SIZE = 16277182
PACK = 'sp_diphone-tts-mc26.3.zip'
PREFIX = 'compatibility/diphone-tts/'
MANIFEST = PREFIX + 'manifest.json'
BRANCH = 'codex/star-program-diphone-tts'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
PROJECT = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
LIMIT = 41943040
BACKUP = CONFIG.parent / 'backups/resource-pack-before-diphone-tts-9cdc20e8d0c3.json'


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
    require(pin.get('projectId') == PROJECT and pin.get('targetMinecraft') == '26.3' and pin.get('resourceFormat') == [97, 1], 'Wrong project or Minecraft format')
    require(pin.get('url') == f'{RAW}/{PARENT}/{BASE_NAME}' and pin.get('sha256') == BASE_SHA256
            and pin.get('sha1') == BASE_SHA1 and pin.get('size') == BASE_SIZE
            and pin.get('publication', {}).get('commit') == PARENT, 'Current pinned pack changed')


def central_entries(data):
    end = data.rfind(b'PK\x05\x06')
    require(end >= 0 and end + 22 <= len(data), 'Missing ZIP directory')
    disk, start_disk, local_count, total_count, size, offset, comment_size = struct.unpack_from('<4H2IH', data, end + 4)
    require(disk == start_disk == 0 and local_count == total_count and offset + size == end
            and end + 22 + comment_size == len(data), 'Unsupported ZIP archive')
    entries, cursor = {}, offset
    while cursor < end:
        require(data[cursor:cursor + 4] == b'PK\x01\x02', 'Invalid ZIP central record')
        name_size, extra_size, member_comment = struct.unpack_from('<3H', data, cursor + 28)
        length = 46 + name_size + extra_size + member_comment
        record = data[cursor:cursor + length]
        name = record[46:46 + name_size].decode('utf-8')
        require(name not in entries, 'Duplicate ZIP member')
        entries[name] = {'central': record, 'offset': struct.unpack_from('<I', record, 42)[0]}
        cursor += length
    require(len(entries) == total_count and cursor == end, 'Incorrect ZIP count')
    ordered = sorted(entries.values(), key=lambda entry: entry['offset'])
    for index, entry in enumerate(ordered):
        finish = ordered[index + 1]['offset'] if index + 1 < len(ordered) else offset
        entry['local'] = data[entry['offset']:finish]
    return data[end + 22:], entries


def overlay_archive(base, patches):
    comment, originals = central_entries(base)
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(patches.items()):
            info = ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value, compresslevel=9)
    _, replacements = central_entries(buffer.getvalue())
    local, central = bytearray(), bytearray()
    order = [*originals, *sorted(set(patches) - set(originals))]
    for name in order:
        entry = replacements[name] if name in replacements else originals[name]
        record = bytearray(entry['central'])
        struct.pack_into('<I', record, 42, len(local))
        local.extend(entry['local'])
        central.extend(record)
    count = len(order)
    result = bytes(local + central) + struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, count, count, len(central), len(local), len(comment)) + comment
    require(len(result) <= LIMIT, 'Resource pack exceeds 40 MiB')
    _, after = central_entries(result)
    require(all(after[name]['local'] == value['local'] for name, value in originals.items() if name not in patches), 'Unrelated compressed resource changed')
    with ZipFile(BytesIO(base)) as before, ZipFile(BytesIO(result)) as built:
        require(built.testzip() is None and set(built.namelist()) == set(before.namelist()) | set(patches), 'Resource membership or CRC failure')
        require(all(built.read(name) == value for name, value in patches.items()), 'Overlay resource differs')
        require(all(before.read(name) == built.read(name) for name in before.namelist() if name not in patches), 'Unrelated resource bytes changed')
    return result


def prepare():
    before = CONFIG.read_bytes()
    pin = json.loads(before)
    assert_parent(pin)
    base_path = ROOT / 'security-green' / BASE_NAME
    base = base_path.read_bytes()
    require(sha(base) == BASE_SHA256 and len(base) == BASE_SIZE and hashlib.sha1(base).hexdigest() == BASE_SHA1, 'Exact base archive differs')
    sys.path.insert(0, str(ROOT))
    from tts_overlay import diphone_patches
    patches, sounds, bank = diphone_patches(ROOT / 'tts/phoneme-v2')
    require(bank['diphoneUnits'] == 561 and bank['diphonePhaseClips'] == len(patches) == len(sounds) == 2805, 'Unexpected production speech inventory')
    sound_path = 'assets/star_program/sounds.json'
    with ZipFile(BytesIO(base)) as archive:
        original_names = set(archive.namelist())
        original_sounds = json.loads(archive.read(sound_path))
        require(not set(patches) & original_names and not set(sounds) & set(original_sounds), 'Existing resource would be overwritten by a speech phase')
    patches[sound_path] = encoded({**original_sounds, **sounds})
    data = overlay_archive(base, patches)
    production_manifest = (ROOT / 'tts/phoneme-v2/manifest.json').read_bytes()
    report = {'version': 1, 'projectId': PROJECT, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
              'revision': 'assembled-diphone-speech', 'baseCommit': PARENT, 'baseURL': pin['url'],
              'basePack': BASE_NAME, 'baseSHA256': BASE_SHA256, 'baseSize': BASE_SIZE, 'packFile': PACK,
              'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data), 'sizeLimitBytes': LIMIT,
              'remainingBytes': LIMIT - len(data), 'changedExistingFiles': [sound_path],
              'addedFiles': sorted(set(patches) - original_names), 'removedFiles': [],
              'unchangedEntries': len(original_names) - 1, 'originalSoundEvents': len(original_sounds),
              'mergedSoundEvents': len(original_sounds) + len(sounds), 'allExistingSoundRegistrationsPreserved': True,
              'unrelatedResourcesByteIdentical': True, 'unrelatedCompressedRecordsByteIdentical': True,
              'crc': True, 'voiceMode': 'diphones', **bank,
              'voice': read(ROOT / 'tts/phoneme-v2/manifest.json')['voice'],
              'productionManifestSHA256': sha(production_manifest), 'manifestFile': MANIFEST,
              'sourceBuilderSHA256': sha(Path(__file__).read_bytes()),
              'runtimePinUnchanged': True}
    files = {'base-pin.json': before, PACK: data, 'build-report.json': encoded(report),
             'speech-manifest.json': production_manifest, 'builder/diphone-tts-pack.py': Path(__file__).read_bytes()}
    for name, value in files.items():
        preserve(HERE / name, value)
    require(CONFIG.read_bytes() == before, 'Concurrent resource-pack edit preserved')
    return {key: report[key] for key in ['packFile', 'size', 'sha256', 'remainingBytes', 'diphoneUnits', 'diphonePhaseClips', 'unchangedEntries']}


def payload():
    report = read(HERE / 'build-report.json')
    data = (HERE / PACK).read_bytes()
    builder = (HERE / 'builder/diphone-tts-pack.py').read_bytes()
    production = (HERE / 'speech-manifest.json').read_bytes()
    require(sha(data) == report['sha256'] and len(data) == report['size'] <= LIMIT
            and sha(builder) == report['sourceBuilderSHA256'] and sha(production) == report['productionManifestSHA256'], 'Prepared artifacts changed')
    return report, {PACK: data, MANIFEST: encoded(report), PREFIX + 'speech-manifest.json': production,
                    PREFIX + 'builder/diphone-tts-pack.py': builder}


def check_commit(files):
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    revision = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(git(CHECKOUT, 'rev-parse', revision + '^') == PARENT, 'Unexpected publication parent')
    changed = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files), 'Unexpected publication paths')
    require(all(git(CHECKOUT, 'show', revision + ':' + name, raw=True) == value for name, value in files.items()), 'Committed publication bytes differ')
    require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'', 'Publication checkout changed')
    return revision


def commit():
    assert_parent(read(CONFIG))
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
        # Preserve authored manifest bytes, including their original line endings.
        git(CHECKOUT, 'config', 'core.autocrlf', 'false')
        git(CHECKOUT, 'sparse-checkout', 'init', '--no-cone')
        git(CHECKOUT, 'sparse-checkout', 'set', '--no-cone', '/' + PACK, '/' + PREFIX)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for name in ['user.name', 'user.email']:
            value = git(SOURCE, 'config', '--get', name, check=False)
            if value.returncode == 0 and value.stdout.strip():
                git(CHECKOUT, 'config', name, value.stdout.decode().strip())
    require(git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE and git(CHECKOUT, 'branch', '--show-current') == BRANCH, 'Wrong publication checkout')
    if git(CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(git(CHECKOUT, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'', 'Preserve changed publication checkout')
        require(git(CHECKOUT, 'ls-tree', '-r', '--name-only', PARENT, '--', PACK, PREFIX) == '', 'Publication paths already exist')
        for name, value in files.items():
            preserve(CHECKOUT / name, value)
        git(CHECKOUT, 'add', '--', *files.keys())
        git(CHECKOUT, 'commit', '-m', 'Add compact assembled diphone TTS audio for Minecraft 26.3')
    revision = check_commit(files)
    require((git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True)) == before, 'Source publication checkout changed')
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
    for name in files:
        request = urllib.request.Request(f'{RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-diphone-TTS'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(LIMIT + 1) == files[name], 'Immutable hosted artifact differs: ' + name)
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
            and verified.get('sha256') == report['sha256'] and verified.get('matchesLocalArtifact') is True
            and verified.get('manifestSha256') == sha(files[MANIFEST]), 'Verify exact hosted artifacts before pinning')
    before = CONFIG.read_bytes()
    config = json.loads(before)
    if config.get('sha256') == report['sha256']:
        require(config['publication']['commit'] == revision, 'Inconsistent existing diphone pin')
        return {'status': 'already-pinned', 'commit': revision}
    assert_parent(config)
    require(before == (HERE / 'base-pin.json').read_bytes(), 'Preserve changed runtime resource configuration')
    preserve(BACKUP, before)
    original = deepcopy(config)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    advanced = []
    for key, component in config.items():
        if isinstance(component, dict) and component.get('packCommit') == PARENT:
            component['packCommit'] = revision
            advanced.append(key)
    config['tts'] = {'voiceMode': 'diphones', 'assembledSpeech': True, 'namespace': 'star_program',
                     'voice': report['voice'], 'diphoneUnits': report['diphoneUnits'],
                     'diphonePhaseClips': report['diphonePhaseClips'], 'phaseStepMs': 10,
                     'audioBytes': report['transitionAudioBytes'], 'wholeWordRecordings': 0,
                     'monoVorbis': True, 'deterministicEvents': True,
                     'productionManifestFile': PREFIX + 'speech-manifest.json',
                     'productionManifestSHA256': report['productionManifestSHA256'],
                     'existingAnnouncementsPreserved': True}
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    allowed = {'previousUrls', 'url', 'sha1', 'sha256', 'size', 'publication', 'tts', *advanced}
    require(all(config[key] == value for key, value in original.items() if key not in allowed), 'Unrelated pin metadata changed')
    temporary = CONFIG.with_name(CONFIG.name + '.diphone-tts-pinning')
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
