"""Publish the verified pack on its own branch, then advance the local pack pin.

No Minecraft connection or game-code transfer is performed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GAME = ROOT.parent
CONFIG = GAME / 'config/resource-pack.json'
BASE_PIN = HERE / 'base-pin.json'
SOURCE = ROOT / 'main-menu-publication'
CHECKOUT = ROOT / 'sky-recoil-publication'
PARENT = '07f63538ebdd8f301736d2c4ca92c21ab80ebc11'
BASE_SHA = 'f9f36c225616efa4005ac39e460b3a8c30656654bf9733993c67fba177dbc22d'
BRANCH = 'codex/star-program-sky-recoil'
REMOTE = 'https://github.com/SirLizardsAlot/Star-Program-Resources.git'
RAW = 'https://raw.githubusercontent.com/SirLizardsAlot/Star-Program-Resources'
PACK = 'sp_sky-recoil-mc26.3.zip'
PREFIX = 'compatibility/sky-recoil/'
MANIFEST = PREFIX + 'manifest.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def read(path):
    return json.loads(path.read_bytes())


def preserve(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'Preserve differing existing file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def git(repo, *args, raw=False, check=True):
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'safe.directory=' + repo.as_posix(),
                             '-C', str(repo), *args], capture_output=True)
    if not check:
        return result
    require(result.returncode == 0, result.stderr.decode(errors='replace'))
    return result.stdout if raw else result.stdout.decode().strip()


def payload():
    report = read(HERE / 'build-report.json')
    data = (HERE / PACK).read_bytes()
    require(report['baseSHA256'] == BASE_SHA and report['sha256'] == sha(data)
            and report['existingAudioPreserved'] and len(data) <= 41943040
            and all(report['shaderValidation']['checks'].values()), 'Pack does not match successful validation')
    pin_bytes = CONFIG.read_bytes()
    current = json.loads(pin_bytes)
    if current['sha256'] == BASE_SHA:
        require(current['publication']['commit'] == PARENT, 'Unexpected parent publication')
        preserve(BASE_PIN, pin_bytes)
    else:
        require(current['sha256'] == report['sha256'] and current.get('skyRecoil', {}).get('version') == 1,
                'Preserve unrelated current pack pin')
    base = read(BASE_PIN)
    require(base['sha256'] == BASE_SHA and base['publication']['commit'] == PARENT, 'Base pin changed')
    manifest = {key: value for key, value in report.items() if key != 'shaderValidation'}
    manifest.update({'projectId': base['projectId'], 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
                     'baseCommit': PARENT, 'baseURL': base['url'],
                     'shaderChecks': {key: value for key, value in report['shaderValidation'].items()
                                      if key not in ['stages', 'pairs', 'postPassBindings']},
                     'nativeControls': read(HERE / 'native-controls.json')})
    result = {PACK: data, MANIFEST: encoded(manifest), PREFIX + 'native-controls.json': (HERE / 'native-controls.json').read_bytes()}
    for path in (HERE / 'overrides').rglob('*'):
        if path.is_file():
            result[PREFIX + 'source/' + path.relative_to(HERE / 'overrides').as_posix()] = path.read_bytes()
    for name in ['build.py', 'prepare_sky.py', 'sodium_patch.py', 'transport.py', 'validate_shaders.py', 'release.py', 'README.md']:
        result[PREFIX + 'builder/' + name] = (HERE / name).read_bytes()
    return report, result


def stage():
    report, files = payload()
    require(git(SOURCE, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected source repository')
    source_before = (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', raw=True))
    require(git(SOURCE, 'rev-parse', PARENT + '^{commit}') == PARENT, 'Base commit missing')
    if not (CHECKOUT / '.git').exists():
        require(not CHECKOUT.exists() or not any(CHECKOUT.iterdir()), 'Preserve existing publication directory')
        init = subprocess.run(['git', 'init', str(CHECKOUT)], capture_output=True)
        require(init.returncode == 0, init.stderr.decode(errors='replace'))
        preserve(CHECKOUT / '.git/objects/info/alternates', ((SOURCE / '.git/objects').resolve().as_posix() + '\n').encode())
        git(CHECKOUT, 'remote', 'add', 'origin', REMOTE)
        git(CHECKOUT, 'checkout', '-b', BRANCH, PARENT)
        for key in ['user.name', 'user.email']:
            value = git(SOURCE, 'config', '--get', key, check=False)
            if value.returncode == 0:
                git(CHECKOUT, 'config', key, value.stdout.decode().strip())
    require(git(CHECKOUT, 'branch', '--show-current') == BRANCH
            and git(CHECKOUT, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected publication checkout')
    if git(CHECKOUT, 'rev-parse', 'HEAD') == PARENT:
        changes = git(CHECKOUT, 'status', '--porcelain=v1', '-z', raw=True).decode().split('\0')
        require(all(not row or row[3:] in files for row in changes), 'Preserve unrelated checkout changes')
        for name, content in files.items():
            preserve(CHECKOUT / name, content)
        git(CHECKOUT, 'add', '--', *files)
        git(CHECKOUT, 'commit', '-m', 'Add particle-controlled Sky Block and visual pitch yaw recoil')
    commit = git(CHECKOUT, 'rev-parse', 'HEAD')
    require(git(CHECKOUT, 'rev-list', '--count', PARENT + '..' + commit) == '1', 'Expected one additive commit')
    changed = git(CHECKOUT, 'diff', '--name-only', '-z', PARENT, commit, raw=True).decode().strip('\0').split('\0')
    require(set(changed) == set(files) and not git(CHECKOUT, 'status', '--porcelain=v1'), 'Publication scope changed')
    for name, content in files.items():
        require(git(CHECKOUT, 'show', commit + ':' + name, raw=True) == content, 'Committed file changed: ' + name)
    require(source_before == (git(SOURCE, 'rev-parse', 'HEAD'), git(SOURCE, 'status', '--porcelain=v1', '-z', raw=True)),
            'Original publication checkout changed')
    return report, files, commit


def publish():
    report, files, commit = stage()
    remote = git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH)
    require(not remote or remote.split()[0] == commit, 'Preserve different remote branch')
    if not remote:
        git(CHECKOUT, 'push', '--set-upstream', 'origin', BRANCH + ':refs/heads/' + BRANCH)
    require(git(CHECKOUT, 'ls-remote', '--heads', 'origin', BRANCH).split()[0] == commit, 'Published ref differs')
    verified_files = [PACK, MANIFEST]
    for name in verified_files:
        request = urllib.request.Request(f'{RAW}/{commit}/{name}', headers={'User-Agent': 'STAR-Program-Sky-Recoil'})
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.status == 200 and response.read(41943041) == files[name], 'Immutable hosted bytes differ: ' + name)
    result = {'version': 1, 'status': 'published', 'branch': BRANCH, 'commit': commit,
              'url': f'{RAW}/{commit}/{PACK}', 'sha1': report['sha1'], 'sha256': report['sha256'],
              'size': report['size'], 'manifestFile': MANIFEST, 'manifestSha256': sha(files[MANIFEST]),
              'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'verifiedFiles': verified_files}
    verification = HERE / 'publication-verification.json'
    if verification.exists():
        prior = read(verification)
        require(all(prior.get(key) == value for key, value in result.items() if key != 'verifiedAt'), 'Preserve different hosted verification')
        result = prior
    else:
        preserve(verification, encoded(result))
    return result


def pin():
    verified = read(HERE / 'publication-verification.json')
    report, files, commit = stage()
    require(verified['commit'] == commit and verified['sha256'] == report['sha256']
            and verified['manifestSha256'] == sha(files[MANIFEST]), 'Hosted verification changed')
    before = CONFIG.read_bytes()
    current = json.loads(before)
    if current['sha256'] == report['sha256']:
        require(current['url'] == verified['url'], 'Inconsistent existing pin')
        return {'status': 'already-pinned', 'commit': commit, 'url': current['url']}
    require(current['sha256'] == BASE_SHA and before == BASE_PIN.read_bytes(), 'Current pack pin changed')
    preserve(GAME / 'config/backups/resource-pack-before-sky-recoil.json', before)
    current['previousUrls'] = list(dict.fromkeys([*current.get('previousUrls', []), current['url']]))
    current.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    for value in current.values():
        if isinstance(value, dict) and value.get('packCommit') == PARENT:
            value['packCommit'] = commit
    current['skyRecoil'] = {'version': 1, 'packCommit': commit, 'manifestFile': MANIFEST,
                           'manifestSha256': verified['manifestSha256'], 'protocol': 2,
                           'skyBlock': 'minecraft:red_glazed_terracotta', 'channels': [4, 5, 6, 7]}
    current['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'verifiedAt', 'manifestFile', 'manifestSha256']})
    blob = hashlib.sha1(f'blob {report["size"]}\0'.encode() + files[PACK]).hexdigest()
    current['publication'].update(gitBlob=blob, verifiedBlob=blob)
    temporary = CONFIG.with_suffix('.sky-recoil-pinning.json')
    preserve(temporary, encoded(current))
    require(CONFIG.read_bytes() == before, 'Resource configuration changed before atomic update')
    temporary.replace(CONFIG)
    return {'status': 'pinned', 'commit': commit, 'url': verified['url'], 'sha256': report['sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'publish', 'pin'])
    action = parser.parse_args().action
    value = stage() if action == 'stage' else globals()[action]()
    print(json.dumps({'status': 'committed', 'commit': value[2], 'files': len(value[1])} if action == 'stage' else value, indent=2))
