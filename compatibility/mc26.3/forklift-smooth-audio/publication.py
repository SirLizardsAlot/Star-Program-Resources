"""Prepare and stage the reviewed smooth hydraulic audio pack locally.

This recipe has no publication or runtime-pinning command. The exact staged
payload must be reviewed before a separate authorized publication step.
"""
import argparse
from copy import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import importlib.util

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack'
PREFIX = 'compatibility/mc26.3/forklift-smooth-audio/'
MANIFEST_PATH = PREFIX + 'manifest.json'
PARENT = '16f3a12c682f4ee88a96b0c51f9ffb4af5014b60'
BASE_SHA = 'bbd89b85b7c0f1f87f42cf55fc78ed02cd68323f83737ce10efdf7b149703ecd'
PROJECT_ID = 'c2090ff7-7646-43f5-a2c5-7398d88f4487'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


previous = module('forklift_smooth_previous_publication', GAME / 'tools/forklift-mast-fix-publication.py')
c, audio = previous.c, previous.audio
c.SOURCE = ROOT / 'forklift-mast-fix-publication'
c.CHECKOUT = ROOT / 'forklift-smooth-audio-publication'
c.BASE = ROOT / 'sp_forklift-mast-fix-mc26.3.zip'
c.PACK = ROOT / 'sp_forklift-smooth-audio-mc26.3.zip'
c.REPORT = c.PACK.with_suffix('.report.json')
c.UPLOAD = ROOT / 'upload-report-forklift-smooth-audio.json'
c.PARENT, c.PARENT_SHA256 = PARENT, BASE_SHA
c.BRANCH = 'codex/star-program-forklift-smooth-audio'

SOUND_MAP = 'assets/star_program_forklift/sounds.json'
AUDIO_MANIFEST = 'compatibility/forklift-audio/manifest.json'
CREDITS = 'credits/forklift-audio.txt'
MOVE = 'assets/star_program_forklift/sounds/lift/move.ogg'
ADDED = {'assets/star_program_forklift/sounds/lift/loop.ogg',
         'assets/star_program_forklift/sounds/lift/release.ogg'}
CHANGED = {SOUND_MAP, AUDIO_MANIFEST, CREDITS}
ALIASES = {f'lift.move.{channel}' for channel in range(1, 9)}
SOURCE_FILE = 'compatibility/mc26.3/forklift-mast-fix/audio/source/nuckan-forklift-hydraulics-hq.mp3'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reviewed_overlay():
    require(c.digest(c.BASE.read_bytes()) == BASE_SHA, 'Pinned full base pack changed')
    files, manifest = audio.overlay_files()
    require(set(files) == ADDED | CHANGED | {MOVE}, 'Unexpected forklift audio overlay paths')
    require(manifest['version'] == 2 and manifest['namespace'] == 'star_program_forklift'
            and manifest['sounds']['lift.loop']['channelCount'] == 8
            and manifest['sounds']['lift.loop']['durationMs'] == 1200
            and manifest['sounds']['lift.release']['durationMs'] == 180
            and manifest['source']['license'] == 'CC0-1.0', 'Expected the reviewed v2 mono hydraulic loop')
    with ZipFile(c.BASE) as base:
        before = json.loads(base.read(SOUND_MAP))
        after = json.loads(files[SOUND_MAP])
        require(set(after) == set(before) | ALIASES | {'lift.release'}, 'Append exactly eight channels and one release event')
        require(all(after[key] == value for key, value in before.items()), 'Existing sound registrations changed')
        original = json.loads(base.read(AUDIO_MANIFEST))
        require(manifest['source'] == original['source']
                and manifest['sounds']['lift.move'] == original['sounds']['lift.move']
                and files[MOVE] == base.read(MOVE), 'Original recording, source attribution or short clip changed')
    source = c.git(c.SOURCE, 'show', PARENT + ':' + SOURCE_FILE, raw=True)
    require(c.digest(source) == manifest['source']['sha256'], 'Recorded source differs from the reviewed base commit')
    return files, manifest


def validate_archive(data, files):
    require(c.digest(c.BASE.read_bytes()) == BASE_SHA, 'Pinned base archive changed')
    require(len(data) <= c.LIMIT, 'The final full pack exceeds forty MiB')
    with ZipFile(c.BASE) as old, ZipFile(BytesIO(data)) as new:
        before, after = old.namelist(), new.namelist()
        require(len(before) == len(set(before)) == 2595
                and len(after) == len(set(after)) == 2597, 'Unexpected archive membership or duplicate paths')
        require(set(after) == set(before) | ADDED and not set(before) & ADDED
                and old.comment == new.comment, 'Archive entries or comment changed')
        require(old.testzip() is None and new.testzip() is None, 'ZIP CRC failure')
        changed = sorted(name for name in before if old.read(name) != new.read(name))
        require(set(changed) == CHANGED, 'Only the sound map, audio manifest and credits may change')
        for name in before:
            require(new.read(name) == files.get(name, old.read(name)), 'Unexpected existing pack bytes: ' + name)
        for name in ADDED:
            require(new.read(name) == files[name], 'New audio differs from reviewed bytes: ' + name)
        old_audio = [name for name in before if name.endswith('.ogg')]
        require(len(old_audio) == 103 and sum(name.endswith('.ogg') for name in after) == 105,
                'Preserve all 103 old clips and add exactly two recordings')
        require(all(old.read(name) == new.read(name) for name in old_audio), 'Existing audio bytes changed')
        require(old.read('pack.mcmeta') == new.read('pack.mcmeta')
                and json.loads(new.read('pack.mcmeta'))['pack']['min_format'] == [97, 1]
                and json.loads(new.read('pack.mcmeta'))['pack']['max_format'] == [97, 1],
                'Keep the Minecraft 26.3 metadata byte-identical')
        return changed


