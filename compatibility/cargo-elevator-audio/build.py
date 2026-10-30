"""Prepare and validate the cargo lift sound overlay and a local full pack.

Reads the pinned 26.3 archive without changing it or the active resource pin.
No portal, publication, Minecraft connection, or code transfer occurs here.
"""
from __future__ import annotations

import argparse
from copy import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import numpy as np

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack/cargo-elevator-audio'
RATE = 32000
NS = 'star_program_cargo'
LIMIT = 41943040
SOURCE = ROOT / 'source/micronin-electric-hoist-hq.mp3'
SOURCE_SHA = 'f8739b978f6afc149286b76e51c9295a62813556766bed29d011894d8c62b180'
PAGE = 'https://freesound.org/people/Micronin/sounds/184888/'
DOWNLOAD = 'https://cdn.freesound.org/previews/184/184888_141342-hq.mp3'
LICENSE = 'https://creativecommons.org/publicdomain/zero/1.0/'
BASE = GAME / 'resource-pack/sp_mc26.3-runtime-fix.zip'
BASE_SHA = '962a4e3191d4acc0bf9bb1da7ff9e9c23d1b50284842ff10e823ef2a65a31133'
PACK = ROOT / 'sp_cargo-elevator-direct-drive-mc26.3.zip'
REPORT = PACK.with_suffix('.report.json')
APPROVED_PREDECESSOR = ROOT / 'sp_cargo-elevator-electric-hoist-mc26.3.zip'
APPROVED_PREDECESSOR_SHA = 'f62821a9320c4f60a43ba1118f0fd88660c547468433a6744f0093d59594fd87'
FROZEN_SOUNDS = {
    'motor.run': '7be63fbe6e871f5079bd9462ca66e09a520a3ff13ae5881b05abbb5a05a24db3',
    'departure.cue': '7e878e8f99dd7ddb7f3e52675ff007c71f2ef847cf18e4bb9da958e23fa06875',
    'arrival.cue': '073d0bca51cf2f3dc613c5c225bc4b478925b1aa9040ea2026209933dce41530',
    'door.opening': '44bdd7a1829913b6926857547d42c6742dc26ce19920f4652a3f348dfc5717b9',
    'door.closing': '8b5b9803ca8e2a8e12c820c07ea6732c9fdc641e8e4f2ed446b3176265b195b7'
}
CONTACTOR = {
    'title': 'Contactor/motor overload relay noises', 'creator': 'tt_runscript',
    'page': 'https://freesound.org/people/tt_runscript/sounds/807384/',
    'downloadUrl': 'https://cdn.freesound.org/previews/807/807384_5365416-hq.mp3',
    'license': 'CC0-1.0', 'licenseUrl': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'file': 'source/siemens-contactor-hq.mp3',
    'sha256': '3cef4579d30352ad16f6f6720a109c011537b17d34c2ecbf27acd220c049d2a1',
    'originalEvidenceFile': 'source/siemens-contactor-807384.html',
    'evidenceFile': 'source/contactor-license.txt'
}
CUES = {
    'departure.cue': {'title': 'Factory Warning Buzzer', 'creator': 'qubodup',
                      'page': 'https://freesound.org/people/qubodup/sounds/832414/',
                      'downloadUrl': 'https://cdn.freesound.org/previews/832/832414_71257-hq.mp3',
                      'license': 'CC0-1.0',
                      'licenseUrl': 'https://creativecommons.org/publicdomain/zero/1.0/',
                      'file': 'source/qubodup-departure-hq.mp3',
                      'sha256': '36b798f34ec06999ff8de1377055516f1ad4b7423733fdc1db2474f0ad7e69aa',
                      'originalEvidenceFile': 'source/departure-832414.html',
                      'evidenceFile': 'source/departure-license.txt'},
    'arrival.cue': {'title': '13622 ready bell ring', 'creator': 'Robinhood76',
                    'page': 'https://freesound.org/people/Robinhood76/sounds/841269/',
                    'downloadUrl': 'https://cdn.freesound.org/previews/841/841269_321967-hq.mp3',
                    'license': 'CC-BY-NC-4.0',
                    'licenseUrl': 'https://creativecommons.org/licenses/by-nc/4.0/',
                    'file': 'source/robinhood-arrival-hq.mp3',
                    'sha256': '2291e8f4fec1dbd68019a802ee7f0e066830aa2f1dcdef4809703087bb8244b0',
                    'originalEvidenceFile': 'source/arrival-841269.html',
                    'evidenceFile': 'source/arrival-license.txt'}
}
VOICES = {
    'door.opening': {'text': 'Stand back! Doors opening.', 'file': 'source/door-opening-matthew.mp3',
                     'sha256': '9344c4dcd8ab0bd7f4b0b6b54428bc38710a1b6c751092ea09f6b85cbc5bb60d',
                     'originalDownloadFilename': 'ttsMP3.com_VoiceText_2026-10-29_22-31-21.mp3'},
    'door.closing': {'text': 'Stand back! Doors closing.', 'file': 'source/door-closing-matthew.mp3',
                     'sha256': '9213374de72e7a0d344fef28a03a554535ad305d4b710bb899bab3c32fa24753',
                     'originalDownloadFilename': 'ttsMP3.com_VoiceText_2026-10-29_22-32-28.mp3'}
}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


