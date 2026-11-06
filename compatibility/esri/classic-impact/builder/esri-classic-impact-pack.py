"""Stage the classic ESRI impact shader on the currently accepted combined pack."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import BytesIO
import json
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
impact = load('classic_impact_tools', TOOL.with_name('esri-impact-pack.py'))
release = impact.release
require, sha, encoded, read, preserve = release.require, release.sha, release.encoded, release.read, release.preserve
overlay = load('classic_impact_overlay', TOOL.with_name('diphone-tts-pack.py'))
PARENT = 'f898da17c82da4d6c1288ebc7d3336aa1d5f450a'
BASE_SHA256 = '34255c33f89afb44721d867dae178b77d1d4543731ea3fafa56867156dc254fb'
BASE_SHA1 = '29f511f917e1bec179e2061f05c4bab39f8423a4'
BASE_SIZE = 28_514_902
BRANCH = 'codex/star-program-esri-classic-impact'
STAGE = release.GAME / 'staging'
HERE = STAGE / 'esri-classic-impact-pack'
CHECKOUT = HERE / 'publication'
PACK = release.PACK
BASE = STAGE / 'esri-rift-pack-combined' / PACK
BASE_URL = f'{release.RAW}/{PARENT}/{PACK}'
PREFIX = 'compatibility/esri/classic-impact/'
MANIFEST = PREFIX + 'publication-manifest.json'
SHADER = 'assets/shader_selector/shaders/post/shader.fsh'
BEGIN, END = b'// STAR_ESRI_IMPACT_BEGIN', b'// STAR_ESRI_IMPACT_END'
CURRENT_HELPER = '5a9bcfe89893eee7ea64a564b25ef007b94a2f76c5e9a25e4e0a6a66fa331018'
CLASSIC_HELPER = '8b92b22e5f6a14d33e6ff69ea33ed26064648cc0eb983982413897bbfa4ce995'
SURROUNDING = '221099bb75bba43ff195b36afc624d2c89b4a0ecd98484daf795e649b22fa71d'


def assert_base(config):
    require(config.get('projectId') == release.PROJECT and config.get('targetMinecraft') == '26.3'
            and config.get('resourceFormat') == [97, 1] and config.get('url') == BASE_URL
            and config.get('sha256') == BASE_SHA256 and config.get('sha1') == BASE_SHA1
            and config.get('size') == BASE_SIZE and config.get('publication', {}).get('commit') == PARENT
            and config.get('esri', {}).get('packCommit') == PARENT, 'Accepted combined ESRI pin changed')


def split_shader(data, expected):
    require(data.count(BEGIN) == data.count(END) == 1, 'Unexpected ESRI impact helper boundaries')
    start, stop = data.index(BEGIN), data.index(END) + len(END)
    before, helper, after = data[:start], data[start:stop], data[stop:]
    require(start < stop and sha(helper) == expected and sha(before + after) == SURROUNDING,
            'Accepted ESRI helper or surrounding shader changed')
    return before, helper, after


def prepare():
    config = release.CONFIG.read_bytes()
    assert_base(json.loads(config))
    base, classic = BASE.read_bytes(), impact.BASE.read_bytes()
    require(len(base) == BASE_SIZE and sha(base) == BASE_SHA256
            and hashlib.sha1(base).hexdigest() == BASE_SHA1 and sha(classic) == impact.BASE_SHA256,
            'Exact source archives differ')
    with ZipFile(BytesIO(base)) as archive, ZipFile(BytesIO(classic)) as donor:
        current = archive.read(SHADER)
        before, _, after = split_shader(current, CURRENT_HELPER)
        _, old_helper, _ = split_shader(donor.read(SHADER), CLASSIC_HELPER)
    revised = before + old_helper + after
    pack = overlay.overlay_archive(base, {SHADER: revised})
    before_comment, before_directory = overlay.central_entries(base)
    after_comment, after_directory = overlay.central_entries(pack)
    require(before_comment == after_comment and list(before_directory) == list(after_directory),
            'Archive membership or order changed')
    for name in before_directory.keys() - {SHADER}:
        old_record, new_record = before_directory[name]['central'], after_directory[name]['central']
        require(old_record[:42] == new_record[:42] and old_record[46:] == new_record[46:],
                'Unrelated archive directory record changed: ' + name)
    validation = encoded(impact.validate(pack, SHADER))
    report = {'version': 1, 'projectId': release.PROJECT, 'targetMinecraft': '26.3',
              'resourceFormat': [97, 1], 'baseCommit': PARENT, 'baseURL': BASE_URL,
              'baseSHA256': BASE_SHA256, 'baseSize': BASE_SIZE, 'baseConfigSHA256': sha(config),
              'classicDonorCommit': impact.PARENT, 'classicDonorSHA256': impact.BASE_SHA256,
              'packFile': PACK, 'sha1': hashlib.sha1(pack).hexdigest(), 'sha256': sha(pack),
              'size': len(pack), 'sizeLimitBytes': release.LIMIT, 'manifestFile': MANIFEST,
              'changedEntries': {SHADER: {'beforeSHA256': sha(current), 'afterSHA256': sha(revised)}},
              'preservedEntries': len(before_directory) - 1, 'addedEntries': [], 'removedEntries': [],
              'unrelatedCompressedRecordsByteIdentical': True,
              'shaderValidationSHA256': sha(validation), 'builderSHA256': sha(TOOL.read_bytes())}
    require(release.CONFIG.read_bytes() == config, 'Preserve changed active resource configuration')
    for name, data in {'base-pin.json': config, PACK: pack, 'build-report.json': encoded(report),
                       'shader-validation.json': validation}.items():
        preserve(HERE / name, data)
    return report


def git(*args, **kwargs):
    return release.git(CHECKOUT, *args, **kwargs)


def publish():
    config_bytes = (HERE / 'base-pin.json').read_bytes()
    config = json.loads(config_bytes)
    assert_base(config)
    require(release.CONFIG.read_bytes() == config_bytes, 'Preserve changed active resource configuration')
    report = read(HERE / 'build-report.json')
    pack, validation, tool = (HERE / PACK).read_bytes(), (HERE / 'shader-validation.json').read_bytes(), TOOL.read_bytes()
    require(len(pack) == report['size'] <= release.LIMIT and sha(pack) == report['sha256']
            and hashlib.sha1(pack).hexdigest() == report['sha1'] and sha(validation) == report['shaderValidationSHA256']
            and sha(tool) == report['builderSHA256'] and sha(config_bytes) == report['baseConfigSHA256']
            and json.loads(validation)['packSHA256'] == report['sha256'], 'Prepared resources differ from their validation')
    files = {PACK: pack, MANIFEST: encoded(report), PREFIX + 'builder/esri-classic-impact-pack.py': tool,
             PREFIX + 'shader-validation.json': validation}
    require(git('remote', 'get-url', 'origin') == release.REMOTE and git('branch', '--show-current') == BRANCH
            and not git('status', '--porcelain=v1', '--untracked-files=all'), 'Wrong or changed publication checkout')
    ref = 'refs/heads/' + BRANCH
    remote = git('ls-remote', '--heads', 'origin', ref)
    if git('rev-parse', 'HEAD') == PARENT:
        require(not remote and sha((CHECKOUT / PACK).read_bytes()) == BASE_SHA256, 'Preserve changed publication base')
        (CHECKOUT / PACK).write_bytes(pack)
        for name, data in files.items():
            if name != PACK:
                preserve(CHECKOUT / name, data)
        git('add', '--', *files)
        git('commit', '-m', 'Restore classic ESRI impact frames')
    revision = git('rev-parse', 'HEAD')
    require(git('rev-list', '--parents', '-n', '1', revision).split() == [revision, PARENT], 'Unexpected publication parent')
    changed = git('diff', '--name-only', '-z', PARENT, revision, raw=True).decode().rstrip('\0').split('\0')
    require(set(changed) == set(files) and all(git('show', revision + ':' + name, raw=True) == data
            for name, data in files.items()), 'Publication revision differs from prepared resources')
    require(not remote or remote.split() == [revision, ref], 'Preserve changed remote branch')
    if not remote:
        git('push', 'origin', f'{revision}:{ref}')
    require(git('ls-remote', '--heads', 'origin', ref).split() == [revision, ref], 'Wrong remote publication revision')
    for name, data in files.items():
        request = urllib.request.Request(f'{release.RAW}/{revision}/{name}', headers={'User-Agent': 'STAR-Program-ESRI'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(release.LIMIT + 1) == data, 'Hosted resource differs: ' + name)
    blob = git('rev-parse', f'{revision}:{PACK}')
    verification = {'version': 1, 'status': 'published', 'commit': revision, 'branch': BRANCH,
                    'url': f'{release.RAW}/{revision}/{PACK}', 'gitBlob': blob, 'manifestFile': MANIFEST,
                    'manifestSha256': sha(files[MANIFEST]), 'matchesLocalArtifact': True, 'remoteFilesVerified': list(files),
                    'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    **{key: report[key] for key in ['sha1', 'sha256', 'size']}}
    verification_path = HERE / 'publication-verification.json'
    if verification_path.exists():
        previous = read(verification_path)
        require(all(previous.get(key) == value for key, value in verification.items() if key != 'verifiedAt'),
                'Preserve differing hosted verification')
        verification = previous

    def advance(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'packCommit' and child == PARENT:
                    value[key] = revision
                else:
                    advance(child)
        elif isinstance(value, list):
            for child in value:
                advance(child)

    advance(config)
    config['esri']['shaderPublication'] = MANIFEST
    config['previousUrls'] = list(dict.fromkeys([*config['previousUrls'], BASE_URL]))
    config.update({key: verification[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['publication'].update({key: verification[key] for key in
                                 ['status', 'branch', 'commit', 'gitBlob', 'manifestFile', 'manifestSha256', 'verifiedAt']})
    config['publication']['verifiedBlob'] = blob
    require(release.CONFIG.read_bytes() == config_bytes, 'Preserve changed active resource configuration')
    preserve(verification_path, encoded(verification))
    preserve(HERE / 'resource-pack.prepared.json', encoded(config))
    return verification


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'publish'])
    print(json.dumps(globals()[parser.parse_args().action](), indent=2))
