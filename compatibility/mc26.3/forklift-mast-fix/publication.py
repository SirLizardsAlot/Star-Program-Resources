"""Publish the reviewed forklift mast clearance fix over the current full pack.

Only the existing seventeen forklift paths may be overlaid, with four reviewed
lift-audio additions. Pallet assets and all old audio remain unchanged.
"""
import argparse
from copy import copy, deepcopy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
FORKLIFT = GAME / 'models/forklift'
PALLET = GAME / 'models/wooden-pallet'
PREFIX = 'compatibility/mc26.3/forklift-mast-fix/'
MANIFEST_PATH = PREFIX + 'manifest.json'
PARENT = 'e187134f3b8d9ee0fab712e9a12cb5b21b4c89f9'
BASE_SHA = '4506def8e989e865194eeae57badfb9f2d116ea0b156465ce33d99d76eb4e1fe'
PROJECT_ID = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


previous = module('forklift_mast_previous_publication', GAME / 'tools/forklift-pack-publication.py')
audio = module('forklift_mast_audio', GAME / 'tools/forklift-audio.py')
c = previous.c
c.SOURCE = ROOT / 'forklift-pallet-publication'
c.CHECKOUT = ROOT / 'forklift-mast-fix-publication'
c.BASE = ROOT / 'sp_forklift-pallet-mc26.3.zip'
c.PACK = ROOT / 'sp_forklift-mast-fix-mc26.3.zip'
c.REPORT = c.PACK.with_suffix('.report.json')
c.UPLOAD = ROOT / 'upload-report-forklift-mast-fix.json'
c.PARENT, c.PARENT_SHA256 = PARENT, BASE_SHA
c.BRANCH = 'codex/star-program-forklift-mast-fix'
IDS = previous.FORKLIFT_IDS
ASSETS = {f'assets/star_program/{folder}/{name}.json'
          for folder in ['items', 'models/item'] for name in IDS}
ASSETS.add('assets/star_program/textures/item/forklift.png')
PALLET_ASSETS = ['assets/star_program/items/wooden_pallet.json',
                'assets/star_program/models/item/wooden_pallet.json',
                'assets/star_program/textures/item/pallet.png']
