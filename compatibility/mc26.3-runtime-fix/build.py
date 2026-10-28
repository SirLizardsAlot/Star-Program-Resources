"""Publish the minimal 26.3 post-effect runtime binding correction."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re

GAME = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mc263_runtime_publication_base', GAME / 'tools/mc26.3-pack.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.c

m.MIGRATION = m.ROOT / 'mc26.3-runtime-fix'
m.OVERRIDES = m.MIGRATION / 'overrides'
m.BASE = m.ROOT / 'sp_mc26.3.zip'
m.PACK = m.ROOT / 'sp_mc26.3-runtime-fix.zip'
m.REPORT = m.PACK.with_suffix('.report.json')
m.BASE_SHA256 = 'd7eb3e3493474443004efe90849e8eb375bde8d5b9d4de5ce5fdf604a2d29d2b'
m.PARENT = 'dc78e56b1c45f1b717cd3cad18a760bf0be18747'
m.PREFIX = 'compatibility/mc26.3-runtime-fix/'
m.__file__ = __file__
c.SOURCE = m.ROOT / 'mc26.3-publication'
c.CHECKOUT = m.ROOT / 'mc26.3-runtime-fix-publication'
c.BASE, c.PACK, c.REPORT = m.BASE, m.PACK, m.REPORT
c.UPLOAD = m.ROOT / 'upload-report-mc26.3-runtime-fix.json'
c.PARENT, c.PARENT_SHA256 = m.PARENT, m.BASE_SHA256
c.BRANCH = 'codex/star-program-mc26.3-runtime-fix'


def inputs():
    m.require(c.digest(m.BASE.read_bytes()) == m.BASE_SHA256, 'Active 26.3 base ZIP changed')
    m.require(m.hashlib.sha1(m.CLIENT.read_bytes()).hexdigest() == m.CLIENT_SHA1, 'Official client changed')
    notes = {'runtime-fix.json': c.read_json(m.MIGRATION / 'runtime-fix.json')}
    patches = {path.relative_to(m.OVERRIDES).as_posix(): path.read_bytes()
               for path in m.OVERRIDES.rglob('*') if path.is_file()}
    expected = set(notes['runtime-fix.json']['changedFiles'])
    m.require(set(patches) == expected and patches, 'Runtime fix differs from reviewed resource list')
    m.require(all(name.startswith('assets/shader_selector/shaders/') and '..' not in Path(name).parts
                  for name in patches), 'Runtime fix must only alter reviewed shader resources')
    return patches, set(), notes


m.inputs = inputs


def commit_local():
    c.assert_parent(c.read_json(c.CONFIG))
    report, _, payload = m.prepared()
    c.check_checkout()
    if c.git(c.CHECKOUT, 'rev-parse', 'HEAD') == m.PARENT:
        m.require(set(c.changes()) == {('A ', name) for name in payload}, 'Unexpected staged files')
        for name, content in payload.items():
            m.require(c.git(c.CHECKOUT, 'show', ':' + name, raw=True) == content, 'Staged bytes changed')
        c.git(c.CHECKOUT, 'commit', '-m', 'Fix unbound sampler in the Minecraft 26.3 post effect')
    return {'status': 'committed', 'commit': c.check_commit(payload), 'branch': c.BRANCH,
            'sha256': report['sha256'], 'published': False}


def pin(commit=None):
    report, manifest, commit, url = c.publication_context(commit)
    verified = c.read_json(c.UPLOAD)
    expected = {'status': 'published', 'commit': commit, 'branch': c.BRANCH, 'url': url,
                'httpStatus': 200, 'sha1': report['sha1'], 'sha256': report['sha256'],
                'size': report['size'], 'gitBlob': report['gitBlob'], 'matchesLocalArtifact': True}
    m.require(all(verified.get(key) == value for key, value in expected.items()) and verified.get('verifiedAt'),
              'Verify hosted runtime-fix ZIP before pinning')
    before = c.CONFIG.read_bytes()
    config = json.loads(before)
    if config.get('url') == url:
        m.require(config['sha256'] == report['sha256'], 'Inconsistent runtime fix pin')
        return {'status': 'already-pinned', 'url': url}
    c.assert_parent(config)
    m.require(config['projectId'] == m.PROJECT_ID and config['targetMinecraft'] == '26.3', 'Unexpected project or version')
    backup = c.CONFIG.parent / 'backups/resource-pack-before-mc26.3-runtime-fix-d7eb3e349347.json'
    c.preserve(backup, before)
    config['previousUrls'] = list(dict.fromkeys([*config.get('previousUrls', []), config['url']]))
    config.update({key: verified[key] for key in ['url', 'sha1', 'sha256', 'size']})
    config['runtimeFix26_3'] = {**manifest, 'manifestFile': m.PREFIX + 'manifest.json', 'packCommit': commit}
    config['publication'].update({key: verified[key] for key in ['status', 'branch', 'commit', 'gitBlob', 'verifiedAt']})
    config['publication']['verifiedBlob'] = verified['gitBlob']
    changed = {'url', 'sha1', 'sha256', 'size', 'previousUrls', 'runtimeFix26_3', 'publication'}
    m.require(all(config[key] == value for key, value in json.loads(before).items() if key not in changed),
              'Unrelated resource configuration changed')
    temporary = c.CONFIG.with_suffix('.mc26.3-runtime-fix-pinning.json')
    c.preserve(temporary, c.json_bytes(config))
    m.require(c.CONFIG.read_bytes() == before, 'Resource pin changed during preparation')
    temporary.replace(c.CONFIG)
    return {'status': 'pinned', 'url': url, 'sha256': report['sha256'], 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'prepared', 'stage', 'commit', 'publish', 'verify', 'pin'])
    parser.add_argument('commit', nargs='?')
    args = parser.parse_args()
    if args.commit and (args.action not in ['verify', 'pin'] or not re.fullmatch('[a-f0-9]{40}', args.commit)):
        parser.error('Only verify and pin accept an immutable commit')
    actions = {'build': m.build, 'prepared': lambda: m.prepared()[1], 'stage': c.stage, 'commit': commit_local,
               'publish': c.publish, 'verify': lambda: c.verify(args.commit), 'pin': lambda: pin(args.commit)}
    print(json.dumps(actions[args.action](), indent=2))
