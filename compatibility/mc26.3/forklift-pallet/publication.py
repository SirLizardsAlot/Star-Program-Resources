"""Add forklift/pallet models to the pinned full pack, then publish and pin it.

Build, stage and commit are local. Publication uses an isolated checkout and
the established guarded resource workflow. No game code is sent to Minecraft.
"""
from __future__ import annotations

import argparse
from copy import copy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
FORKLIFT = GAME / 'models/forklift'
PALLET = GAME / 'models/wooden-pallet'
PREFIX = 'compatibility/mc26.3/forklift-pallet/'
MANIFEST_PATH = PREFIX + 'manifest.json'
PARENT = 'aeea15dc2d3e1d064e2df5397dd7fb361b95905d'
BASE_SHA = '07b1a53f690c7741d88e8332f2dedf428ca98cb5cae847bb6facda15b933976c'
PROJECT_ID = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'
FORKLIFT_IDS = ['forklift', 'forklift_body', 'forklift_lift',
                'forklift_mast_stage_1', 'forklift_mast_stage_2',
                'forklift_mast_stage_3', 'forklift_front_wheel',
                'forklift_rear_wheel']


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


previous = module('forklift_publication_previous', GAME / 'tools/keycard-publication.py')
c = previous.c
c.SOURCE = ROOT / 'cargo-elevator-direct-drive-publication'
c.CHECKOUT = ROOT / 'forklift-pallet-publication'
c.BASE = ROOT / 'cargo-elevator-audio/sp_cargo-elevator-direct-drive-mc26.3.zip'
c.PACK = ROOT / 'sp_forklift-pallet-mc26.3.zip'
c.REPORT = c.PACK.with_suffix('.report.json')
c.UPLOAD = ROOT / 'upload-report-forklift-pallet.json'
c.PARENT, c.PARENT_SHA256 = PARENT, BASE_SHA
c.BRANCH = 'codex/star-program-forklift-pallet'
c.ensure_checkout = previous.ensure_checkout


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reviewed_assets():
    sources = {
        'forklift': (FORKLIFT, 'forklift.bbmodel'),
        'pallet': (PALLET, 'wooden_pallet.bbmodel'),
    }
    builds, manifests, files = {}, {}, {}
    expected = {f'assets/star_program/{directory}/{name}.json'
                for name in FORKLIFT_IDS for directory in ['items', 'models/item']}
    expected |= {'assets/star_program/textures/item/forklift.png',
                 'assets/star_program/items/wooden_pallet.json',
                 'assets/star_program/models/item/wooden_pallet.json',
                 'assets/star_program/textures/item/pallet.png'}
    for key, (folder, source_name) in sources.items():
        build = c.read_json(folder / 'build-report.json')
        manifest = c.read_json(folder / 'model-manifest.json')
        source_hash = c.digest((folder / source_name).read_bytes())
        require(build.get('sourceSHA256') == manifest.get('sourceSHA256') == source_hash,
                f'Save and package the current {key} source before merging the pack')
        require(build.get('checks') and all(value is True for value in build['checks'].values()),
                f'The {key} native build has a failed check')
        listed = {}
        for entry in build['files']:
            name = entry['name']
            data = (folder / 'export' / name).read_bytes()
            require(c.digest(data) == entry['SHA256'] and len(data) == entry['bytes'],
                    'Native export changed after validation: ' + name)
            if name.startswith('assets/'):
                listed[name] = data
        actual = {p.relative_to(folder / 'export').as_posix()
                  for p in (folder / 'export/assets').rglob('*') if p.is_file()}
        require(actual == set(listed), f'Unexpected {key} export files')
        require(not set(files) & set(listed), 'Model export paths overlap')
        files.update(listed)
        builds[key], manifests[key] = build, manifest
    require(set(files) == expected, 'Expected exactly the twenty forklift/pallet assets')
    rig_hash = c.digest((FORKLIFT / 'lift-rig.json').read_bytes())
    require(manifests['forklift']['liftRigSHA256'] == rig_hash
            and manifests['pallet']['pickupFit']['forkliftSourceSHA256'] == manifests['forklift']['sourceSHA256']
            and manifests['pallet']['pickupFit']['forkliftRigSHA256'] == rig_hash,
            'The pallet fit and forklift source/rig no longer match')
    for name, data in files.items():
        resource = PurePosixPath(name)
        require(not resource.is_absolute() and '..' not in resource.parts and '\\' not in name,
                'Unsafe asset path')
        if name.endswith('.json'):
            value = json.loads(data)
            if '/items/' in name:
                item = resource.stem
                require(value == {'model': {'type': 'minecraft:model', 'model': f'star_program:item/{item}'}},
                        'Unexpected custom item mapping: ' + name)
            else:
                require(value.get('elements'), 'Native model is empty')
                for element in value['elements']:
                    require(all(isinstance(number, (int, float)) and -16 <= number <= 32
                                for field in ['from', 'to'] for number in element[field]),
                            'Native element bounds exceeded: ' + name)
                for texture in value['textures'].values():
                    namespace, resource_path = texture.split(':', 1)
                    require(f'assets/{namespace}/textures/{resource_path}.png' in files,
                            'Missing native texture: ' + texture)
    return files, builds, manifests