AUDIO_ASSETS = {'assets/star_program_forklift/sounds.json',
                'assets/star_program_forklift/sounds/lift/move.ogg',
                'compatibility/forklift-audio/manifest.json', 'credits/forklift-audio.txt'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def current_assets():
    build = c.read_json(FORKLIFT / 'build-report.json')
    manifest = c.read_json(FORKLIFT / 'model-manifest.json')
    source_hash = c.digest((FORKLIFT / 'forklift.bbmodel').read_bytes())
    require(build.get('sourceSHA256') == manifest.get('sourceSHA256') == source_hash,
            'Save and package the changed forklift source first')
    require(build.get('checks') and all(value is True for value in build['checks'].values()),
            'Forklift native build has a failed check')
    require(build.get('uniqueItemModels') == 8 and build.get('elements') == 74,
            'Preserve the eight models and seventy-four cuboids')
    require(manifest['liftRigSHA256'] == c.digest((FORKLIFT / 'lift-rig.json').read_bytes()),
            'Forklift rig changed after model packaging')
    files = {}
    for entry in build['files']:
        name = entry['name']
        data = (FORKLIFT / 'export' / name).read_bytes()
        require(c.digest(data) == entry['SHA256'] and len(data) == entry['bytes'],
                'Forklift export changed after packaging: ' + name)
        if name.startswith('assets/'):
            files[name] = data
    actual = {path.relative_to(FORKLIFT / 'export').as_posix()
              for path in (FORKLIFT / 'export/assets').rglob('*') if path.is_file()}
    require(set(files) == actual == ASSETS, 'Expected precisely seventeen existing forklift assets')
    geometry_changes = {}
    with ZipFile(c.BASE) as base:
        for name, data in files.items():
            require(name in base.namelist(), 'The overlay must not introduce new asset paths')
            if '/items/' in name:
                require(data == base.read(name), 'Keep every custom item definition byte-identical')
            elif name.endswith('.json'):
                new, old = json.loads(data), json.loads(base.read(name))
                require(new.get('textures') == old.get('textures'), 'Texture resource IDs must remain stable')
                for element in new['elements']:
                    require(all(isinstance(value, (int, float)) and -16 <= value <= 32
                                for field in ['from', 'to'] for value in element[field]),
                            'Native Java element bounds exceeded')
                # Existing front/rear wheels share names in the assembly.
                # Keep ordered elements rather than collapsing those cuboids.
                geometry = lambda model: [{key: value for key, value in element.items() if key != 'faces'}
                                          for element in model['elements']]
                before, after = geometry(old), geometry(new)
                require(len(before) == len(after)
                        and [element['name'] for element in before] == [element['name'] for element in after],
                        'Preserve all ordered model cuboids')
                changed = sorted(before[index]['name'] for index in range(len(before)) if before[index] != after[index])
                if changed:
                    geometry_changes[name] = changed
        require(set(geometry_changes) == {'assets/star_program/models/item/' + name + '.json'
                                         for name in ['forklift', 'forklift_body', 'forklift_mast_stage_3']},
                'Geometry may change only in the assembled, body and third-stage models')
        require(len(geometry_changes['assets/star_program/models/item/forklift.json']) == 3,
                'Expected precisely three changed assembled cuboids')
        base_pallet_manifest = c.read_json(c.SOURCE / 'compatibility/mc26.3/forklift-pallet/pallet/model-manifest.json')
        require(c.digest((PALLET / 'wooden_pallet.bbmodel').read_bytes()) == base_pallet_manifest['sourceSHA256'],
                'The authoritative pallet source must remain unchanged')
        for name in PALLET_ASSETS:
            require((PALLET / 'export' / name).read_bytes() == base.read(name),
                    'Pallet native asset changed: ' + name)
    return files, build, manifest, geometry_changes


def validate_archive(data, files):
    require(c.digest(c.BASE.read_bytes()) == BASE_SHA, 'Pinned base archive changed')
    require(len(data) <= c.LIMIT, 'The final full pack exceeds forty MiB')
    with ZipFile(c.BASE) as old, ZipFile(BytesIO(data)) as new:
        before, after = old.namelist(), new.namelist()
        require(len(before) == len(set(before)) == 2591 and len(after) == len(set(after)) == 2595,
                'Unexpected archive membership or duplicate paths')
        require(set(files) == ASSETS | AUDIO_ASSETS and not set(before) & AUDIO_ASSETS,
                'Unexpected overlay or existing forklift audio namespace')
        require(set(after) == set(before) | AUDIO_ASSETS and old.comment == new.comment,
                'Archive entries or comment changed')
        require(old.testzip() is None and new.testzip() is None, 'ZIP CRC failure')
        changed = sorted(name for name in before if old.read(name) != new.read(name))
        require(changed and set(changed) <= ASSETS, 'Only forklift assets may change')
        for name in before:
            require(new.read(name) == files.get(name, old.read(name)), 'Unexpected pack entry: ' + name)
        for name in AUDIO_ASSETS:
            require(new.read(name) == files[name], 'New lift audio differs from reviewed bytes: ' + name)
        require(sum(name.endswith('.ogg') for name in before) == 102,
                'Preserve all one-hundred-two audio clips')
        require(sum(name.endswith('.ogg') for name in after) == 103, 'Add exactly one short lift recording')
        metadata = json.loads(new.read('pack.mcmeta'))['pack']
        require(metadata['min_format'] == metadata['max_format'] == [97, 1],
                'Keep the Minecraft26.3 pack metadata')
        return changed


def make_manifest(build, forklift, audio_manifest):
    baseline = c.read_json(c.SOURCE / 'compatibility/mc26.3/forklift-pallet/manifest.json')
    result = deepcopy(baseline)
    result['revision'] = 'mast-clearance-fix'
    result['forklift'].update({'sourceSHA256': forklift['sourceSHA256'],
                              'liftRigSHA256': forklift['liftRigSHA256'],
                              'manifestFile': PREFIX + 'forklift/model-manifest.json',
                              'nativeBuildReport': PREFIX + 'forklift/native-build-report.json',
                              'cuboids': build['elements']})
    result['audio'] = {'namespace': audio_manifest['namespace'], 'soundEvents': ['star_program_forklift:lift.move'],
                       'manifestFile': 'compatibility/forklift-audio/manifest.json',
                       'manifestSha256': c.digest(c.json_bytes(audio_manifest)),
                       'license': audio_manifest['source']['license'], 'source': audio_manifest['source']['page']}
    return result


def reviewed_overlay():
    files, native_build, forklift, geometry_changes = current_assets()
    additions, audio_manifest = audio.overlay_files()
    require(set(additions) == AUDIO_ASSETS and audio_manifest['namespace'] == 'star_program_forklift'
            and audio_manifest['source']['license'] == 'CC0-1.0'
            and audio_manifest['sounds']['lift.move']['durationMs'] == 240
            and audio_manifest['sounds']['lift.move']['channels'] == 1,
            'Expected the reviewed short mono CC0 forklift recording')
    files.update(additions)
    return files, native_build, forklift, geometry_changes, audio_manifest


def build():
    config_bytes = c.CONFIG.read_bytes()
    config = json.loads(config_bytes)
    c.assert_parent(config)
    files, native_build, forklift, geometry_changes, audio_manifest = reviewed_overlay()
    manifest = make_manifest(native_build, forklift, audio_manifest)
    output = BytesIO()
    with ZipFile(c.BASE) as old, ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=9) as new:
        new.comment = old.comment
        for info in old.infolist():
            new.writestr(copy(info), files.get(info.filename, old.read(info.filename)))
        for name in sorted(AUDIO_ASSETS):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            new.writestr(info, files[name], compresslevel=9)
    data = output.getvalue()
    changed = validate_archive(data, files)
    report = {'version': 1, 'basePack': c.BASE.name, 'baseURL': config['url'], 'baseCommit': PARENT,
              'baseSHA256': BASE_SHA, 'sha1': hashlib.sha1(data).hexdigest(), 'sha256': c.digest(data),
              'gitBlob': c.blob_hash(data), 'size': len(data), 'sizeLimitBytes': c.LIMIT,
              'remainingBytes': c.LIMIT-len(data), 'existingAssetCount': 2591,
              'existingAudioClipsVerified': 102, 'newAudioClips': 1, 'addedFiles': sorted(AUDIO_ASSETS), 'removedFiles': [],
              'changedExistingFiles': changed, 'geometryChanges': geometry_changes,
              'manifestSha256': c.digest(c.json_bytes(manifest)), 'forkliftPallet': manifest,
              'assets': [{'file': name, 'sha256': c.digest(value), 'size': len(value)}
                         for name, value in sorted(files.items())],
              'checks': {'currentSourceAndNativeBuildMatch': True, 'exactThreeGeometryEdits': True,
                         'itemMappingsByteIdentical': True, 'palletAssetsByteIdentical': True,
                         'unrelatedAssetsByteIdentical': True, 'allAudioByteIdentical': True,
                         'packMetadataByteIdentical': True, 'zipMembershipAndCRCs': True,
                         'nativeJavaBounds': True, 'reviewedCC0LiftAudio': True, 'under40MiB': True},
              'runtimePinUnchanged': True, 'published': False}
    c.preserve(c.PACK, data)
    c.preserve(c.REPORT, c.json_bytes(report))
    require(c.CONFIG.read_bytes() == config_bytes, 'Runtime pin changed during build')
    return report


