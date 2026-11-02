"""Remove only the sky-facing glass quads and publish the scoped pack update.

No Minecraft connection or game-code transfer is performed.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
SKY, ROOT = HERE.parent, HERE.parent.parent
GAME = ROOT.parent
CONFIG = GAME / 'config/resource-pack.json'
BASE_SHA = 'f934eea1eaae516f3dd7f6a5e2b36952c92bd6f0a7268d03a9f9b629e02411e6'
PARENT = 'a6a996b3df3e1ba66c6db0e9b74f805dd6a1b9ef'
PACK = 'sp_sky-panel-clean-face-mc26.3.zip'
PREFIX = 'compatibility/sky-panel-clean-face/'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


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
    current = CONFIG.read_bytes()
    pin = json.loads(current)
    require(pin['sha256'] == BASE_SHA and pin['publication']['commit'] == PARENT, 'Current pack pin changed')
    preserve(HERE / 'base-pin.json', current)
    base_path = SKY / 'sp_sky-cold-load-mc26.3.zip'
    base = base_path.read_bytes()
    require(sha(base) == BASE_SHA, 'Base pack changed')
    models = module('clean_panel_models', SKY / 'panel_models.py').make_panels()
    buffer = BytesIO()
    with ZipFile(BytesIO(base)) as original, ZipFile(buffer, 'w') as output:
        for name, data in models.items():
            old = json.loads(original.read(name))
            new = json.loads(data)
            sky_faces = set(old['elements'][1]['faces'])
            require(len(sky_faces) == 1, 'Expected exactly one existing sky face')
            expected = json.loads(original.read(name))
            removed = expected['elements'][0]['faces'].pop(next(iter(sky_faces)))
            require(removed['texture'] == '#glass' and new == expected,
                    'Only the glass quad facing the sky may change: ' + name)
            dest = HERE / 'overrides' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        for entry in original.infolist():
            output.writestr(entry, models.get(entry.filename, original.read(entry.filename)))
    data = buffer.getvalue()
    require(len(data) <= 41943040, 'Resource pack exceeds 40 MiB')
    with ZipFile(BytesIO(base)) as original, ZipFile(BytesIO(data)) as final:
        require(final.testzip() is None, 'Pack CRC failed')
        require(final.namelist() == original.namelist(), 'Resource entry set changed')
        changed = [name for name in original.namelist() if original.read(name) != final.read(name)]
        require(set(changed) == set(models), 'Unexpected resource change')
        # This scoped model change inherits the exact shader resources already
        # validated in the base pack, including all bindings and data textures.
        shader_names = [name for name in original.namelist()
                        if name.endswith(('.fsh', '.vsh', '.glsl'))]
        require(all(final.read(name) == original.read(name) for name in shader_names), 'Shader bytes changed')
    previous_report = json.loads((SKY / 'cold-load/build-report.json').read_bytes())
    require(previous_report['sha256'] == BASE_SHA and all(previous_report['shaderValidation']['checks'].values()),
            'Base validation changed')
    report = {'version': 1, 'basePack': base_path.name, 'baseSHA256': BASE_SHA,
              'pack': PACK, 'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data),
              'changedExistingFiles': sorted(changed), 'addedFiles': [], 'removedFiles': [],
              'existingAudioPreserved': True, 'allOtherResourcesByteIdentical': True,
              'skyOrientationPreserved': True, 'skyFaceGlassOverlayRemoved': True,
              'oppositeFaceAndEdgesPreserved': True,
              'shaderFilesByteIdentical': len(shader_names),
              'inheritedShaderValidationFromPackSHA256': BASE_SHA,
              'shaderValidation': previous_report['shaderValidation']}
    preserve(SKY / PACK, data)
    preserve(HERE / 'build-report.json', encoded(report))
    print(json.dumps({k: v for k, v in report.items() if k != 'shaderValidation'}, indent=2))


def transport():
    release = module('clean_panel_release', SKY / 'release.py')
    release.HERE, release.BASE_PIN = HERE, HERE / 'base-pin.json'
    release.SOURCE, release.CHECKOUT = ROOT / 'sky-cold-load-publication', ROOT / 'pure-sky-panel-publication'
    release.PARENT, release.BASE_SHA = PARENT, BASE_SHA
    release.BRANCH, release.PACK = 'codex/star-program-pure-sky-panel', PACK
    release.PREFIX, release.MANIFEST = PREFIX, PREFIX + 'manifest.json'
    release.VERIFICATION = HERE / 'publication-verification.json'
    original_git = release.git
    configured = False
    def git(repo, *args, **kwargs):
        nonlocal configured
        if repo == release.CHECKOUT and not configured:
            # Earlier additive publications share object stores. Reference
            # each store directly rather than exceeding Git's nesting limit.
            pending, stores = [release.SOURCE / '.git/objects'], []
            while pending:
                store = pending.pop(0).resolve()
                if store in stores:
                    continue
                require(store.is_relative_to(ROOT.resolve()) and store.is_dir(),
                        'Unexpected shared publication object store')
                stores.append(store)
                linked = store / 'info/alternates'
                if linked.exists():
                    for line in linked.read_text().splitlines():
                        if line.strip():
                            target = Path(line.strip())
                            pending.append(target if target.is_absolute() else store / target)
            (repo / '.git/objects/info/alternates').write_bytes(
                ('\n'.join(store.as_posix() for store in stores) + '\n').encode())
            original_git(repo, 'config', 'core.autocrlf', 'false')
            configured = True
        if args[:2] == ('commit', '-m'):
            args = ('commit', '-m', 'Remove glass overlay from the sky-facing panel side')
        return original_git(repo, *args, **kwargs)
    release.git = git
    def payload():
        report = json.loads((HERE / 'build-report.json').read_bytes())
        data = (SKY / PACK).read_bytes()
        base = json.loads(release.BASE_PIN.read_bytes())
        require(base['sha256'] == BASE_SHA and base['publication']['commit'] == PARENT, 'Base pin changed')
        require(sha(data) == report['sha256'] and report['allOtherResourcesByteIdentical'], 'Pack changed')
        check = json.loads((HERE / 'panel-render-report.json').read_bytes())
        require(check['packSHA256'] == report['sha256'] and check['nativeTrapdoorStates'] == 16
                and check['skyMaximumDifferenceFromSkyOnly'] == 0
                and check['glassMaximumDifferenceFromGlassOnly'] == 0, 'Model rendering check missing')
        manifest = {k: v for k, v in report.items() if k != 'shaderValidation'}
        manifest.update(projectId=base['projectId'], targetMinecraft=base['targetMinecraft'],
                        resourceFormat=base['resourceFormat'], baseCommit=PARENT, baseURL=base['url'])
        files = {PACK: data, release.MANIFEST: encoded(manifest),
                 PREFIX + 'panel-render-report.json': (HERE / 'panel-render-report.json').read_bytes(),
                 PREFIX + 'builder/build.py': Path(__file__).read_bytes(),
                 PREFIX + 'builder/panel_models.py': (SKY / 'panel_models.py').read_bytes(),
                 PREFIX + 'builder/panel_models_test.py': (SKY / 'panel_models_test.py').read_bytes(),
                 PREFIX + 'builder/panel_render_check.mjs': (HERE / 'panel_render_check.mjs').read_bytes()}
        for path in (HERE / 'overrides').rglob('*.json'):
            files[PREFIX + 'source/' + path.relative_to(HERE / 'overrides').as_posix()] = path.read_bytes()
        return report, files
    release.payload = payload
    return release


def pin():
    release = transport()
    report, files, commit = release.stage()
    verification = json.loads(release.VERIFICATION.read_bytes())
    require(verification['commit'] == commit and verification['sha256'] == report['sha256']
            and verification['manifestSha256'] == sha(files[release.MANIFEST]), 'Hosted bytes differ')
    original = CONFIG.read_bytes()
    require(original == (HERE / 'base-pin.json').read_bytes(), 'Current pack pin changed')
    current = json.loads(original)
    preserve(GAME / 'config/backups/resource-pack-before-pure-sky-panel.json', original)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({k: verification[k] for k in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'].update(panelSkyGlassOverlay=False, panelSkyFace='mounting',
        panelSeeThroughFace='exposed', manifestFile=release.MANIFEST, manifestSha256=verification['manifestSha256'])
    current['publication'].update({k: verification[k] for k in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    temporary = CONFIG.with_suffix('.pure-sky-panel.json')
    preserve(temporary, encoded(current))
    require(CONFIG.read_bytes() == original, 'Concurrent pack pin edit')
    temporary.replace(CONFIG)
    print(json.dumps({'status': 'pinned', 'url': verification['url']}, indent=2))


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