def validate_archive(data, files):
    require(len(data) <= c.LIMIT, 'Full pack exceeds the 40 MiB upload limit')
    require(c.digest(c.BASE.read_bytes()) == BASE_SHA, 'The pinned cargo base archive changed')
    with ZipFile(c.BASE) as old, ZipFile(BytesIO(data)) as new:
        before, after = old.namelist(), new.namelist()
        require(len(before) == len(set(before)) == 2571 and len(after) == len(set(after)),
                'Unexpected base count or duplicate ZIP paths')
        require(old.testzip() is None and new.testzip() is None, 'ZIP CRC failure')
        require(not set(before) & set(files), 'A new model path already exists in the pinned pack')
        require(set(after) == set(before) | set(files), 'Unexpected added or removed pack entries')
        require(old.comment == new.comment, 'Archive comment changed')
        for name in before:
            require(old.read(name) == new.read(name), 'Existing pack entry changed: ' + name)
        for name, content in files.items():
            require(new.read(name) == content, 'Merged pack differs from native export: ' + name)
        metadata = json.loads(new.read('pack.mcmeta'))
        require(metadata['pack']['min_format'] == metadata['pack']['max_format'] == [97, 1],
                'Keep the existing Minecraft 26.3 pack format')
        audio = sum(name.endswith('.ogg') for name in before)
        require(audio == 102, 'Existing audio membership changed')
        return len(before), audio


def make_manifest(builds, manifests):
    return {
        'version': 1, 'projectId': PROJECT_ID, 'targetMinecraft': '26.3',
        'resourceFormat': [97, 1], 'namespace': 'star_program',
        'itemModels': [f'star_program:{name}' for name in [*FORKLIFT_IDS, 'wooden_pallet']],
        'forklift': {'sourceSHA256': manifests['forklift']['sourceSHA256'],
                     'liftRigSHA256': manifests['forklift']['liftRigSHA256'],
                     'manifestFile': PREFIX + 'forklift/model-manifest.json',
                     'nativeBuildReport': PREFIX + 'forklift/native-build-report.json',
                     'cuboids': builds['forklift']['elements'], 'itemDisplayScale': [2, 2, 2],
                     'liftMaximumDeckHeightBlocks': manifests['forklift']['liftTravel']['forkDeckMaximumHeightBlocks']},
        'pallet': {'sourceSHA256': manifests['pallet']['sourceSHA256'],
                   'manifestFile': PREFIX + 'pallet/model-manifest.json',
                   'nativeBuildReport': PREFIX + 'pallet/native-build-report.json',
                   'cuboids': builds['pallet']['elements'], 'itemDisplayScale': [1, 1, 1],
                   'pickupOffsetFromLiftPivotBlocks': manifests['pallet']['pickupFit']['firstContact']['palletOffsetFromLiftPivotBlocks']},
    }


def build():
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    c.assert_parent(config)
    require(config.get('projectId') == PROJECT_ID and config.get('targetMinecraft') == '26.3',
            'Unexpected runtime project or version')
    files, builds, manifests = reviewed_assets()
    manifest = make_manifest(builds, manifests)
    with ZipFile(c.BASE) as old:
        require(old.testzip() is None, 'Pinned archive CRC failure')
        output = BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=9) as new:
            new.comment = old.comment
            for info in old.infolist():
                new.writestr(copy(info), old.read(info.filename))
            for name, data in sorted(files.items()):
                info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                new.writestr(info, data, compresslevel=9)
    data = output.getvalue()
    entry_count, audio_count = validate_archive(data, files)
    report = {'version': 1, 'basePack': c.BASE.name,
              'baseURL': config['url'], 'baseCommit': PARENT, 'baseSHA256': BASE_SHA,
              'size': len(data), 'sizeLimitBytes': c.LIMIT, 'remainingBytes': c.LIMIT-len(data),
              'sha1': hashlib.sha1(data).hexdigest(), 'sha256': c.digest(data),
              'gitBlob': c.blob_hash(data), 'existingAssetCount': entry_count,
              'existingAudioClipsVerified': audio_count, 'addedFiles': sorted(files),
              'changedExistingFiles': [], 'removedFiles': [],
              'assets': [{'file': name, 'size': len(content), 'sha256': c.digest(content)}
                         for name, content in sorted(files.items())],
              'manifestSha256': c.digest(c.json_bytes(manifest)), 'forkliftPallet': manifest,
              'checks': {'modelSourcesAndBuildsMatch': True, 'palletFitMatchesForklift': True,
                         'allExistingEntriesByteIdentical': True, 'allExistingAudioByteIdentical': True,
                         'packMetadataByteIdentical': True, 'itemMappingsVerified': True,
                         'nativeBoundsAndTexturesVerified': True, 'zipMembershipAndCRCs': True,
                         'under40MiB': True}, 'runtimePinUnchanged': True, 'published': False}
    c.preserve(c.PACK, data)
    c.preserve(c.REPORT, c.json_bytes(report))
    require(c.CONFIG.read_bytes() == before, 'Runtime configuration changed during build')
    return report