def prepared():
    files, native_build, forklift, geometry_changes, audio_manifest = reviewed_overlay()
    manifest = make_manifest(native_build, forklift, audio_manifest)
    report, data = c.read_json(c.REPORT), c.PACK.read_bytes()
    changed = validate_archive(data, files)
    require(report['sha256'] == c.digest(data) and report['sha1'] == hashlib.sha1(data).hexdigest()
            and report['gitBlob'] == c.blob_hash(data) and report['size'] == len(data)
            and report['baseSHA256'] == BASE_SHA and report['baseCommit'] == PARENT
            and report['changedExistingFiles'] == changed and report['geometryChanges'] == geometry_changes
            and report['addedFiles'] == sorted(AUDIO_ASSETS) and report['removedFiles'] == []
            and report['forkliftPallet'] == manifest
            and report['manifestSha256'] == c.digest(c.json_bytes(manifest))
            and all(value is True for value in report['checks'].values()),
            'Prepared mast-fix archive or evidence changed')
    recipe = Path(__file__).read_bytes()
    if c.UPLOAD.exists():
        verified = c.read_json(c.UPLOAD)
        require(verified.get('status') == 'published' and verified.get('sha256') == report['sha256']
                and re.fullmatch('[a-f0-9]{40}', verified.get('commit', '')), 'Invalid publication evidence')
        recipe = c.git(c.CHECKOUT, 'show', verified['commit'] + ':' + PREFIX + 'publication.py', raw=True)
    return report, manifest, {
        c.PACK.name: data, PREFIX + 'pack-build-report.json': c.REPORT.read_bytes(),
        MANIFEST_PATH: c.json_bytes(manifest), PREFIX + 'publication.py': recipe,
        PREFIX + 'forklift/model-manifest.json': (FORKLIFT / 'model-manifest.json').read_bytes(),
        PREFIX + 'forklift/native-build-report.json': (FORKLIFT / 'build-report.json').read_bytes(),
        PREFIX + 'forklift/lift-rig.json': (FORKLIFT / 'lift-rig.json').read_bytes(),
        PREFIX + 'audio/manifest.json': c.json_bytes(audio_manifest),
        PREFIX + 'audio/build.py': (GAME / 'tools/forklift-audio.py').read_bytes(),
        PREFIX + 'audio/source/nuckan-forklift-hydraulics-hq.mp3': audio.SOURCE.read_bytes(),
        PREFIX + 'audio/source/license.txt': (audio.ROOT / 'source/license.txt').read_bytes(),
    }


c.prepared = prepared


