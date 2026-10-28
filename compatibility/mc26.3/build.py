"""Build and publish the additive Minecraft 26.3 compatibility migration."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
MIGRATION = ROOT / 'mc26.3'
CLIENT = MIGRATION / 'reference/minecraft-client.jar'
OVERRIDES = MIGRATION / 'overrides'
BASE = ROOT / 'sp_keycard-mc26.2.zip'
PACK = ROOT / 'sp_mc26.3.zip'
REPORT = PACK.with_suffix('.report.json')
BASE_SHA256 = 'fa74b2f782336dff549f1aa38a3a942fb847b36d6b2a86f9cad291c9b0705ae8'
PARENT = '0e10d446c3dbe8e463b47b3d540f6019bd79db2d'
CLIENT_SHA1 = 'e877b6a07acd633fb3bb475002175cec036e7b87'
PREFIX = 'compatibility/mc26.3/'
PROJECT_ID = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Reuse the existing guarded publication transport and isolated object-store
# setup. The previous checkout, archives, pins, and branches remain intact.
previous = load_module('mc263_previous_publication', GAME / 'tools/keycard-publication.py')
c = previous.c
c.SOURCE = ROOT / 'keycard-publication'
c.CHECKOUT = ROOT / 'mc26.3-publication'
c.BASE, c.PACK, c.REPORT = BASE, PACK, REPORT
c.UPLOAD = ROOT / 'upload-report-mc26.3.json'
c.PARENT, c.PARENT_SHA256 = PARENT, BASE_SHA256
c.BRANCH = 'codex/star-program-mc26.3'
c.ensure_checkout = previous.ensure_checkout


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inputs():
    require(c.digest(BASE.read_bytes()) == BASE_SHA256, 'Pinned 26.2 base archive changed')
    require(hashlib.sha1(CLIENT.read_bytes()).hexdigest() == CLIENT_SHA1, 'Official 26.3 client changed')
    with ZipFile(CLIENT) as client:
        version = json.loads(client.read('version.json'))
    require(version['id'] == '26.3' and version['pack_version']['resource_major'] == 97
            and version['pack_version']['resource_minor'] == 1, 'Expected official 26.3 resource format 97.1')
    notes = {name: c.read_json(MIGRATION / name) for name in ['shader-migration.json', 'atlas-migration.json']}
    removals = set()
    for note in notes.values():
        removals.update(note.get('removedFiles', []))
    patches = {path.relative_to(OVERRIDES).as_posix(): path.read_bytes()
               for path in OVERRIDES.rglob('*') if path.is_file()}
    patches['pack.mcmeta'] = c.json_bytes({'pack': {'description': 'Star Program - Minecraft 26.3',
                                                  'min_format': [97, 1], 'max_format': [97, 1]}})
    require(patches and not removals.intersection(patches), 'A removed resource also has an override')
    for name in set(patches) | removals:
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'Unsafe resource path')
    return patches, removals, notes


def inspect_archive(data, patches, removals):
    require(len(data) <= c.LIMIT, "Pack exceeds DiamondFire's 40 MiB limit")
    with ZipFile(BASE) as old, ZipFile(BytesIO(data)) as new, ZipFile(CLIENT) as client:
        before, after = old.namelist(), new.namelist()
        require(len(before) == len(set(before)) and len(after) == len(set(after)), 'Duplicate ZIP entries')
        require(old.testzip() is None and new.testzip() is None, 'ZIP CRC failure')
        require(removals <= set(before), 'Removal does not name an existing resource')
        require(set(after) == (set(before) - removals) | set(patches), 'Unexpected resource membership')
        changed = []
        for name in before:
            if name in removals:
                continue
            if name in patches:
                require(new.read(name) == patches[name], 'Override differs from source: ' + name)
                if new.read(name) != old.read(name):
                    changed.append(name)
            else:
                require(new.read(name) == old.read(name), 'Unrelated asset changed: ' + name)
        for name, content in patches.items():
            require(new.read(name) == content, 'Prepared source differs from ZIP: ' + name)
        for name in after:
            if name.endswith('.json') or name.endswith('.mcmeta'):
                json.loads(new.read(name))
        audio = [name for name in before if name.endswith('.ogg')]
        require(all(name in after and old.read(name) == new.read(name) for name in audio), 'Existing audio changed')
        # All post pass targets and shader references must exist in 26.3 or in
        # this pack. The removed Fabulous transparency buffers cannot be used.
        chain = json.loads(new.read('assets/minecraft/post_effect/end_of_frame.json'))
        targets = set(chain.get('targets', {})) | {'minecraft:main'}
        for render_pass in chain['passes']:
            require(render_pass['output'] in targets, 'Missing post output target')
            for entry in render_pass.get('inputs', []):
                require(entry.get('target') in targets, 'Unsupported post input target: ' + str(entry.get('target')))
            for key, suffix in [('vertex_shader', '.vsh'), ('fragment_shader', '.fsh')]:
                identifier = render_pass[key]
                namespace, resource = identifier.split(':', 1) if ':' in identifier else ('minecraft', identifier)
                resource_path = f'assets/{namespace}/shaders/{resource}{suffix}'
                require(resource_path in after or resource_path in client.namelist(), 'Missing post shader: ' + resource_path)
        require('assets/minecraft/post_effect/transparency.json' not in after, 'Obsolete transparency pipeline remains')
        require(json.loads(new.read('pack.mcmeta'))['pack']['min_format'] == [97, 1]
                and json.loads(new.read('pack.mcmeta'))['pack']['max_format'] == [97, 1], 'Wrong pack format')
        return {'changedFiles': sorted(changed), 'addedFiles': sorted(set(after) - set(before)),
                'removedFiles': sorted(removals), 'entries': len(after),
                'existingAssetsByteIdentical': len(before) - len(changed) - len(removals),
                'existingAudioByteIdentical': len(audio),
                'jsonFilesValidated': sum(name.endswith(('.json', '.mcmeta')) for name in after)}


def build():
    c.assert_parent(c.read_json(c.CONFIG))
    patches, removals, notes = inputs()
    output = BytesIO()
    with ZipFile(BASE) as old, ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as new:
        new.comment = old.comment
        for entry in old.infolist():
            if entry.filename not in removals:
                new.writestr(entry, patches.get(entry.filename, old.read(entry.filename)))
        for name in sorted(set(patches) - set(old.namelist())):
            entry = ZipInfo(name, (2026, 10, 28, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            new.writestr(entry, patches[name], compresslevel=9)
    data = output.getvalue()
    details = inspect_archive(data, patches, removals)
    # Always compile the exact final archive, never only loose shader sources.
    temporary = MIGRATION / 'candidate.zip'
    temporary.write_bytes(data)
    validator = load_module('mc263_shader_validator', MIGRATION / 'validate_shaders.py')
    shader_validation = validator.validate(temporary, CLIENT)
    report = {'version': 1, 'projectId': PROJECT_ID, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
              'basePack': BASE.name, 'baseCommit': PARENT, 'baseSHA256': BASE_SHA256,
              'clientSHA1': CLIENT_SHA1, 'packFile': PACK.name, 'size': len(data),
              'sizeLimitBytes': c.LIMIT, 'remainingBytes': c.LIMIT - len(data),
              'sha1': hashlib.sha1(data).hexdigest(), 'sha256': c.digest(data), **details,
              'shaderValidation': shader_validation,
              'sourceHashes': {name: c.digest(content) for name, content in sorted(patches.items())},
              'migrationNotes': notes,
              'checks': {'zipCrc': True, 'jsonParsed': True, 'unrelatedAssetsPreserved': True,
                         'allAudioPreserved': True, 'postReferencesResolved': True,
                         'shaderCompilation': True, 'withinUploadLimit': True}}
    c.preserve(PACK, data)
    c.preserve(REPORT, c.json_bytes(report))
    return {key: report[key] for key in ['packFile', 'size', 'sha1', 'sha256',
                                        'changedFiles', 'addedFiles', 'removedFiles', 'checks']}


def prepared():
    patches, removals, notes = inputs()
    data, report = PACK.read_bytes(), c.read_json(REPORT)
    details = inspect_archive(data, patches, removals)
    require(report['sha256'] == c.digest(data) and report['sha1'] == hashlib.sha1(data).hexdigest()
            and report['size'] == len(data) and report['baseSHA256'] == BASE_SHA256
            and all(report['checks'].values()), 'Prepared build report changed')
    require(all(report[key] == value for key, value in details.items()), 'Prepared resource inventory changed')
    require(report['sourceHashes'] == {name: c.digest(content) for name, content in sorted(patches.items())}
            and report['migrationNotes'] == notes, 'Migration source changed after build')
    manifest = {key: report[key] for key in ['version', 'projectId', 'targetMinecraft', 'resourceFormat',
                'basePack', 'baseCommit', 'baseSHA256', 'clientSHA1', 'packFile', 'size', 'sha1', 'sha256',
                'existingAssetsByteIdentical', 'existingAudioByteIdentical', 'changedFiles', 'addedFiles', 'removedFiles']}
    payload = {PACK.name: data, PREFIX + 'manifest.json': c.json_bytes(manifest),
               PREFIX + 'pack-build-report.json': REPORT.read_bytes(),
               PREFIX + 'build.py': Path(__file__).read_bytes(),
               PREFIX + 'validate_shaders.py': (MIGRATION / 'validate_shaders.py').read_bytes()}
    payload.update({PREFIX + 'overrides/' + name: content for name, content in patches.items()})
    payload.update({PREFIX + name: c.json_bytes(note) for name, note in notes.items()})
    return {**report, 'gitBlob': c.blob_hash(data)}, manifest, payload


c.prepared = prepared


def commit_local():
    c.assert_parent(c.read_json(c.CONFIG))
    report, _, payload = prepared()
    c.check_checkout()
    if c.git(c.CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        require(set(c.changes()) == {('A ', name) for name in payload}, 'Unexpected staged files')
        for name, content in payload.items():
            require(c.git(c.CHECKOUT, 'show', ':' + name, raw=True) == content, 'Staged source changed')
        c.git(c.CHECKOUT, 'commit', '-m', 'Migrate STAR PROGRAM resource pack to Minecraft 26.3')
    return {'status': 'committed', 'commit': c.check_commit(payload), 'branch': c.BRANCH,
            'sha256': report['sha256'], 'published': False}


def pin(commit=None):
    report, manifest, commit, url = c.publication_context(commit)
    verified = c.read_json(c.UPLOAD)
    expected = {'status': 'published', 'commit': commit, 'branch': c.BRANCH, 'url': url,
                'httpStatus': 200, 'sha1': report['sha1'], 'sha256': report['sha256'],
                'size': report['size'], 'gitBlob': report['gitBlob'], 'matchesLocalArtifact': True}
    require(all(verified.get(key) == value for key, value in expected.items()) and verified.get('verifiedAt'),
            'Verify published archive before pinning')
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    if config.get('url') == url:
        require(config['sha256'] == report['sha256'] and config['targetMinecraft'] == '26.3', 'Inconsistent 26.3 pin')
        return {'status': 'already-pinned', 'url': url}
    c.assert_parent(config)
    require(config['projectId'] == PROJECT_ID, 'Unexpected project')
    backup = c.CONFIG.parent / 'backups/resource-pack-before-mc26.3-fa74b2f78233.json'
    c.preserve(backup, before)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['targetMinecraft'], config['resourceFormat'] = '26.3', [97, 1]
    config['compatibility26_3'] = {**manifest, 'manifestFile': PREFIX + 'manifest.json', 'packCommit': commit}
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    config['publication'].pop('pullRequest', None)
    changed = {'url', 'sha1', 'sha256', 'size', 'targetMinecraft', 'resourceFormat',
               'previousUrls', 'compatibility26_3', 'publication'}
    require(all(config[key] == value for key, value in json.loads(before).items() if key not in changed),
            'Unrelated resource configuration changed')
    temporary = c.CONFIG.with_suffix('.mc26.3-pinning.json')
    c.preserve(temporary, c.json_bytes(config))
    require(c.CONFIG.read_bytes() == before, 'Pack pin changed during preparation')
    temporary.replace(c.CONFIG)
    return {'status': 'pinned', 'url': url, 'sha256': report['sha256'], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    parser.add_argument('commit', nargs='?')
    args = parser.parse_args()
    if args.commit and (args.action not in ['verify', 'pin'] or not re.fullmatch('[a-f0-9]{40}', args.commit)):
        parser.error('Only verify and pin accept an immutable commit')
    actions = {'build': build, 'prepared': lambda: prepared()[1], 'stage': c.stage, 'commit': commit_local,
               'publish': c.publish, 'verify': lambda: c.verify(args.commit), 'pin': lambda: pin(args.commit)}
    print(json.dumps(actions[args.action](), indent=2))
