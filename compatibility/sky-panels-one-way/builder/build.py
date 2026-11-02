"""Publish a model-only correction for seeing through Sky Panels from behind."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
if HERE.name == 'panel-back-release':
    HERE = HERE.parent
ROOT, GAME = HERE.parent, HERE.parent.parent
STAGE = HERE / 'panel-back-release'
CONFIG = GAME / 'config/resource-pack.json'
BASE_SHA = 'b6ca0e76d30c1f9e29c3ea710135bada7459c9c49fcd43086c05744adb325c1d'
PARENT = '121fb9e5b3cd8a46d2071e20a483fec5991db24e'
PACK = 'sp_sky-panels-one-way-mc26.3.zip'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build():
    pin = json.loads(CONFIG.read_bytes())
    require(pin['sha256'] == BASE_SHA and pin['publication']['commit'] == PARENT, 'Current pack pin changed')
    preserve(STAGE / 'base-pin.json', CONFIG.read_bytes())
    original = (HERE / 'sp_sky-recoil-sodium-fix-mc26.3.zip').read_bytes()
    require(sha(original) == BASE_SHA, 'Pinned archive changed')
    patches = module('one_way_panel_models', HERE / 'panel_models.py').make_panels()
    with ZipFile(BytesIO(original)) as archive:
        before = {name: archive.read(name) for name in archive.namelist()}
        entries = archive.infolist()
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for entry in entries:
            archive.writestr(entry, patches.get(entry.filename, before[entry.filename]))
    data = output.getvalue()
    require(len(data) <= 41943040, 'Pack exceeds 40 MiB')
    with ZipFile(BytesIO(data)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failure')
        changed = {name for name, content in before.items() if content != archive.read(name)}
        require(changed == set(patches) and set(archive.namelist()) == set(before), 'Unexpected resource changes')
        for name in patches:
            json.loads(archive.read(name))
        require(all(archive.read(name) == content for name, content in before.items()
                    if '/shaders/' in name or name.endswith('.ogg')), 'Shader or audio bytes changed')
    report = {'version': 1, 'basePack': 'sp_sky-recoil-sodium-fix-mc26.3.zip', 'baseSHA256': BASE_SHA,
              'pack': PACK, 'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data),
              'changedExistingFiles': sorted(changed), 'addedFiles': [], 'removedFiles': [],
              'unchangedEntries': len(before) - len(changed), 'existingAudioPreserved': True,
              'shaderValidation': {'checks': {'allShadersByteIdenticalToValidatedBase': True}},
              'panelBehavior': 'Front sky, transparent tinted glass rear, single front-facing sky quad'}
    (HERE / PACK).write_bytes(data)
    preserve(STAGE / PACK, data)
    (STAGE / 'build-report.json').write_bytes(encoded(report))
    for name, content in patches.items():
        preserve(STAGE / 'overrides' / name, content)
    for name in ['native-controls.json', 'prepare_sky.py', 'sodium_patch.py', 'transport.py', 'panel_models.py', 'validate_shaders.py', 'release.py', 'README.md']:
        preserve(STAGE / name, (HERE / name).read_bytes())
    (STAGE / 'build.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(report, indent=2))


def transport():
    release = module('panel_back_release', HERE / 'release.py')
    release.HERE, release.BASE_PIN = STAGE, STAGE / 'base-pin.json'
    release.SOURCE = ROOT / 'sky-recoil-sodium-fix-publication'
    release.CHECKOUT = ROOT / 'sky-panels-one-way-publication'
    release.PARENT, release.BASE_SHA = PARENT, BASE_SHA
    release.BRANCH, release.PACK = 'codex/star-program-sky-panels-one-way', PACK
    release.PREFIX = 'compatibility/sky-panels-one-way/'
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
    require(current['sha256'] == BASE_SHA and original == (STAGE / 'base-pin.json').read_bytes(), 'Current pack pin changed')
    preserve(GAME / 'config/backups/resource-pack-before-one-way-panels.json', original)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'].update(manifestFile=release.MANIFEST, manifestSha256=verified['manifestSha256'], panelRearTransparent=True)
    current['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    temporary = CONFIG.with_suffix('.one-way-panels.json')
    preserve(temporary, encoded(current))
    require(CONFIG.read_bytes() == original, 'Pack pin changed before update')
    temporary.replace(CONFIG)
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