def commit_local():
    c.assert_parent(c.read_json(c.CONFIG))
    report, _, payload = prepared()
    c.check_checkout()
    if c.git(c.CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(set(c.changes()) == {('A ', name) for name in payload}, 'Stage precisely the mast-fix payload')
        for name, value in payload.items():
            require(c.git(c.CHECKOUT, 'show', ':' + name, raw=True) == value, 'Staged bytes changed: ' + name)
        c.git(c.CHECKOUT, 'commit', '-m', 'Correct forklift mast clearance and add recorded hydraulic motion audio')
    return {'status': 'committed', 'commit': c.check_commit(payload), 'branch': c.BRANCH,
            'sha256': report['sha256'], 'published': False}


def pin(commit=None):
    report, manifest, commit, url = c.publication_context(commit)
    verified = c.read_json(c.UPLOAD)
    expected = {'status': 'published', 'commit': commit, 'branch': c.BRANCH, 'url': url,
                'httpStatus': 200, 'sha1': report['sha1'], 'sha256': report['sha256'],
                'size': report['size'], 'gitBlob': report['gitBlob'], 'matchesLocalArtifact': True}
    require(all(verified.get(key) == value for key, value in expected.items()) and verified.get('verifiedAt'),
            'Verify the immutable mast-fix pack before pinning')
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    metadata = {**manifest, 'manifestFile': MANIFEST_PATH, 'manifestSha256': report['manifestSha256'], 'packCommit': commit}
    audio_metadata = {**c.read_json(audio.ROOT / 'manifest.json'),
                      'manifestFile': 'compatibility/forklift-audio/manifest.json', 'packCommit': commit}
    if config.get('url') == url:
        require(config['sha256'] == report['sha256'] and config['forkliftPallet'] == metadata
                and config.get('forkliftAudio') == audio_metadata
                and config['cargoElevatorAudio']['packCommit'] == commit, 'Existing pin metadata differs')
        return {'status': 'already-pinned', 'url': url}
    c.assert_parent(config)
    require(config.get('projectId') == PROJECT_ID and config.get('targetMinecraft') == '26.3', 'Wrong project/version')
    cargo = config['cargoElevatorAudio']
    cargo_source = c.read_json(ROOT / 'cargo-elevator-audio/manifest.json')
    require(cargo['packCommit'] == PARENT
            and {key: value for key, value in cargo.items() if key not in ['manifestFile', 'packCommit']} == cargo_source,
            'Cargo component metadata changed')
    with ZipFile(c.PACK) as archive:
        require(json.loads(archive.read(cargo['manifestFile'])) == cargo_source, 'Cargo manifest bytes changed')
        for sound in cargo_source['sounds'].values():
            require(c.digest(archive.read(sound['file'])) == sound['sha256'], 'Cargo sound changed')
    backup = c.CONFIG.parent / 'backups/resource-pack-before-forklift-mast-fix-4506def8e989.json'
    c.preserve(backup, before)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['forkliftPallet'] = metadata
    config['forkliftAudio'] = audio_metadata
    config['cargoElevatorAudio']['packCommit'] = commit
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    changed = {'url', 'sha1', 'sha256', 'size', 'previousUrls', 'forkliftPallet', 'forkliftAudio', 'cargoElevatorAudio', 'publication'}
    require(all(config[key] == value for key, value in json.loads(before).items() if key not in changed),
            'Unrelated runtime configuration changed')
    require({key: value for key, value in cargo.items() if key != 'packCommit'}
            == {key: value for key, value in json.loads(before)['cargoElevatorAudio'].items() if key != 'packCommit'},
            'Cargo metadata changed beyond the containment reference')
    temporary = c.CONFIG.with_suffix('.forklift-mast-fix-pinning.json')
    c.preserve(temporary, c.json_bytes(config))
    require(c.CONFIG.read_bytes() == before, 'Resource configuration changed before atomic pin')
    temporary.replace(c.CONFIG)
    return {'status': 'pinned', 'commit': commit, 'url': url, 'sha256': report['sha256'],
            'sha1': report['sha1'], 'size': report['size'], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    parser.add_argument('commit', nargs='?')
    args = parser.parse_args()
    if args.commit and (args.action not in ['verify', 'pin'] or not re.fullmatch('[a-f0-9]{40}', args.commit)):
        parser.error('Only verify/pin accept an immutable commit')
    actions = {'build': build, 'prepared': lambda: prepared()[0], 'stage': c.stage,
               'commit': commit_local, 'publish': c.publish,
               'verify': lambda: c.verify(args.commit), 'pin': lambda: pin(args.commit)}
    result = actions[args.action]()
    print(json.dumps({key: value for key, value in result.items() if key != 'forkliftPallet'}, indent=2))