def prepared():
    files, builds, manifests = reviewed_assets()
    manifest = make_manifest(builds, manifests)
    report, data = c.read_json(c.REPORT), c.PACK.read_bytes()
    entry_count, audio_count = validate_archive(data, files)
    require(report['sha256'] == c.digest(data) and report['sha1'] == hashlib.sha1(data).hexdigest()
            and report['size'] == len(data) and report['gitBlob'] == c.blob_hash(data)
            and report['baseSHA256'] == BASE_SHA and report['baseCommit'] == PARENT
            and report['forkliftPallet'] == manifest
            and report['manifestSha256'] == c.digest(c.json_bytes(manifest))
            and report['addedFiles'] == sorted(files) and report['changedExistingFiles'] == []
            and report['removedFiles'] == [] and report['existingAssetCount'] == entry_count
            and report['existingAudioClipsVerified'] == audio_count
            and all(value is True for value in report['checks'].values()),
            'Prepared pack/report/model assets changed')
    payload = {c.PACK.name: data, PREFIX + 'pack-build-report.json': c.REPORT.read_bytes(),
               MANIFEST_PATH: c.json_bytes(manifest), PREFIX + 'publication.py': Path(__file__).read_bytes(),
               PREFIX + 'forklift/lift-rig.json': (FORKLIFT / 'lift-rig.json').read_bytes()}
    for key, folder in [('forklift', FORKLIFT), ('pallet', PALLET)]:
        payload[PREFIX + key + '/model-manifest.json'] = (folder / 'model-manifest.json').read_bytes()
        payload[PREFIX + key + '/native-build-report.json'] = (folder / 'build-report.json').read_bytes()
    return report, manifest, payload


c.prepared = prepared


def commit_local():
    c.assert_parent(c.read_json(c.CONFIG))
    report, _, payload = prepared()
    c.check_checkout()
    if c.git(c.CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(set(c.changes()) == {('A ', name) for name in payload}, 'Stage exactly the reviewed model payload')
        for name, content in payload.items():
            require(c.git(c.CHECKOUT, 'show', ':' + name, raw=True) == content,
                    'Staged payload changed: ' + name)
        c.git(c.CHECKOUT, 'commit', '-m', 'Add telescoping forklift and matching wooden pallet models')
    return {'status': 'committed', 'commit': c.check_commit(payload), 'branch': c.BRANCH,
            'sha256': report['sha256'], 'published': False}


def pin(commit=None):
    report, manifest, commit, url = c.publication_context(commit)
    verified = c.read_json(c.UPLOAD)
    expected = {'status': 'published', 'commit': commit, 'branch': c.BRANCH, 'url': url,
                'httpStatus': 200, 'sha1': report['sha1'], 'sha256': report['sha256'],
                'size': report['size'], 'gitBlob': report['gitBlob'], 'matchesLocalArtifact': True}
    require(all(verified.get(key) == value for key, value in expected.items())
            and verified.get('verifiedAt'), 'Verify immutable publication before pinning')
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    metadata = {**manifest, 'manifestFile': MANIFEST_PATH,
                'manifestSha256': report['manifestSha256'], 'packCommit': commit}
    if config.get('url') == url:
        require(config.get('sha256') == report['sha256'] and config.get('forkliftPallet') == metadata,
                'Inconsistent existing forklift/pallet pin')
        return {'status': 'already-pinned', 'url': url}
    c.assert_parent(config)
    require(config.get('projectId') == PROJECT_ID and config.get('targetMinecraft') == '26.3',
            'Unexpected runtime project or version')
    backup = c.CONFIG.parent / 'backups/resource-pack-before-forklift-pallet-07b1a53f690c.json'
    c.preserve(backup, before)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['forkliftPallet'] = metadata
    config.setdefault('publication', {}).update({key: verified[key]
                                               for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    changed = {'url', 'sha1', 'sha256', 'size', 'previousUrls', 'forkliftPallet', 'publication'}
    require(all(config[key] == value for key, value in json.loads(before).items() if key not in changed),
            'Unrelated pack configuration changed')
    temporary = c.CONFIG.with_suffix('.forklift-pallet-pinning.json')
    c.preserve(temporary, c.json_bytes(config))
    require(c.CONFIG.read_bytes() == before, 'Runtime pin changed before atomic replacement')
    temporary.replace(c.CONFIG)
    return {'status': 'pinned', 'commit': commit, 'url': url, 'sha1': report['sha1'],
            'sha256': report['sha256'], 'size': report['size'], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    parser.add_argument('commit', nargs='?')
    args = parser.parse_args()
    if args.commit and (args.action not in ['verify', 'pin'] or not re.fullmatch('[a-f0-9]{40}', args.commit)):
        parser.error('Only verify/pin accept a complete immutable commit')
    actions = {'build': build, 'prepared': lambda: prepared()[0], 'stage': c.stage,
               'commit': commit_local, 'publish': c.publish,
               'verify': lambda: c.verify(args.commit), 'pin': lambda: pin(args.commit)}
    result = actions[args.action]()
    print(json.dumps({key: value for key, value in result.items() if key != 'forkliftPallet'}, indent=2))
