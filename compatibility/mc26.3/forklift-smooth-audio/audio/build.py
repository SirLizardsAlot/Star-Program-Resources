"""Stage a continuous hydraulic loop without changing the active pack or pin.

The former 240 ms sound remains byte exact for old templates. A one-second
periodic body is extended by an identical 200 ms head. Complementary fades
therefore reconstruct the same waveform at each native scheduling boundary.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import shutil
import wave

import numpy as np

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack/forklift-audio'
OUT = ROOT / 'loop-candidate'
RATE = 32000
SOURCE_SHA = '0f37bda459666a71a79482b11832bef455f23b8cf1505462677627e117d76459'
OLD_SHA = 'aac7f45b54248c520b4ab84267f0f0fbe6bd852186d79957ad763ba7b29bda75'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


audio = module('forklift_loop_audio', GAME / 'resource-pack/turbines/build_audio.py')
decode = module('forklift_loop_mp3', GAME / 'resource-pack/lab-audio/audio_io.py')
sha = lambda data: hashlib.sha256(data).hexdigest()
rms = lambda data: float(np.sqrt(np.mean(data * data)))


def json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def wav_write(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


def pitched(samples, pitch):
    return np.interp(np.arange(round(len(samples) / pitch)) * pitch,
                     np.arange(len(samples)), samples)


def spectrum(samples):
    power = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) ** 2
    frequencies = np.fft.rfftfreq(len(samples), 1 / RATE)
    power[0] = 0
    total = power.sum()
    index = power.argmax()
    return {'centroidHz': round(float((power * frequencies).sum() / total), 2),
            'above2000HzPercent': round(float(power[frequencies > 2000].sum() / total * 100), 3),
            'peakHz': round(float(frequencies[index]), 2),
            'peak20HzBandPowerPercent': round(float(power[np.abs(frequencies - frequencies[index]) < 10].sum() / total * 100), 3)}


def render_motion(loop, release, start, stop, pitch, volume, count):
    output = np.zeros(count)
    grain = pitched(loop, pitch) * volume
    hop = round(RATE / pitch)
    first, last = round(start * RATE), round(stop * RATE)
    for at in range(first, last, hop):
        end = min(last, at + len(grain))
        output[at:end] += grain[:end - at]
    tail = pitched(release, pitch) * volume * .65
    output[last:min(count, last + len(tail))] += tail[:max(0, min(count - last, len(tail)))]
    return output


def main(stage=False):
    old_manifest = json.loads((ROOT / 'manifest.json').read_text())
    old_path = ROOT / 'assets/star_program_forklift/sounds/lift/move.ogg'
    assert sha(old_path.read_bytes()) == OLD_SHA
    source = ROOT / 'source/nuckan-forklift-hydraulics-hq.mp3'
    assert sha(source.read_bytes()) == SOURCE_SHA
    page = (ROOT / 'source/nuckan-212941.html').read_text()
    assert 'creativecommons.org/publicdomain/zero/1.0' in page
    raw, source_rate = decode.decode_mp3(source.resolve())
    raw = np.interp(np.arange(round(len(raw) * RATE / source_rate)) * source_rate / RATE,
                    np.arange(len(raw)), raw)
    # This longer section has changing pump/valve texture instead of the old
    # nearly stationary 425 Hz tone. Filter the whole source before cropping.
    filtered = audio.filtered(raw, RATE, highpass=70, lowpass=1100)
    start, end = 5.05, 6.25
    segment = filtered[round(start * RATE):round(end * RATE)].copy()
    overlap = round(.2 * RATE)
    body_frames = RATE
    assert len(segment) == body_frames + overlap
    # Crossfade the source tail into its head inside the periodic body. Equal
    # power keeps unrelated mechanical detail from dipping at this inner join.
    phase = np.linspace(0, np.pi / 2, overlap, endpoint=True)
    join = segment[-overlap:] * np.cos(phase) + segment[:overlap] * np.sin(phase)
    body = np.concatenate([segment[overlap:body_frames], join])
    body -= body.mean()
    body *= min(.12 / rms(body), .65 / np.max(np.abs(body)))
    # Identical overlap samples plus complementary amplitude fades make every
    # repeated packet phase coherent, including its natural source variation.
    loop = np.concatenate([body, body[:overlap]])
    fade = np.sin(phase) ** 2
    loop[:overlap] *= fade
    loop[-overlap:] *= 1 - fade
    release = body[round(.35 * RATE):round(.53 * RATE)].copy()
    attack = round(.01 * RATE)
    release[:attack] *= np.sin(np.linspace(0, np.pi / 2, attack)) ** 2
    release[attack:] *= np.cos(np.linspace(0, np.pi / 2, len(release) - attack)) ** 2
    io = audio.AudioIO(Path(r'C:\Program Files\Audacity\sndfile.dll'))
    files = {}
    decoded = {}
    for key, samples in [('loop', loop), ('release', release)]:
        path = OUT / f'assets/star_program_forklift/sounds/lift/{key}.ogg'
        io.write(path, samples, quality=.45)
        actual, rate = io.read(path)
        assert rate == RATE and actual.shape == (len(samples), 1)
        decoded[key] = actual[:, 0]
        files[key] = {'file': path.relative_to(OUT).as_posix(), 'sha256': sha(path.read_bytes()),
                      'bytes': path.stat().st_size, 'durationMs': len(samples) / RATE * 1000,
                      'sampleRate': RATE, 'channels': 1, 'frames': len(samples),
                      'fadeInMs': 200 if key == 'loop' else 10,
                      'fadeOutMs': 200 if key == 'loop' else 170}
    assert len(decoded['loop']) == 38400 and len(decoded['release']) == 5760
    preview = render_motion(decoded['loop'], decoded['release'], .1, 2.2, 1, .18, RATE * 5)
    preview += render_motion(decoded['loop'], decoded['release'], 2.8, 4.5, 10 / 11, .14, RATE * 5)
    wav_write(OUT / 'preview-up-stop-down-stop.wav', preview)
    wav_write(OUT / 'loop-three-cycles.wav', render_motion(decoded['loop'], decoded['release'], 0, 3, 1, .5, round(3.2 * RATE)))
    # Exact decoded packet comparisons at native dispatch boundaries. Vorbis
    # independently encodes the two copies, so allow its small coding error.
    reconstruction = decoded['loop'][:overlap] + decoded['loop'][body_frames:]
    join_error = reconstruction - body[:overlap]
    # Compare a short seam window with its adjacent signal, rather than a
    # misleading endpoint-zero check on the individually faded Ogg file.
    internal_delta = abs(body[0] - body[-1])
    normal_step_rms = rms(np.diff(body))
    manifest = {
        'version': 2, 'namespace': 'star_program_forklift',
        'source': old_manifest['source'],
        'processing': {'cropSeconds': [start, end], 'mono': True,
                       'highPassHz': 70, 'lowPassHz': 1100,
                       'periodicBodyMs': 1000, 'sourceJoinCrossfadeMs': 200,
                       'packetOverlapMs': 200, 'periodicHeadDuplicated': True,
                       'syntheticAudio': False},
        'sounds': {
            'lift.move': old_manifest['sounds']['lift.move'],
            'lift.loop': {'eventPrefix': 'star_program_forklift:lift.move.',
                          'channelCount': 8, **files['loop']},
            'lift.release': {'event': 'star_program_forklift:lift.release', **files['release']}},
        'recommendedPlayback': {'upPitch': 1, 'downPitch': 10 / 11,
                                'upVolume': .18, 'downVolume': .14,
                                'upRepeatTicks': 20, 'downRepeatTicks': 22,
                                'range': 20, 'maximumReleaseMs': 198,
                                'channelCount': 8},
        'creditsFile': 'credits/forklift-audio.txt'}
    registrations = json.loads((ROOT / 'assets/star_program_forklift/sounds.json').read_text())
    for channel in range(1, 9):
        registrations[f'lift.move.{channel}'] = {'sounds': [{'name': 'star_program_forklift:lift/loop',
                                                          'stream': False, 'attenuation_distance': 20}]}
    registrations['lift.release'] = {'sounds': [{'name': 'star_program_forklift:lift/release',
                                               'stream': False, 'attenuation_distance': 20}]}
    json_write(OUT / 'assets/star_program_forklift/sounds.json', registrations)
    json_write(OUT / 'manifest.v2.json', manifest)
    credits = ('Forklift lift movement\nRecording: hydraulics.wav by nuckan\n'
               'https://freesound.org/people/nuckan/sounds/212941/\n'
               'License: CC0-1.0\nhttps://creativecommons.org/publicdomain/zero/1.0/\n'
               'Source: publicly offered HQ MP3 preview, recorded by the creator from their forklift at work.\n'
               'Continuous loop: source 5.05 to 6.25 seconds, mono 32 kHz, 70 Hz highpass, 1100 Hz lowpass.\n'
               'A 200 ms equal-power source crossfade produces a one-second periodic body.\n'
               'Its first 200 ms is duplicated at the end and complementary 200 ms fades permit phase-coherent packet overlap.\n'
               'Playback: raise at pitch 1 every 20 ticks, lower at pitch 10/11 every 22 ticks.\n'
               'Release: matched 180 ms crop with 10 ms fade-in and 170 ms fade-out.\n'
               'Eight event aliases reference one loop file for independent vehicle sound channels.\n'
               'Original lift.move event and 240 ms file are preserved for older templates.\n'
               'No synthesized motor audio is used.\n')
    (OUT / 'credits.txt').write_text(credits, encoding='utf-8')
    report = {'sourceSHA256': SOURCE_SHA, 'oldGrainSHA256': OLD_SHA,
              'activeAssetsUnchanged': True, 'newFiles': files,
              'spectrum': spectrum(body),
              'decodedOverlapErrorRmsDbFS': round(float(20 * np.log10(rms(join_error))), 3),
              'decodedOverlapErrorVsBodyDb': round(float(20 * np.log10(rms(join_error) / rms(body[:overlap]))), 3),
              'periodBoundaryStep': float(internal_delta),
              'normalAdjacentSampleDeltaRms': normal_step_rms,
              'packetBoundaryExpectedDiscontinuity': 0,
              'previewSeconds': 5, 'previewPeak': float(np.max(np.abs(preview))),
              'previewRmsDbFS': round(float(20 * np.log10(rms(preview))), 3),
              'upLoopHopMs': 1000, 'downLoopHopMs': 1100,
              'upOverlapMs': 200, 'downOverlapMs': 220,
              'preview': str((OUT / 'preview-up-stop-down-stop.wav').resolve())}
    json_write(OUT / 'analysis.json', report)
    assert sha(old_path.read_bytes()) == OLD_SHA
    assert old_manifest == json.loads((ROOT / 'manifest.json').read_text())
    if stage:
        for path in (OUT / 'assets').rglob('*'):
            if path.is_file():
                destination = ROOT / path.relative_to(OUT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        shutil.copyfile(OUT / 'manifest.v2.json', ROOT / 'manifest.json')
        shutil.copyfile(OUT / 'credits.txt', ROOT / 'credits.txt')
        assert sha(old_path.read_bytes()) == OLD_SHA
        assert sha(source.read_bytes()) == SOURCE_SHA
        assert all(sha((ROOT / row['file']).read_bytes()) == row['sha256'] for row in files.values())
        report['staged'] = True
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', action='store_true', help='Promote reviewed local assets and manifest, never the active pack pin')
    main(parser.parse_args().stage)
