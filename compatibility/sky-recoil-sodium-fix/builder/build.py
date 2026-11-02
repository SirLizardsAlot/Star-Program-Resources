"""Fix the installed Sodium Extra varying collision without changing vanilla.

The final archive differs from the pinned pack in exactly two Sodium shader
files and pack.mcmeta. Build/compile checks are local and never launch a game.
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
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
if HERE.name == 'sodium-fix-release':
    HERE = HERE.parent
ROOT = HERE.parent
GAME = ROOT.parent
STAGE = HERE / 'sodium-fix-release'
CONFIG = GAME / 'config/resource-pack.json'
BASE_SHA = '599788d1586f5fe228e28bd2bdf481e4fe1be5c04ff65da373506235e39c1426'
PARENT = '0d029c033f075b4a9e6aa2cc5ec266642a3ebaa4'
PACK = 'sp_sky-recoil-sodium-fix-mc26.3.zip'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing existing file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build():
    current = json.loads(CONFIG.read_bytes())
    require(current['sha256'] == BASE_SHA and current['publication']['commit'] == PARENT,
            'Current resource pin differs from the reviewed failing pack')
    preserve(STAGE / 'base-pin.json', CONFIG.read_bytes())
    data = (HERE / 'sp_sky-recoil-panels-mc26.3.zip').read_bytes()
    require(sha(data) == BASE_SHA, 'Pinned input archive changed')
    with ZipFile(BytesIO(data)) as archive:
        before = {name: archive.read(name) for name in archive.namelist()}
        entries = archive.infolist()
    patches = {}
    for extension, direction in [('vsh', 'out'), ('fsh', 'in')]:
        name = 'assets/sodium/shaders/blocks/block_layer_opaque.' + extension
        old = f'layout(location = 4) {direction} vec3 spSkyRay;'.encode()
        new = f'layout(location = 6) {direction} vec3 spSkyRay;'.encode()
        require(before[name].count(old) == 1, 'Expected one original sky varying: ' + name)
        patches[name] = before[name].replace(old, new)
        source = HERE / 'overrides' / name
        require(source.read_bytes() in (before[name], patches[name]), 'Preserve edited source: ' + name)
        preserve(STAGE / 'before' / name, before[name])
        source.write_bytes(patches[name])
    meta = json.loads(before['pack.mcmeta'])
    meta['sodium'] = {'ignored_shaders': ['terrain.vsh', 'terrain.fsh']}
    patches['pack.mcmeta'] = encoded(meta)
    # The ignored files are the vanilla fallback. Sodium still uses its own
    # dedicated replacements in this same archive.
    for name, content in patches.items():
        preserve(STAGE / 'overrides' / name, content)
    (HERE / 'overrides/pack.mcmeta').write_bytes(patches['pack.mcmeta'])
    generator = HERE / 'sodium_patch.py'
    original = generator.read_bytes()
    updated = original.replace(b'layout(location = 4) out vec3 spSkyRay;', b'layout(location = 6) out vec3 spSkyRay;')
    updated = updated.replace(b'layout(location = 4) in vec3 spSkyRay;', b'layout(location = 6) in vec3 spSkyRay;')
    if original != updated:
        preserve(STAGE / 'before/sodium_patch.py', original)
        generator.write_bytes(updated)
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for entry in entries:
            archive.writestr(entry, patches.get(entry.filename, before[entry.filename]))
    final = output.getvalue()
    require(len(final) <= 41943040, 'Pack exceeds upload limit')
    artifact = HERE / PACK
    artifact.write_bytes(final)
    validator = module('sodium_fix_validator', HERE / 'validate_shaders.py')
    validation = validator.validate(artifact, ROOT / 'mc26.3/reference/minecraft-client.jar')
    with ZipFile(BytesIO(final)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failure')
        changed = [name for name, value in before.items() if archive.read(name) != value]
        require(set(changed) == set(patches) and set(archive.namelist()) == set(before), 'Unexpected resource change')
    report = {'version': 1, 'basePack': 'sp_sky-recoil-panels-mc26.3.zip', 'baseSHA256': BASE_SHA,
              'pack': PACK, 'sha256': sha(final), 'sha1': hashlib.sha1(final).hexdigest(),
              'size': len(final), 'changedExistingFiles': sorted(changed), 'addedFiles': [], 'removedFiles': [],
              'unchangedEntries': len(before) - 3, 'existingAudioPreserved': True,
              'vanillaShadersByteIdentical': True, 'shaderValidation': validation,
              'fix': 'Reserve varying locations4/5 for Sodium Extra, move the sky ray to6'}
    (STAGE / 'build-report.json').write_bytes(encoded(report))
    (STAGE / PACK).write_bytes(final)
    preserve(STAGE / 'native-controls.json', (HERE / 'native-controls.json').read_bytes())
    # Reuse the existing guarded immutable-branch publication transport in an
    # isolated release directory. Prior archives and publication branches stay.
    for name in ['prepare_sky.py', 'sodium_patch.py', 'transport.py', 'panel_models.py', 'validate_shaders.py', 'release.py']:
        preserve(STAGE / name, (HERE / name).read_bytes())
    (STAGE / 'build.py').write_bytes(Path(__file__).read_bytes())
    preserve(STAGE / 'README.md', b'# Sodium and Sodium Extra compatibility fix\n\n'
             b'Only the dedicated Sodium sky varying and compatibility metadata change.\n'
             b'Vanilla shaders, native helpers, sky models and existing audio stay byte-identical.\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'shaderValidation'}
          | {'shaderStages': validation['stagesCompiled']}, indent=2))


def transport():
    release = module('sky_sodium_hotfix_release', HERE / 'release.py')
    release.HERE, release.BASE_PIN = STAGE, STAGE / 'base-pin.json'
    release.SOURCE = ROOT / 'sky-recoil-panels-publication'
    release.CHECKOUT = ROOT / 'sky-recoil-sodium-fix-publication'
    release.PARENT, release.BASE_SHA = PARENT, BASE_SHA
    release.BRANCH = 'codex/star-program-sky-recoil-sodium-fix'
    release.PACK = PACK
    release.PREFIX = 'compatibility/sky-recoil-sodium-fix/'
    release.MANIFEST = release.PREFIX + 'manifest.json'
    release.VERIFICATION = STAGE / 'publication-verification.json'
    return release


def pin():
    release = transport()
    report, files, commit = release.stage()
    verified = json.loads(release.VERIFICATION.read_bytes())
    require(verified['commit'] == commit and verified['sha256'] == report['sha256']
            and verified['manifestSha256'] == sha(files[release.MANIFEST]), 'Hosted verification differs')
    original = CONFIG.read_bytes()
    current = json.loads(original)
    require(current['sha256'] == BASE_SHA and original == (STAGE / 'base-pin.json').read_bytes(), 'Pack pin changed')
    preserve(GAME / 'config/backups/resource-pack-before-sodium-sky-fix.json', original)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'].update(manifestFile=release.MANIFEST, manifestSha256=verified['manifestSha256'],
                               sodiumExtraCompatible=True, sodiumSkyVaryingLocation=6)
    current['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    staged = CONFIG.with_suffix('.sodium-fix.json')
    preserve(staged, encoded(current))
    require(CONFIG.read_bytes() == original, 'Pack pin changed before update')
    staged.replace(CONFIG)
    print(json.dumps({'status': 'pinned', 'url': verified['url'], 'sha256': verified['sha256']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'stage', 'publish', 'pin'])
    action = parser.parse_args().action
    if action == 'build':
        build()
    elif action == 'pin':
        pin()
    elif action == 'publish':
        print(json.dumps(transport().publish(), indent=2))
    else:
        report, files, commit = transport().stage()
        print(json.dumps({'status': 'committed', 'commit': commit, 'files': len(files)}, indent=2))