def make_manifest(manifest):
    return {'version': 1, 'projectId': PROJECT_ID, 'targetMinecraft': '26.3', 'resourceFormat': [97, 1],
            'revision': 'smooth-forklift-hydraulics', 'baseCommit': PARENT, 'basePack': c.BASE.name,
            'baseSHA256': BASE_SHA, 'packFile': c.PACK.name,
            'audioManifestFile': AUDIO_MANIFEST,
            'audioManifestSha256': c.digest(c.json_bytes(manifest)),
            'forkliftAudio': manifest, 'existingSourceFile': SOURCE_FILE,
            'sourceCommit': PARENT, 'addedFiles': sorted(ADDED), 'changedExistingFiles': sorted(CHANGED),
            'removedFiles': [], 'existingAudioClipsByteIdentical': 103,
            'soundEventsAdded': sorted('star_program_forklift:' + name for name in ALIASES | {'lift.release'})}


def build():
    config_bytes = c.CONFIG.read_bytes()
    config = json.loads(config_bytes)
    c.assert_parent(config)
    files, audio_manifest = reviewed_overlay()
    output = BytesIO()
    with ZipFile(c.BASE) as old, ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=9) as new:
        new.comment = old.comment
        for info in old.infolist():
            new.writestr(copy(info), files.get(info.filename, old.read(info.filename)))
        for name in sorted(ADDED):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            new.writestr(info, files[name], compresslevel=9)
    data = output.getvalue()
    changed = validate_archive(data, files)
    manifest = make_manifest(audio_manifest)
    report = {'version': 1, 'basePack': c.BASE.name, 'baseURL': config['url'], 'baseCommit': PARENT,
              'baseSHA256': BASE_SHA, 'sha1': hashlib.sha1(data).hexdigest(), 'sha256': c.digest(data),
              'gitBlob': c.blob_hash(data), 'size': len(data), 'sizeLimitBytes': c.LIMIT,
              'remainingBytes': c.LIMIT - len(data), 'existingAssetCount': 2595,
              'existingEntriesByteIdentical': 2592, 'existingAudioClipsVerified': 103,
              'newAudioClips': 2, 'addedFiles': sorted(ADDED), 'removedFiles': [],
              'changedExistingFiles': changed, 'manifestSha256': c.digest(c.json_bytes(manifest)),
              'forkliftAudio': audio_manifest, 'publicationManifest': manifest,
              'recipeSha256': c.digest(Path(__file__).read_bytes()),
              'assets': [{'file': name, 'sha256': c.digest(value), 'size': len(value)}
                         for name, value in sorted(files.items())],
              'checks': {'originalSoundEventsUnchanged': True, 'eightChannelsAndOneReleaseAdded': True,
                         'all103ExistingAudioClipsByteIdentical': True, 'allModelsAndTexturesByteIdentical': True,
                         'onlyThreeReviewedExistingEntriesChanged': True, 'packMetadataByteIdentical': True,
                         'zipMembershipAndCRCs': True, 'recordedCC0SourceUnchanged': True,
                         'under40MiB': True}, 'runtimePinUnchanged': True, 'published': False}
    c.preserve(c.PACK, data)
    c.preserve(c.REPORT, c.json_bytes(report))
    require(c.CONFIG.read_bytes() == config_bytes, 'Runtime pin changed during local preparation')
    return report


def prepared():
    c.assert_parent(c.read_json(c.CONFIG))
    files, audio_manifest = reviewed_overlay()
    report, data = c.read_json(c.REPORT), c.PACK.read_bytes()
    manifest = make_manifest(audio_manifest)
    changed = validate_archive(data, files)
    require(report['sha256'] == c.digest(data) and report['sha1'] == hashlib.sha1(data).hexdigest()
            and report['gitBlob'] == c.blob_hash(data) and report['size'] == len(data)
            and report['baseSHA256'] == BASE_SHA and report['baseCommit'] == PARENT
            and report['changedExistingFiles'] == changed and report['addedFiles'] == sorted(ADDED)
            and report['removedFiles'] == [] and report['forkliftAudio'] == audio_manifest
            and report['publicationManifest'] == manifest
            and report['manifestSha256'] == c.digest(c.json_bytes(manifest))
            and report['recipeSha256'] == c.digest(Path(__file__).read_bytes())
            and all(value is True for value in report['checks'].values()), 'Prepared audio archive or evidence changed')
    payload = {c.PACK.name: data, PREFIX + 'pack-build-report.json': c.REPORT.read_bytes(),
               MANIFEST_PATH: c.json_bytes(manifest), PREFIX + 'publication.py': Path(__file__).read_bytes(),
               PREFIX + 'audio/manifest.json': files[AUDIO_MANIFEST],
               PREFIX + 'audio/credits.txt': files[CREDITS],
               PREFIX + 'audio/build.py': (GAME / 'tools/forklift-audio-loop.py').read_bytes(),
               PREFIX + 'audio/analysis.json': (audio.ROOT / 'loop-candidate/analysis.json').read_bytes()}
    return report, manifest, payload


c.prepared = prepared


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'prepared', 'stage'])
    args = parser.parse_args()
    result = {'build': build, 'prepared': lambda: prepared()[0], 'stage': c.stage}[args.action]()
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ['forkliftAudio', 'publicationManifest', 'assets']}, indent=2))
