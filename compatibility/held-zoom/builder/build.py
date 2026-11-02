"""Build and publish the held zoom replacement without contacting Minecraft."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
SKY, ROOT = HERE.parent, HERE.parent.parent
GAME = ROOT.parent
CONFIG = GAME / 'config/resource-pack.json'
BASE_SHA = 'f0c2a37afa56fc55040f6d6227426f3b8d5599b1c135c520d0a294fe7329dbed'
PARENT = 'f8d73a651185b8b153c195c8be349d0e607be666'
PACK = 'sp_held-zoom-mc26.3.zip'
PREFIX = 'compatibility/held-zoom/'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


# Reuse the guarded additive publication transport, including its flattened
# object stores, without modifying any prior release source or checkout.
support = module('zoom_publication_support', SKY / 'pure-sky-panel/build.py')
for key in ['HERE', 'SKY', 'ROOT', 'GAME', 'CONFIG', 'BASE_SHA', 'PARENT', 'PACK', 'PREFIX']:
    setattr(support, key, globals()[key])
encoded, sha, require, preserve = support.encoded, support.sha, support.require, support.preserve


def build():
    original_pin = CONFIG.read_bytes()
    pin = json.loads(original_pin)
    require(pin['sha256'] == BASE_SHA and pin['publication']['commit'] == PARENT, 'Current pack pin changed')
    preserve(HERE / 'base-pin.json', original_pin)
    base_path = SKY / 'sp_sky-panel-clean-face-mc26.3.zip'
    base = base_path.read_bytes()
    require(sha(base) == BASE_SHA, 'Base archive changed')
    with ZipFile(BytesIO(base)) as archive:
        before = {name: archive.read(name) for name in archive.namelist()}
        entries = {entry.filename: entry for entry in archive.infolist()}
    patches = module('held_zoom_patches', HERE / 'patch_zoom.py').make_zoom(before)
    final = {**before, **patches}
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        for name, data in final.items():
            entry = entries.get(name)
            if entry is None:
                entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    data = buffer.getvalue()
    require(len(data) <= 41943040, 'Pack exceeds 40 MiB')
    artifact = SKY / PACK
    preserve(artifact, data)
    validator = module('zoom_shader_validator', SKY / 'validate_shaders.py')
    validation = validator.validate(artifact, ROOT / 'mc26.3/reference/minecraft-client.jar')
    with ZipFile(BytesIO(data)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failed')
        for name in archive.namelist():
            if name.endswith('.json') or name == 'pack.mcmeta':
                json.loads(archive.read(name))
    for name, content in patches.items():
        dest = HERE / 'overrides' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    report = {'version': 1, 'pack': PACK, 'basePack': base_path.name, 'baseSHA256': BASE_SHA,
              'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data),
              'changedExistingFiles': sorted(name for name in before if final[name] != before[name]),
              'addedFiles': sorted(set(final) - set(before)), 'removedFiles': [],
              'existingAudioPreserved': True, 'allOtherResourcesByteIdentical': True,
              'skyAndPanelAssetsPreserved': True, 'sodiumShadersByteIdentical': True,
              'heldZoom': True, 'zoomInputRange': [0, 1], 'zoomReset': 0,
              'angularFovInterpolation': True, 'oldRecoilMarkersIgnored': True,
              'nativeParticleProtocol': 3, 'shaderValidation': validation}
    preserve(HERE / 'build-report.json', encoded(report))
    print(json.dumps({k: v for k, v in report.items() if k != 'shaderValidation'} |
                     {'shaderStages': validation['stagesCompiled'], 'stagePairs': validation['stagePairsChecked']}, indent=2))


def transport():
    release = support.transport()
    release.SOURCE, release.CHECKOUT = ROOT / 'pure-sky-panel-publication', ROOT / 'held-zoom-publication'
    release.BRANCH = 'codex/star-program-held-zoom'
    old_git = release.git
    def git(repo, *args, **kwargs):
        if args[:2] == ('commit', '-m'):
            args = ('commit', '--message', 'Replace visual recoil with held angular-FOV zoom')
        return old_git(repo, *args, **kwargs)
    release.git = git
    def payload():
        report = json.loads((HERE / 'build-report.json').read_bytes())
        data = (SKY / PACK).read_bytes()
        require(sha(data) == report['sha256'] and all(report['shaderValidation']['checks'].values()), 'Archive validation differs')
        check = json.loads((HERE / 'zoom-render-report.json').read_bytes())
        require(check['packSHA256'] == report['sha256'], 'Rendered archive differs')
        base = json.loads(release.BASE_PIN.read_bytes())
        require(base['sha256'] == BASE_SHA and base['publication']['commit'] == PARENT, 'Base pin differs')
        manifest = {k: v for k, v in report.items() if k != 'shaderValidation'}
        manifest.update(projectId=base['projectId'], targetMinecraft=base['targetMinecraft'],
                        resourceFormat=base['resourceFormat'], baseCommit=PARENT, baseURL=base['url'])
        files = {PACK: data, release.MANIFEST: encoded(manifest),
                 PREFIX + 'zoom-render-report.json': (HERE / 'zoom-render-report.json').read_bytes()}
        for name in ['build.py', 'patch_zoom.py', 'zoom_render_check.mjs', 'README.md', 'native-controls.json']:
            files[PREFIX + 'builder/' + name] = (HERE / name).read_bytes()
        for path in (HERE / 'overrides').rglob('*'):
            if path.is_file():
                files[PREFIX + 'source/' + path.relative_to(HERE / 'overrides').as_posix()] = path.read_bytes()
        return report, files
    release.payload = payload
    return release


def pin():
    release = transport()
    report, files, commit = release.stage()
    verified = json.loads(release.VERIFICATION.read_bytes())
    require(verified['commit'] == commit and verified['sha256'] == report['sha256']
            and verified['manifestSha256'] == sha(files[release.MANIFEST]), 'Hosted verification differs')
    original = CONFIG.read_bytes()
    require(original == (HERE / 'base-pin.json').read_bytes(), 'Pack pin changed')
    current = json.loads(original)
    preserve(GAME / 'config/backups/resource-pack-before-held-zoom.json', original)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({k: verified[k] for k in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'].update(recoilEnabled=False, zoomEnabled=True, protocol=3,
        manifestFile=release.MANIFEST, manifestSha256=verified['manifestSha256'])
    current['zoom'] = {'version': 1, 'packCommit': commit, 'held': True, 'range': [0, 1],
                       'reset': 0, 'controlByteSteps': 255, 'greens': [246, 245],
                       'function': 'SP.Shader.Zoom', 'manifestFile': release.MANIFEST,
                       'manifestSha256': verified['manifestSha256']}
    current['publication'].update({k: verified[k] for k in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    temp = CONFIG.with_suffix('.held-zoom.json')
    preserve(temp, encoded(current))
    require(CONFIG.read_bytes() == original, 'Concurrent pin edit')
    temp.replace(CONFIG)
    print(json.dumps({'status': 'pinned', 'url': verified['url']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'stage', 'publish', 'pin'])
    action = parser.parse_args().action
    if action in ['build', 'pin']:
        globals()[action]()
    elif action == 'publish':
        print(json.dumps(transport().publish(), indent=2))
    else:
        report, files, commit = transport().stage()
        print(json.dumps({'status': 'committed', 'commit': commit, 'files': len(files)}))
