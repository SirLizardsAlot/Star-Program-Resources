"""Prepare and publish ESRI's impact and closure shaders over its accepted pack."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import urllib.request
from zipfile import ZipFile

sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = Path(__file__).resolve()
release = load('esri_release', TOOL.with_name('esri-pack.py'))
require, sha, encoded, read, preserve = release.require, release.sha, release.encoded, release.read, release.preserve
CONFIG, RAW = release.CONFIG, release.RAW
BRANCH = 'codex/star-program-esri-impact'
PARENT = 'd658ff1a8fc45ec870043a60d736814c32362c23'
BASE_SHA256 = 'a388d70354390e6c573795d407927655f0193f5c5ea4f097c939f74cc7d07090'
BASE_SHA1 = 'bb1f551d5953db881d9b0d98b0662e4bf3551b1f'
BASE_SIZE = 28_509_698
BASE = release.LOCAL_PACK
HERE = release.HERE / 'impact-revision'
CHECKOUT = HERE / 'publication'
BACKUP = CONFIG.parent / 'backups/resource-pack-before-esri-impact-a388d7035439.json'
PACK = release.PACK
LOCAL_PACK = HERE / BASE.name
PREPARED_PIN = HERE / 'resource-pack.prepared.json'
PREFIX = 'compatibility/esri/impact-revision/'
MANIFEST = PREFIX + 'publication-manifest.json'
SHADER_SOURCE = release.HERE / 'impact_shader.py'
WORMHOLE = release.ROOT / 'wormhole-marker'
PORTAL_SHADERS = {
    'assets/minecraft/shaders/core/text.fsh': '6788d00c361350fc7808ef3d8ef392a9568a4166cb4374e58177e4fb7ab147bb',
    'assets/minecraft/shaders/core/text.vsh': '80a6cb13b707ffe0464649793b0ecc7769c7c46fd63cab1f07ab4aa3b798ce4d',
    'assets/star_wormhole/shaders/include/tunnel.glsl': '9249d9a3bcee01dfe55c5aa7b91fbe5eff88fcd1e33ad28b445d1d15867ee3f2',
}
BASE_URL = f'{RAW}/{PARENT}/{PACK}'


def git(*args, **kwargs):
    return release.git(CHECKOUT, *args, **kwargs)


def assert_base(config):
    require(config.get('projectId') == release.PROJECT and config.get('targetMinecraft') == '26.3'
            and config.get('resourceFormat') == [97, 1], 'Wrong project or Minecraft format')
    require(config.get('url') == BASE_URL and config.get('sha256') == BASE_SHA256
            and config.get('sha1') == BASE_SHA1 and config.get('size') == BASE_SIZE
            and config.get('publication', {}).get('commit') == PARENT
            and config.get('esri', {}).get('packCommit') == PARENT, 'Accepted ESRI pack pin changed')


def remote_revision():
    rows = git('ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH).splitlines()
    require(len(rows) <= 1, 'Expected one matching ESRI impact branch at most')
    return rows[0].split()[0] if rows else None


def initialize_checkout():
    if CHECKOUT.exists():
        return
    CHECKOUT.mkdir()
    git('init', '--quiet')
    git('remote', 'add', 'origin', release.REMOTE)
    require(remote_revision() is None, 'Preserve the existing remote ESRI impact branch')
    git('config', 'core.autocrlf', 'false')
    git('config', 'remote.origin.promisor', 'true')
    git('config', 'remote.origin.partialclonefilter', 'blob:none')
    git('fetch', '--depth=1', '--filter=blob:none', 'origin', PARENT)
    git('sparse-checkout', 'set', '--no-cone', '/' + PACK, '/' + PREFIX)
    git('checkout', '-b', BRANCH, PARENT)
    for name in ['user.name', 'user.email']:
        value = release.git(release.CHECKOUT, 'config', '--get', name, check=False)
        if value.returncode == 0 and value.stdout.strip():
            git('config', name, value.stdout.decode().strip())


def checkout_head():
    require(git('remote', 'get-url', 'origin') == release.REMOTE
            and git('branch', '--show-current') == BRANCH, 'Wrong ESRI publication checkout')
    require(git('status', '--porcelain=v1', '-z', '--untracked-files=all', raw=True) == b'',
            'Preserve changed ESRI publication checkout')
    return git('rev-parse', 'HEAD')


def validate(pack, path):
    compiler_module = load('esri_impact_shaderc', release.ROOT / 'mc26.3-runtime-fix/validate_shaders.py')
    marker = load('esri_impact_marker', WORMHOLE / 'validate.py')
    with ZipFile(BytesIO(pack)) as archive, ZipFile(compiler_module.DEFAULT_CLIENT) as client:
        version = json.loads(client.read('version.json'))
        require(version['id'] == '26.3' and version['pack_version']['resource_major'] == 97,
                'Expected the official Minecraft 26.3 client')
        compiler = compiler_module.Compiler(archive, client)
        try:
            stages = []
            effect = 'assets/minecraft/post_effect/end_of_frame.json'
            post_id = 'shader_selector:post/shader'
            passes = json.loads(archive.read(effect))['passes']
            matches = [(i, row) for i, row in enumerate(passes) if row['fragment_shader'] == post_id]
            require(len(matches) == 1, 'Expected one existing end-of-frame shader pass')
            index, post_pass = matches[0]
            for defines in [{}, {'DEPTH_ZERO_TO_ONE': '1'}]:
                vertex = compiler.compile(path.removesuffix('.fsh') + '.vsh', defines)
                fragment = compiler.compile(path, defines)
                compiler_module.stage_pair(vertex, fragment)
                compiler_module.post_bindings(effect, index, post_pass, vertex, fragment)
                stages.append({'program': post_id, 'defines': defines, 'vertex': vertex, 'fragment': fragment})
            text = 'assets/minecraft/shaders/core/text'
            for defines in marker.text_variants():
                vertex = compiler.compile(text + '.vsh', defines)
                fragment = compiler.compile(text + '.fsh', defines)
                compiler_module.stage_pair(vertex, fragment)
                native = compiler.compile(text + '.vsh', defines, vanilla=True)
                require(all(native['interface']['inputs'].get(location) == item
                            for location, item in vertex['interface']['inputs'].items()),
                        'Core text vertex inputs differ from the native pipeline')
                stages.append({'program': 'core/text', 'defines': defines, 'vertex': vertex, 'fragment': fragment})
        finally:
            compiler.close()
    return {'compiler': 'Minecraft 26.3 ShaderC', 'packSHA256': sha(pack),
            'stagePairsChecked': len(stages), 'stages': stages}


def prepare():
    before = CONFIG.read_bytes()
    assert_base(json.loads(before))
    base = BASE.read_bytes()
    require(len(base) == BASE_SIZE and sha(base) == BASE_SHA256
            and hashlib.sha1(base).hexdigest() == BASE_SHA1, 'Accepted ESRI archive differs')
    source = SHADER_SOURCE.read_bytes()
    patches = {path: (WORMHOLE / 'src' / path).read_bytes() for path in PORTAL_SHADERS}
    shader = load('esri_impact_revision_shader', SHADER_SOURCE)
    with ZipFile(BytesIO(base)) as archive:
        old = archive.read(shader.SHADER_PATH)
        count = len(archive.namelist())
        accepted = {path: archive.read(path) for path in patches}
    require(all(sha(accepted[path]) == PORTAL_SHADERS[path] and data != accepted[path]
                for path, data in patches.items()), 'Expected only the three reviewed portal shader replacements')
    new = shader.upgrade_shader(old.decode('utf-8')).encode('utf-8')
    require(new != old and shader.upgrade_shader(new.decode('utf-8')).encode('utf-8') == new,
            'Expected one idempotent ESRI shader revision')
    accepted[shader.SHADER_PATH], patches[shader.SHADER_PATH] = old, new
    overlay = load('esri_impact_zip_overlay', TOOL.with_name('diphone-tts-pack.py'))
    pack = overlay.overlay_archive(base, patches)
    before_comment, before_directory = overlay.central_entries(base)
    after_comment, after_directory = overlay.central_entries(pack)
    require(before_comment == after_comment and list(before_directory) == list(after_directory),
            'ESRI archive directory membership or order changed')
    for name in before_directory.keys() - patches.keys():
        before_record, after_record = before_directory[name]['central'], after_directory[name]['central']
        require(before_record[:42] == after_record[:42] and before_record[46:] == after_record[46:],
                'Unrelated ZIP directory record changed beyond its local offset: ' + name)
    validation = validate(pack, shader.SHADER_PATH)
    validation_bytes = encoded(validation)
    report = {
        'version': 1, 'projectId': release.PROJECT, 'targetMinecraft': '26.3',
        'resourceFormat': [97, 1], 'baseCommit': PARENT, 'baseURL': BASE_URL,
        'baseSHA256': BASE_SHA256, 'baseSize': BASE_SIZE, 'baseConfigSHA256': sha(before),
        'packFile': PACK, 'sha1': hashlib.sha1(pack).hexdigest(), 'sha256': sha(pack),
        'size': len(pack), 'sizeLimitBytes': release.LIMIT,
        'remainingBytes': release.LIMIT - len(pack), 'preservedEntries': count - len(patches),
        'changedEntries': {path: {'beforeSHA256': sha(accepted[path]), 'afterSHA256': sha(data)}
                           for path, data in patches.items()},
        'addedEntries': [], 'removedEntries': [], 'unrelatedCompressedRecordsByteIdentical': True,
        'unrelatedDirectoryRecordsPreservedExceptOffsets': True,
        'builderSHA256': sha(TOOL.read_bytes()), 'shaderSourceSHA256': sha(source),
        'shaderValidationSHA256': sha(validation_bytes),
    }
    require(CONFIG.read_bytes() == before and BASE.read_bytes() == base and SHADER_SOURCE.read_bytes() == source
            and all((WORMHOLE / 'src' / path).read_bytes() == patches[path] for path in PORTAL_SHADERS),
            'Concurrent ESRI pack input changed')
    for name, data in {'base-pin.json': before, LOCAL_PACK.name: pack, 'build-report.json': encoded(report),
                       'shader-validation.json': validation_bytes}.items():
        preserve(HERE / name, data)
    return report


def payload():
    report = read(HERE / 'build-report.json')
    pack, tool, source, validation = (path.read_bytes() for path in
        (LOCAL_PACK, TOOL, SHADER_SOURCE, HERE / 'shader-validation.json'))
    require(len(pack) == report['size'] <= release.LIMIT and sha(pack) == report['sha256']
            and hashlib.sha1(pack).hexdigest() == report['sha1']
            and sha(tool) == report['builderSHA256'] and sha(source) == report['shaderSourceSHA256']
            and sha(validation) == report['shaderValidationSHA256']
            and json.loads(validation)['packSHA256'] == report['sha256']
            and sha((HERE / 'base-pin.json').read_bytes()) == report['baseConfigSHA256'],
            'Prepared impact revision differs from validated bytes')
    require(all(sha((WORMHOLE / 'src' / path).read_bytes()) == report['changedEntries'][path]['afterSHA256']
                for path in PORTAL_SHADERS), 'Prepared portal shader sources changed')
    files = {PACK: pack, MANIFEST: encoded(report), PREFIX + 'builder/esri-impact-pack.py': tool,
             PREFIX + 'builder/impact_shader.py': source, PREFIX + 'shader-validation.json': validation}
    return report, files


def committed(files):
    revision = checkout_head()
    require(git('rev-list', '--parents', '-n', '1', revision).split() == [revision, PARENT],
            'Impact release must be one commit from the accepted ESRI revision')
    changed = git('diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files) and all(git('show', revision + ':' + name, raw=True) == data
            for name, data in files.items()), 'Committed ESRI revision differs from the prepared release')
    return revision


def commit():
    assert_base(read(CONFIG))
    require(CONFIG.read_bytes() == (HERE / 'base-pin.json').read_bytes(), 'Active ESRI pack configuration changed')
    report, files = payload()
    initialize_checkout()
    if checkout_head() == PARENT:
        require(remote_revision() is None, 'Preserve existing remote ESRI impact branch')
        require(sha((CHECKOUT / PACK).read_bytes()) == BASE_SHA256
                and all(not (CHECKOUT / name).exists() for name in files if name != PACK),
                'Preserve existing ESRI checkout assets')
        for name, data in files.items():
            if name == PACK:
                (CHECKOUT / name).write_bytes(data)
            else:
                preserve(CHECKOUT / name, data)
        git('add', '--', *files)
        git('commit', '-m', 'Upgrade the ESRI discharge impact shader')
    return {'status': 'committed', 'commit': committed(files), 'size': report['size']}


def publish():
    assert_base(read(CONFIG))
    _, files = payload()
    revision = committed(files)
    remote = remote_revision()
    require(remote in (None, revision), 'Preserve changed remote ESRI impact branch')
    if remote is None:
        git('push', 'origin', f'{revision}:refs/heads/{BRANCH}')
    require(remote_revision() == revision, 'Remote ESRI impact revision differs')
    return {'status': 'pushed', 'commit': revision, 'branch': BRANCH}


def verify():
    report, files = payload()
    revision = committed(files)
    require(remote_revision() == revision, 'Publish the exact ESRI impact revision first')
    for name, data in files.items():
        request = urllib.request.Request(f'{RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-ESRI'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(release.LIMIT + 1) == data,
                    'Immutable hosted ESRI artifact differs: ' + name)
    result = {'version': 1, 'status': 'published', 'commit': revision, 'branch': BRANCH,
              'url': f'{RAW}/{revision}/{PACK}', 'sha1': report['sha1'], 'sha256': report['sha256'],
              'size': report['size'], 'gitBlob': git('rev-parse', f'{revision}:{PACK}'),
              'manifestFile': MANIFEST, 'manifestSha256': sha(files[MANIFEST]),
              'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'httpStatus': 200, 'matchesLocalArtifact': True, 'remoteFilesVerified': list(files)}
    destination = HERE / 'publication-verification.json'
    if destination.exists():
        previous = read(destination)
        require(all(previous.get(key) == value for key, value in result.items() if key != 'verifiedAt'),
                'Preserve differing hosted verification')
        return previous
    preserve(destination, encoded(result))
    return result


def prepared_config():
    report, files = payload()
    revision = committed(files)
    verified = read(HERE / 'publication-verification.json')
    require(verified.get('status') == 'published' and verified.get('matchesLocalArtifact') is True
            and verified.get('commit') == revision and verified.get('url') == f'{RAW}/{revision}/{PACK}'
            and verified.get('manifestSha256') == sha(files[MANIFEST])
            and all(verified.get(key) == report[key] for key in ['sha1', 'sha256', 'size']),
            'Verify the immutable ESRI impact release before pinning')
    base_pin = (HERE / 'base-pin.json').read_bytes()
    config = json.loads(base_pin)
    assert_base(config)
    advanced = []

    def advance(value, prefix=''):
        if isinstance(value, dict):
            for key, child in value.items():
                position = f'{prefix}.{key}' if prefix else key
                if key == 'packCommit' and child == PARENT:
                    value[key] = revision
                    advanced.append(position)
                else:
                    advance(child, position)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                advance(child, f'{prefix}[{index}]')

    advance(config)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), BASE_URL]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['esri']['shaderPublication'] = MANIFEST
    config['publication'].update({key: verified[key] for key in
        ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    return base_pin, encoded(config), advanced, verified


def prepare_pin():
    base_pin, after, _, verified = prepared_config()
    require(CONFIG.read_bytes() in (base_pin, after), 'Preserve changed active resource configuration')
    preserve(PREPARED_PIN, after)
    return {'status': 'prepared', 'url': verified['url'], 'sha256': verified['sha256'],
            'config': str(PREPARED_PIN)}


def pin(preview_path):
    base_pin, after, advanced, verified = prepared_config()
    require(PREPARED_PIN.read_bytes() == after, 'Prepare the verified ESRI impact config first')
    preview_bytes = preview_path.read_bytes()
    preview = json.loads(preview_bytes)
    details = preview.get('esriImpactPresentation', {})
    resource = details.get('resourcePack', {})
    require(preview.get('projectId') == release.PROJECT and preview.get('installed') is False
            and preview.get('editorVerified') is True and details.get('previousPackUrl') == BASE_URL
            and resource.get('url') == verified['url'] and resource.get('sha256') == verified['sha256'],
            'Prepare the matching scoped native ESRI impact preview before pinning')
    before = CONFIG.read_bytes()
    require(before in (base_pin, after), 'Preserve changed active resource configuration')
    preserve(BACKUP, base_pin)
    if before != after:
        temporary = CONFIG.with_name(CONFIG.name + '.esri-impact-pinning')
        with temporary.open('xb') as target:
            target.write(after)
            target.flush()
            os.fsync(target.fileno())
        require(CONFIG.read_bytes() == before and preview_path.read_bytes() == preview_bytes,
                'Concurrent resource or native preview edit preserved')
        os.replace(temporary, CONFIG)
    return {'status': 'pinned', 'commit': verified['commit'], 'url': verified['url'],
            'sha256': verified['sha256'], 'size': verified['size'], 'backup': str(BACKUP),
            'advancedContainment': advanced}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'commit', 'publish', 'verify', 'prepare-pin', 'pin'])
    parser.add_argument('--native-preview', type=Path)
    args = parser.parse_args()
    if bool(args.native_preview) != (args.action == 'pin'):
        parser.error('Pin requires the matching --native-preview path')
    result = pin(args.native_preview) if args.native_preview else globals()[args.action.replace('-', '_')]()
    print(json.dumps(result, indent=2))
