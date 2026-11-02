"""Build and release the smaller sky programs and corrected one-way panels.

No Minecraft process is started or contacted. The pack is derived from the
current immutable pin and preserves unrelated assets and all sound bytes.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import time
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
if HERE.name == 'release':
    HERE = HERE.parent
SKY = HERE.parent
ROOT, GAME = SKY.parent, SKY.parent.parent
STAGE = HERE / 'release'
CONFIG = GAME / 'config/resource-pack.json'
BASE_SHA = 'c9b21a204b8a8b9c6e6e7e2597fb38115750f7ed3651098ce7ac3ecea1fa00f2'
PARENT = 'a38adf5e25543e63e8a6db1abfc8dbc69797e183'
PACK = 'sp_sky-cold-load-mc26.3.zip'
CLIENT = ROOT / 'mc26.3/reference/minecraft-client.jar'


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
    pin = json.loads(CONFIG.read_bytes())
    require(pin['sha256'] == BASE_SHA and pin['publication']['commit'] == PARENT, 'Current pack pin changed')
    preserve(STAGE / 'base-pin.json', CONFIG.read_bytes())
    base_path = SKY / 'sp_sky-panels-one-way-mc26.3.zip'
    original = base_path.read_bytes()
    require(sha(original) == BASE_SHA, 'Pinned archive changed')
    with ZipFile(BytesIO(original)) as archive:
        before = {name: archive.read(name) for name in archive.namelist()}
        entries = {entry.filename: entry for entry in archive.infolist()}
    patches = module('cold_data', HERE / 'prepare_data.py').make_data()
    patches.update(module('cold_shaders', HERE / 'patch_shaders.py').make_shaders(before))
    merged = {**before, **patches}
    patches.update(module('cold_camera', HERE / 'patch_camera.py').make_camera(merged))
    models = module('cold_panels', SKY / 'panel_models.py').make_panels()
    patches.update(models)
    cube_name = 'assets/dfsky/models/block/sky_block.json'
    cube = json.loads(before[cube_name])
    for element in cube['elements']:
        for face in element['faces'].values():
            if face['texture'] == '#sky':
                face['uv'] = [0, 0, 1, 2]
    patches[cube_name] = encoded(cube)
    post_name = 'assets/minecraft/post_effect/end_of_frame.json'
    post = json.loads(before[post_name])
    effect = next(row for row in post['passes'] if row['fragment_shader'] == 'shader_selector:post/shader')
    require(not any(row.get('sampler_name') == 'SkyData' for row in effect['inputs']), 'Unexpected existing SkyData binding')
    effect['inputs'].append({'sampler_name': 'SkyData', 'location': 'dfsky:sky_data',
                             'width': 256, 'height': 128, 'bilinear': False})
    patches[post_name] = encoded(post)
    final = {**before, **patches}
    for name, content in patches.items():
        target = HERE / 'overrides' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, content in final.items():
            if name in entries:
                archive.writestr(entries[name], content)
            else:
                from zipfile import ZipInfo, ZIP_DEFLATED
                entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, content)
    data = output.getvalue()
    require(len(data) <= 41943040, 'Pack exceeds 40 MiB limit')
    artifact = SKY / PACK
    artifact.write_bytes(data)
    validator = module('cold_validator', SKY / 'validate_shaders.py')
    started = time.perf_counter()
    validation = validator.validate(artifact, CLIENT)
    compilation_seconds = time.perf_counter() - started
    with ZipFile(BytesIO(data)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failure')
        for name in archive.namelist():
            if name.endswith('.json') or name == 'pack.mcmeta':
                json.loads(archive.read(name))
        require(archive.read('pack.mcmeta') == before['pack.mcmeta'], 'Version/Sodium compatibility metadata changed')
        require(all(archive.read(name) == content for name, content in before.items() if name.endswith('.ogg')),
                'Existing audio changed')
    changed = sorted(name for name in before if final[name] != before[name])
    added = sorted(set(final) - set(before))
    base_validation = json.loads((SKY / 'sodium-fix-release/build-report.json').read_bytes())['shaderValidation']
    old_stages = {(row['file'], json.dumps(row['defines'], sort_keys=True)): row for row in base_validation['stages']}
    reductions = []
    for row in validation['stages']:
        key = row['file'], json.dumps(row['defines'], sort_keys=True)
        old = old_stages.get(key)
        if old and row['file'].endswith('.fsh') and row['spirvBytes'] < old['spirvBytes']:
            reductions.append({'file': row['file'], 'defines': row['defines'],
                               'beforeBytes': old['spirvBytes'], 'afterBytes': row['spirvBytes']})
    report = {'version': 1, 'basePack': base_path.name, 'baseSHA256': BASE_SHA, 'pack': PACK,
              'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data),
              'changedExistingFiles': changed, 'addedFiles': added, 'removedFiles': [],
              'unchangedEntries': len(before) - len(changed), 'existingAudioPreserved': True,
              'shaderValidation': validation, 'cpuCompilationSeconds': compilation_seconds,
              'smallerFragmentStages': reductions,
              'dataTexture': [256, 128], 'skyImageDataPreserved': True,
              'viewBobbingUsesFullProjection': True, 'markerMetadataCarriersPerSet': 1,
              'markerQuadPixelsBeforePerSet': 5824, 'markerQuadPixelsAfterPerSet': 326,
              'skyPanelSideReversed': True, 'affectedClientCrashVerified': False}
    (HERE / 'build-report.json').write_bytes(encoded(report))
    (STAGE / 'build-report.json').write_bytes(encoded(report))
    (STAGE / PACK).write_bytes(data)
    for name, content in patches.items():
        target = STAGE / 'overrides' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name in ['native-controls.json', 'prepare_sky.py', 'sodium_patch.py', 'transport.py', 'panel_models.py', 'validate_shaders.py', 'release.py', 'README.md']:
        (STAGE / name).write_bytes((SKY / name).read_bytes())
    (STAGE / 'build.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({key: value for key, value in report.items() if key not in ['shaderValidation', 'smallerFragmentStages']}
                     | {'stagesCompiled': validation['stagesCompiled'], 'stagePairs': validation['stagePairsChecked'],
                        'smallerStages': len(reductions)}, indent=2))


def transport():
    release = module('cold_release_transport', SKY / 'release.py')
    release.HERE, release.BASE_PIN = STAGE, STAGE / 'base-pin.json'
    release.SOURCE = ROOT / 'sky-panels-one-way-publication'
    release.CHECKOUT = ROOT / 'sky-cold-load-publication'
    release.PARENT, release.BASE_SHA = PARENT, BASE_SHA
    release.BRANCH, release.PACK = 'codex/star-program-sky-cold-load', PACK
    release.PREFIX = 'compatibility/sky-cold-load/'
    release.MANIFEST = release.PREFIX + 'manifest.json'
    release.VERIFICATION = STAGE / 'publication-verification.json'
    original_payload = release.payload
    original_git = release.git
    configured_git = False
    def release_git(repo, *args, **kwargs):
        nonlocal configured_git
        if repo == release.CHECKOUT and not configured_git:
            original_git(repo, 'config', 'core.autocrlf', 'false')
            configured_git = True
        if args[:2] == ('commit', '-m'):
            args = ('commit', '-m', 'Reduce sky compilation and transparency work and correct panel orientation')
        return original_git(repo, *args, **kwargs)
    release.git = release_git
    def full_payload():
        report, files = original_payload()
        sodium = json.loads((HERE / 'sodium-compat-check-report.json').read_bytes())
        require(sodium['packSHA256'] == report['sha256'] and sodium['shaderStagesCompiled'] == 40
                and sodium['stagePairsChecked'] == 20 and sodium['warnings'] == 0,
                'Exact final archive Sodium validation is missing')
        markers = json.loads((HERE / 'marker-check-report.json').read_bytes())
        require(markers['packSHA256'] == report['sha256'] and markers['stagesCompiled'] == 20
                and markers['warnings'] == 0 and all(markers['checks'].values()),
                'Exact final archive marker validation is missing')
        for name in ['prepare_data.py', 'patch_shaders.py', 'patch_camera.py',
                     'test_data.py', 'render_check.mjs', 'bobbing_check.mjs', 'sodium_compat_check.py', 'marker_check.py']:
            files[release.PREFIX + 'builder/' + name] = (HERE / name).read_bytes()
        for name in ['data-report.json', 'render-check-report.json', 'bobbing-check-report.json',
                     'marker-check-report.json', 'sodium-compat-check-report.json', 'panel-orientation-report.json']:
            if (HERE / name).exists():
                files[release.PREFIX + name] = (HERE / name).read_bytes()
        return report, files
    release.payload = full_payload
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
    preserve(GAME / 'config/backups/resource-pack-before-sky-cold-load.json', original)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'].update(manifestFile=release.MANIFEST, manifestSha256=verified['manifestSha256'],
        coldLoadTextures=True, viewBobbingCompatible=True, metadataCarrierCount=1,
        panelRearTransparent=False, panelSkyFace='mounting', panelSeeThroughFace='exposed')
    current['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    temporary = CONFIG.with_suffix('.cold-load.json')
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