audio = module('cargo_audio_io', GAME / 'resource-pack/turbines/build_audio.py')
mp3 = module('cargo_mp3_decoder', GAME / 'resource-pack/lab-audio/audio_io.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def evidence_extract(source):
    original = ROOT / source['originalEvidenceFile']
    html = original.read_text(encoding='utf-8')
    require_url = source['licenseUrl'].replace('https:', '').replace('http:', '')
    if require_url not in html:
        raise ValueError('Missing source license link: ' + source['title'])
    # Public source pages contain third-party service configuration. Publish
    # only the relevant attribution and license evidence, never the raw HTML.
    text = (source['title'] + '\nCreator: ' + source['creator'] + '\n'
            'Primary source: ' + source['page'] + '\n'
            'License: ' + source['license'] + '\n' + source['licenseUrl'] + '\n'
            'License verified from the source page downloaded on 2026-10-29.\n'
            'Original local page snapshot SHA256: ' + sha(original.read_bytes()) + '\n')
    write(ROOT / source['evidenceFile'], text.encode())
    return sha(text.encode())


def resample(data, rate):
    # Gentle band limits remove machine-room air noise while retaining the
    # recorded low motor fundamental and mechanical relay transients.
    frequencies = np.fft.rfftfreq(len(data), 1 / rate)
    gain = np.ones(len(frequencies))
    gain[frequencies <= 35] = 0
    low = (frequencies > 35) & (frequencies < 70)
    gain[low] = .5 - .5 * np.cos(np.pi * (frequencies[low] - 35) / 35)
    high = (frequencies > 5500) & (frequencies < 7000)
    gain[high] = .5 + .5 * np.cos(np.pi * (frequencies[high] - 5500) / 1500)
    gain[frequencies >= 7000] = 0
    filtered = np.fft.irfft(np.fft.rfft(data) * gain, n=len(data))
    return np.interp(np.arange(round(len(data) * RATE / rate)) * rate / RATE,
                     np.arange(len(data)), filtered)


def heavy_band(data, low=28, high=3600, weight_db=0):
    data = data - np.mean(data)
    frequencies = np.fft.rfftfreq(len(data), 1 / RATE)
    gain = (frequencies / max(low, 1)) ** 2
    gain = gain / (1 + gain) / np.sqrt(1 + (frequencies / high) ** 8)
    if weight_db:
        # Broad low gearing weight comes from the recording itself.
        gain *= 10 ** ((weight_db / (1 + (frequencies / 210) ** 4)) / 20)
    return np.fft.irfft(np.fft.rfft(data) * gain, n=len(data))


def lowered(data, ratio):
    # Conventional playback resampling, not a generated oscillator or drone.
    return np.interp(np.arange(round(len(data) / ratio)) * ratio, np.arange(len(data)), data)


def direct_drive_motor_clips():
    # Reconstruct only the motor body from its frozen accepted Ogg. Its
    # waveform and pitch are never regenerated or replaced in the pack.
    io = audio.AudioIO(Path(r'C:\Program Files\Audacity\sndfile.dll'))
    run_path = ROOT / 'assets/star_program_cargo/sounds/motor/run.ogg'
    if sha(run_path.read_bytes()) != FROZEN_SOUNDS['motor.run']:
        raise ValueError('Accepted travel clip changed')
    decoded, rate = io.read(run_path)
    run = decoded[:, 0]
    stack = np.zeros(rate * 7)
    for at in [0, 2, 4]:
        stack[at * rate:at * rate + len(run)] += run
    period = stack[rate * 2:rate * 4].copy()
    source = ROOT / CONTACTOR['file']
    if sha(source.read_bytes()) != CONTACTOR['sha256']:
        raise ValueError('Preserved contactor source changed')
    evidence_sha = evidence_extract(CONTACTOR)
    raw, source_rate = mp3.decode_mp3(source)
    raw = np.interp(np.arange(round(len(raw) * RATE / source_rate)) * source_rate / RATE,
                    np.arange(len(raw)), raw)
    def switch(start, end):
        samples = lowered(raw[round(start * RATE):round(end * RATE)], .78)
        samples = heavy_band(samples, low=30, high=4200)
        return audio.fade(audio.level(samples, target=.14, peak=.72), .004, .10)
    # Actual isolated contactor switches after the initial18 small relay
    # clicks. One engagement, one release and one brake-latch accent only.
    on, off = switch(34.27, 34.8), switch(38.87, 39.4)
    start = np.zeros(round(2.2 * RATE))
    body = np.tile(period, 2)[:len(start)]
    times = np.arange(len(start)) / RATE
    energized = np.clip((times - .12) / .012, 0, 1)
    inrush = 1 + .65 * np.exp(-np.maximum(times - .13, 0) / .18)
    start += body * energized * inrush
    start[:len(on)] += on
    start[-round(.2 * RATE):] *= np.cos(np.linspace(0, np.pi / 2, round(.2 * RATE))) ** 2
    brake = np.tile(period, 2)[:RATE * 3].copy()
    times = np.arange(len(brake)) / RATE
    coast = np.where(times < .07, 1, np.exp(-np.maximum(times - .07, 0) / .32))
    coast[times > 1.1] = 0
    brake *= coast
    brake[:len(off)] += off
    latch, at = on * .60, round(.72 * RATE)
    brake[at:at + len(latch)] += latch
    brake = audio.fade(brake, .004, .20)
    peak = max(float(np.max(abs(start))), float(np.max(abs(brake))))
    gain = min(1.0, .88 / max(peak, 1e-9))
    start *= gain
    brake *= gain
    provenance = {key: value for key, value in CONTACTOR.items() if key != 'originalEvidenceFile'}
    provenance.update({'bytes': source.stat().st_size, 'sourceRate': source_rate,
                       'evidenceSha256': evidence_sha,
                       'quality': 'Public HQ MP3 preview, original M4A requires login',
                       'cropsSeconds': {'engage': [34.27, 34.8], 'release': [38.87, 39.4]},
                       'playbackRatio': .78, 'smallRelayClicksUsed': False})
    return {'motor.start': start, 'motor.run': run, 'motor.brake': brake}, provenance


def prepare():
    if sha(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError('Preserved source recording changed')
    motor_source = {'title': 'Electric hoist', 'creator': 'Micronin', 'page': PAGE,
                    'downloadUrl': DOWNLOAD, 'license': 'CC0-1.0', 'licenseUrl': LICENSE,
                    'quality': 'Public HQ MP3 preview, original WAV requires login',
                    'file': 'source/' + SOURCE.name, 'sha256': SOURCE_SHA,
                    'originalEvidenceFile': 'source/micronin-hoist-184888.html',
                    'evidenceFile': 'source/electric-hoist-license.txt'}
    motor_evidence_sha = evidence_extract(motor_source)
    original, rate = mp3.decode_mp3(SOURCE)
    source = np.interp(np.arange(round(len(original) * RATE / rate)) * rate / RATE,
                       np.arange(len(original)), original)
    clips, contactor_source = direct_drive_motor_clips()
    start, run, brake = [clips[key] for key in ['motor.start', 'motor.run', 'motor.brake']]
    cue_sources = {}
    for name, spec in CUES.items():
        source_path = ROOT / spec['file']
        if sha(source_path.read_bytes()) != spec['sha256']:
            raise ValueError('User-selected cue source changed: ' + name)
        cue_evidence_sha = evidence_extract(spec)
        samples, cue_rate = mp3.decode_mp3(source_path)
        # Keep the full user-selected cue at its recorded pitch and duration.
        mono = np.interp(np.arange(round(len(samples) * RATE / cue_rate)) * cue_rate / RATE,
                         np.arange(len(samples)), samples)
        clips[name] = audio.fade(audio.level(mono, target=.08, peak=.65), .005, .03)
        cue_sources[name] = {key: value for key, value in spec.items() if key != 'originalEvidenceFile'}
        cue_sources[name].update({'bytes': source_path.stat().st_size, 'sampleRate': cue_rate,
                                 'durationSeconds': len(samples) / cue_rate,
                                 'quality': 'Public HQ MP3 preview, original WAV requires login',
                                 'evidenceSha256': cue_evidence_sha})
    sys.path.insert(0, str(GAME / 'resource-pack/tts/announcements'))
    speech = module('cargo_whole_speech_processing', GAME / 'resource-pack/tts/announcements/render_announcements.py')
    voice_sources = {}
    voice_rights = ('Cargo door speech generation\n'
                    'Provider: ttsMP3 regular voices browser interface\n'
                    'Voice: US English / Matthew, Amazon Polly\n'
                    'Rate: natural default100 percent\n'
                    'Generated through the provider UI on2026-10-29.\n'
                    'Provider usage terms: https://ttsmp3.com/text-to-speech-commercial-use\n'
                    'The provider permits using its generated audio in games, including commercial projects.\n'
                    'No voice model or third-party game recording is included.\n')
    write(ROOT / 'source/ttsmp3-usage.txt', voice_rights.encode())
    for name, spec in VOICES.items():
        source_path = ROOT / spec['file']
        if sha(source_path.read_bytes()) != spec['sha256']:
            raise ValueError('Preserved voice source changed: ' + name)
        raw, source_rate, decoded_info = speech.audio.decode_mp3(source_path)
        natural, trimming = speech.trim_padding(speech.audio.resample(raw, source_rate))
        dry = speech.speaker_eq(natural)
        level = speech.active_rms(dry)
        gain = float(np.clip(.075 / level, 10 ** (-3 / 20), 10 ** (3 / 20)))
        wet = speech.facility_room(dry)
        gain = min(gain, .85 / max(float(np.max(abs(wet))), 1e-9)) * 1.5
        gain *= min(1.0, .95 / max(float(np.max(abs(wet))) * gain, 1e-9))
        processed = wet * gain
        clips[name] = np.interp(np.arange(round(len(processed) * RATE / speech.RATE)) * speech.RATE / RATE,
                                np.arange(len(processed)), processed)
        voice_sources[name] = {**spec, 'creator': 'STAR PROGRAM via ttsMP3',
                               'page': 'https://ttsmp3.com/', 'license': 'ttsMP3 generated-audio use permission',
                               'licenseUrl': 'https://ttsmp3.com/text-to-speech-commercial-use',
                               'evidenceFile': 'source/ttsmp3-usage.txt',
                               'evidenceSha256': sha(voice_rights.encode()),
                               'bytes': source_path.stat().st_size, 'sourceRate': source_rate,
                               'decodedFrames': decoded_info['decodedFrames'],
                               'voice': 'US English / Matthew', 'ratePercent': 100,
                               'engine': 'ttsMP3 free regular voice UI / Amazon Polly',
                               'speechMs': len(natural) / speech.RATE * 1000,
                               'trimming': trimming, 'linearGain': gain,
                               'processing': {'effect': 'existing facility intercom', 'pitchChanged': False,
                                              'timeStretched': False, 'room': speech.ROOM,
                                              'masterGain': 1.5, 'targetActiveRms': .075,
                                              'speakerEq': '90Hz highpass,6500Hz soft lowpass,0.75dB1800Hz presence'}}
    io = audio.AudioIO(Path(r'C:\Program Files\Audacity\sndfile.dll'))
    sounds, entries = {}, {}
    for name, samples in clips.items():
        relative = f'assets/{NS}/sounds/{name.replace(".", "/")}.ogg'
        target = ROOT / relative
        if name in FROZEN_SOUNDS:
            if not target.exists() or sha(target.read_bytes()) != FROZEN_SOUNDS[name]:
                raise ValueError('Frozen accepted sound changed: ' + name)
        else:
            io.write(target, samples, quality=.38)
        decoded, decoded_rate = io.read(target)
        if decoded_rate != RATE or decoded.shape != (len(samples), 1):
            raise ValueError('Incorrect decoded sound format: ' + name)
        decoded = decoded[:, 0]
        peak, rms = float(np.max(abs(decoded))), audio.rms(decoded)
        if not np.isfinite(decoded).all() or peak >= .99 or rms < .008:
            raise ValueError('Clipped, invalid, or silent sound: ' + name)
        if name not in VOICES and max(abs(float(decoded[0])), abs(float(decoded[-1]))) > .004:
            raise ValueError('Unfaded sound edge: ' + name)
        entries[name] = {'event': f'{NS}:{name}', 'file': relative,
                         'sha256': sha(target.read_bytes()), 'bytes': target.stat().st_size,
                         'frames': len(decoded), 'sampleRate': RATE, 'channels': 1,
                         'durationMs': round(len(decoded) / RATE * 1000),
                         'ticks': math.ceil(len(decoded) / RATE * 20),
                         'playbackPitch': 1, 'volume': .65,
                         'repeatEveryTicks': 40 if name == 'motor.run' else None,
                         'overlapMs': 200 if name == 'motor.run' else 0,
                         'peak': peak, 'rms': rms}
        sounds[name] = {'sounds': [{'name': f'{NS}:{name.replace(".", "/")}',
                                  'stream': False, 'attenuation_distance': 40}]}
        audio.write_wav(ROOT / f'previews/{name.replace(".", "-")}.wav', samples)
    write(ROOT / f'assets/{NS}/sounds.json', json_bytes(sounds))
    credits = ('Cargo elevator motor audio\n\n'
               'Electric hoist by Micronin\n' + PAGE + '\n'
               'CC0 1.0 Universal\n' + LICENSE + '\n\n'
               'Source: the public HQ MP3 preview of the author\'s original recording.\n'
               'Changes: mono32 kHz conversion, constant0.85playback lowering, broad30-4500HzEQ,\n'
               'same-motor startup and braking crops, shared level adjustment, edge fades,\n'
               'a2secondphase-aligned motor period with200ms overlapping playback, Vorbis encoding.\n'
               'The recording author does not endorse STAR PROGRAM.\n')
    credits += ('\nDeparture cue: Factory Warning Buzzer by qubodup\n'
                'https://freesound.org/people/qubodup/sounds/832414/\n'
                'CC0 1.0 Universal\nhttps://creativecommons.org/publicdomain/zero/1.0/\n'
                'Derived by qubodup from a bridge crane recording by AstraPLanetshine.\n'
                'STAR PROGRAM changes: mono32 kHz conversion, level adjustment, edge fades, Vorbis encoding.\n'
                '\nArrival cue: 13622 ready bell ring by Robinhood76\n'
                'https://freesound.org/people/Robinhood76/sounds/841269/\n'
                'Creative Commons Attribution-NonCommercial4.0 International\n'
                'https://creativecommons.org/licenses/by-nc/4.0/\n'
                'Noncommercial use only.\n'
                'Changes: stereo to mono32 kHz conversion, level adjustment, edge fades, Vorbis encoding.\n'
                'These authors do not endorse STAR PROGRAM.\n')
    credits += ('\nCargo door voice lines\n'
                'Stand back! Doors opening.\nStand back! Doors closing.\n'
                'Generated through ttsMP3 regular voices, US English / Matthew (Amazon Polly).\n'
                'https://ttsmp3.com/text-to-speech-commercial-use\n'
                'Provider permits generated MP3 use in games and commercial/noncommercial projects.\n'
                'Whole utterances with the established STAR PROGRAM intercom processing.\n')
    credits += ('\nHard-switching startup and stop\n'
                'Contactor/motor overload relay noises by tt_runscript\n'
                'https://freesound.org/people/tt_runscript/sounds/807384/\n'
                'CC0 1.0 Universal\nhttps://creativecommons.org/publicdomain/zero/1.0/\n'
                'Actual Siemens contactor engagement/release crops, lower playback, EQ and level adjustment.\n'
                'The motor body is the accepted travel waveform with an amplitude inrush and short coast.\n'
                'No motor pitch sweep or repeating relay clicks are added.\n')
    write(ROOT / 'credits/cargo-elevator-audio.txt', credits.encode())
    manifest = {'version': 1, 'namespace': NS,
                'creditsFile': 'credits/cargo-elevator-audio.txt',
                'source': {**{key: value for key, value in motor_source.items() if key != 'originalEvidenceFile'},
                           'bytes': SOURCE.stat().st_size, 'sampleRate': rate,
                           'durationSeconds': len(original) / rate,
                           'evidenceSha256': motor_evidence_sha},
                'cueSources': cue_sources,
                'contactorSource': contactor_source,
                'frozenAcceptedSounds': FROZEN_SOUNDS,
                'voiceSources': voice_sources,
                'processing': {'generatedMotorOrCueAudio': False, 'wholeUtteranceSyntheticSpeech': True,
                               'movementRevision': 'hard-switching-approved-electric-hoist',
                               'motorPitchChanged': False, 'motorPitchGlides': False, 'motorDurationFitted': False, 'vorbisQuality': .38,
                               'approvedMotorPlaybackRatio': .85, 'contactorPlaybackRatio': .78, 'motorLayers': 1,
                               'sourceCropsSeconds': {'motor.run': [21.5, 23.37],
                                                      'contactor.engage': [34.27, 34.8],
                                                      'contactor.release': [38.87, 39.4]},
                               'motorLoopPeriodMs': 2000,
                               'motorLoopFadeAndOverlapMs': 200},
                'monoVorbis': True, 'deterministicEvents': True,
                'audioBytes': sum(row['bytes'] for row in entries.values()),
                'sounds': entries}
    write(ROOT / 'manifest.json', json_bytes(manifest))
    # A preview demonstrates the required overlap cadence and three stages.
    # Preview the exact native cadence, deliberately braking during an
    # in-flight cruise clip. StopSound clears run before the brake clip starts.
    preview = np.zeros(RATE * 14)
    preview[:len(start)] += start
    for at in [2, 4, 6, 8]:
        preview[at * RATE:at * RATE + len(run)] += run
    cut = RATE * 9
    preview[cut:] = 0
    preview[cut:cut + len(brake)] += brake
    audio.write_wav(ROOT / 'previews/cargo-elevator-direct-drive-runtime.wav', preview)
    if sha(APPROVED_PREDECESSOR.read_bytes()) != APPROVED_PREDECESSOR_SHA:
        raise ValueError('Approved predecessor archive changed')
    with ZipFile(APPROVED_PREDECESSOR) as previous:
        for name, expected_sha in FROZEN_SOUNDS.items():
            path = entries[name]['file']
            if sha(previous.read(path)) != expected_sha or previous.read(path) != (ROOT / path).read_bytes():
                raise ValueError('Accepted sound changed in direct-drive revision: ' + name)
    return manifest


def overlay_files(manifest):
    files = {path.relative_to(ROOT).as_posix(): path.read_bytes()
             for folder in ['assets', 'credits'] for path in (ROOT / folder).rglob('*') if path.is_file()}
    files['compatibility/cargo-elevator-audio/manifest.json'] = json_bytes(manifest)
    return files


def build():
    manifest = prepare()
    base = BASE.read_bytes()
    if sha(base) != BASE_SHA:
        raise ValueError('Pinned 26.3 base ZIP changed')
    active = json.loads((GAME / 'config/resource-pack.json').read_text(encoding='utf-8'))
    if active.get('sha256') != BASE_SHA:
        raise ValueError('Active resource pin changed, rebase the audio overlay first')
    files = overlay_files(manifest)
    with ZipFile(BASE) as original, ZipFile(PACK, 'w', compression=ZIP_DEFLATED, compresslevel=9) as out:
        if set(files) & set(original.namelist()):
            raise ValueError('Cargo overlay unexpectedly replaces existing resources')
        for info in original.infolist():
            out.writestr(copy(info), original.read(info.filename))
        for name, content in sorted(files.items()):
            info = ZipInfo(name, (2026, 10, 29, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            out.writestr(info, content, compresslevel=9)
    report = verify(manifest)
    write(REPORT, json_bytes(report))
    return report


def verify(manifest=None):
    manifest = manifest or json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    files = overlay_files(manifest)
    with ZipFile(BASE) as original, ZipFile(PACK) as out:
        if len(out.namelist()) != len(set(out.namelist())):
            raise ValueError('Duplicate ZIP entries')
        if set(out.namelist()) != set(original.namelist()) | set(files):
            raise ValueError('Unexpected archive entries')
        for name in original.namelist():
            if out.read(name) != original.read(name):
                raise ValueError('Existing archive resource changed: ' + name)
        for name, content in files.items():
            if out.read(name) != content:
                raise ValueError('Overlay resource differs: ' + name)
    data = PACK.read_bytes()
    if len(data) > LIMIT:
        raise ValueError('Cargo pack exceeds DiamondFire 40 MiB upload limit')
    return {'status': 'prepared', 'published': False, 'base': str(BASE),
            'baseSha256': BASE_SHA, 'file': str(PACK), 'sha256': sha(data),
            'sha1': hashlib.sha1(data).hexdigest(), 'size': len(data),
            'sizeLimitBytes': LIMIT, 'sizeRemainingBytes': LIMIT - len(data),
            'addedFiles': sorted(files), 'existingResourcesPreserved': True,
            'cargoAudio': manifest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audio', 'build', 'verify'])
    action = parser.parse_args().action
    result = prepare() if action == 'audio' else build() if action == 'build' else verify()
    print(json.dumps(result, indent=2))
