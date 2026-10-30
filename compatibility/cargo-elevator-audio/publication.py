"""Publish and pin the reviewed additive cargo lift audio pack.

Uses the established isolated STAR PROGRAM resource publication transport.
Only the exact reviewed files can enter its new branch. The active pin changes
only after the immutable remote archive matches the prepared local ZIP.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
AUDIO = ROOT / 'cargo-elevator-audio'
PREFIX = 'compatibility/cargo-elevator-audio/'
PARENT = '63cea85726f65e417d80e695735b86e205f6f111'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = module('cargo_sound_builder', GAME / 'tools/cargo-elevator-audio.py')
previous = module('cargo_previous_publication', GAME / 'tools/keycard-publication.py')
c = previous.c
c.SOURCE = ROOT / 'mc26.3-runtime-fix-publication'
c.CHECKOUT = ROOT / 'cargo-elevator-direct-drive-publication'
c.BASE, c.PACK, c.REPORT = builder.BASE, builder.PACK, builder.REPORT
c.UPLOAD = AUDIO / 'upload-report-direct-drive.json'
c.PARENT, c.PARENT_SHA256 = PARENT, builder.BASE_SHA
c.BRANCH = 'codex/star-program-cargo-elevator-direct-drive'
c.ensure_checkout = previous.ensure_checkout


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepared():
    verified = builder.verify()
    report = c.read_json(c.REPORT)
    require(report == verified, 'Cargo pack report differs from verified bytes')
    manifest = c.read_json(AUDIO / 'manifest.json')
    require(report['cargoAudio'] == manifest and manifest['namespace'] == 'star_program_cargo'
            and set(manifest['sounds']) == {'motor.start', 'motor.run', 'motor.brake', 'departure.cue', 'arrival.cue', 'door.opening', 'door.closing'},
            'Expected the three motor sounds, two user-selected cues and two door voice lines')
    require(c.digest(builder.SOURCE.read_bytes()) == builder.SOURCE_SHA,
            'Selected motor source changed')
    additions = builder.overlay_files(manifest)
    expected = {'assets/star_program_cargo/sounds.json',
                'assets/star_program_cargo/sounds/motor/start.ogg',
                'assets/star_program_cargo/sounds/motor/run.ogg',
                'assets/star_program_cargo/sounds/motor/brake.ogg',
                'assets/star_program_cargo/sounds/departure/cue.ogg',
                'assets/star_program_cargo/sounds/arrival/cue.ogg',
                'assets/star_program_cargo/sounds/door/opening.ogg',
                'assets/star_program_cargo/sounds/door/closing.ogg',
                PREFIX + 'manifest.json', 'credits/cargo-elevator-audio.txt'}
    require(set(additions) == expected, 'Unexpected cargo archive additions')
    with ZipFile(c.BASE) as old, ZipFile(c.PACK) as new:
        require(old.testzip() is None and new.testzip() is None, 'ZIP CRC failure')
        require(c.digest(c.BASE.read_bytes()) == builder.BASE_SHA, 'Pinned base archive changed')
        for name in new.namelist():
            if name.endswith(('.json', '.mcmeta')):
                json.loads(new.read(name))
    payload = {c.PACK.name: c.PACK.read_bytes(),
               PREFIX + 'pack-build-report.json': c.REPORT.read_bytes(),
               PREFIX + 'manifest.json': c.json_bytes(manifest),
               PREFIX + 'build.py': (GAME / 'tools/cargo-elevator-audio.py').read_bytes(),
               PREFIX + 'publication.py': Path(__file__).read_bytes(),
               }
    for source in [manifest['source'], manifest['contactorSource'],
                   *manifest['cueSources'].values(), *manifest['voiceSources'].values()]:
        for key in ['file', 'evidenceFile']:
            path = source[key]
            require(not path.endswith('.html'), 'Never publish raw third-party webpage HTML')
            payload[PREFIX + path] = (AUDIO / path).read_bytes()
    # Preserve source helpers too, without modifying any earlier copy.
    payload[PREFIX + 'helpers/audio_io.py'] = (GAME / 'resource-pack/lab-audio/audio_io.py').read_bytes()
    payload[PREFIX + 'helpers/audio_processing.py'] = (GAME / 'resource-pack/turbines/build_audio.py').read_bytes()
    for name in ['render_announcements.py', 'audio_helpers.py']:
        payload[PREFIX + 'helpers/' + name] = (GAME / 'resource-pack/tts/announcements' / name).read_bytes()
    payload.update({PREFIX + name: value for name, value in additions.items()
                    if name != PREFIX + 'manifest.json'})
    for name in payload:
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
                'Unsafe publication path')
    return {**report, 'gitBlob': c.blob_hash(c.PACK.read_bytes())}, manifest, payload


c.prepared = prepared


def commit_local():
    c.assert_parent(c.read_json(c.CONFIG))
    report, _, payload = prepared()
    c.check_checkout()
    if c.git(c.CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(set(c.changes()) == {('A ', name) for name in payload}, 'Unexpected staged files')
        for name, content in payload.items():
            require(c.git(c.CHECKOUT, 'show', ':' + name, raw=True) == content,
                    'Staged cargo payload changed: ' + name)
        c.git(c.CHECKOUT, 'commit', '-m', 'Add hard switching cargo hoist starts and stops with approved travel')
    return {'status': 'committed', 'commit': c.check_commit(payload), 'branch': c.BRANCH,
            'sha256': report['sha256'], 'published': False}


def pin(commit=None):
    report, manifest, commit, url = c.publication_context(commit)
    verified = c.read_json(c.UPLOAD)
    expected = {'status': 'published', 'commit': commit, 'branch': c.BRANCH, 'url': url,
                'httpStatus': 200, 'sha1': report['sha1'], 'sha256': report['sha256'],
                'size': report['size'], 'gitBlob': report['gitBlob'], 'matchesLocalArtifact': True}
    require(all(verified.get(key) == value for key, value in expected.items())
            and verified.get('verifiedAt'), 'Verify immutable cargo pack before pinning')
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    metadata = {**manifest, 'manifestFile': PREFIX + 'manifest.json', 'packCommit': commit}
    if config.get('url') == url:
        require(config['sha256'] == report['sha256'] and config.get('cargoElevatorAudio') == metadata,
                'Inconsistent existing cargo pin')
        return {'status': 'already-pinned', 'url': url}
    c.assert_parent(config)
    require(config.get('projectId') == 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
            and config.get('targetMinecraft') == '26.3', 'Unexpected project or version')
    backup = c.CONFIG.parent / 'backups/resource-pack-before-cargo-elevator-962a4e3191d4.json'
    c.preserve(backup, before)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['cargoElevatorAudio'] = metadata
    config['publication'].update({key: verified[key]
                                  for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    changed = {'url', 'sha1', 'sha256', 'size', 'previousUrls', 'cargoElevatorAudio', 'publication'}
    require(all(config[key] == value for key, value in json.loads(before).items() if key not in changed),
            'Unrelated resource configuration changed')
    temporary = c.CONFIG.with_suffix('.cargo-elevator-pinning.json')
    c.preserve(temporary, c.json_bytes(config))
    require(c.CONFIG.read_bytes() == before, 'Resource pin changed while preparing cargo pin')
    temporary.replace(c.CONFIG)
    return {'status': 'pinned', 'commit': commit, 'url': url, 'sha256': report['sha256'],
            'size': report['size'], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    parser.add_argument('commit', nargs='?')
    args = parser.parse_args()
    if args.commit and (args.action not in ['verify', 'pin'] or not re.fullmatch('[a-f0-9]{40}', args.commit)):
        parser.error('Only verify and pin accept an immutable commit')
    actions = {'prepared': lambda: prepared()[1], 'stage': c.stage, 'commit': commit_local,
               'publish': c.publish, 'verify': lambda: c.verify(args.commit), 'pin': lambda: pin(args.commit)}
    print(json.dumps(actions[args.action](), indent=2))
