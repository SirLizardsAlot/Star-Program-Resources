"""Prepare short positional lift grains from nuckan's CC0 forklift recording."""
from pathlib import Path
import hashlib
import importlib.util
import json
import wave
import numpy as np

GAME = Path(__file__).resolve().parent.parent
ROOT = GAME / 'resource-pack/forklift-audio'
RATE = 32000
SOURCE = ROOT / 'source/nuckan-forklift-hydraulics-hq.mp3'
SOURCE_SHA = '0f37bda459666a71a79482b11832bef455f23b8cf1505462677627e117d76459'
PAGE = 'https://freesound.org/people/nuckan/sounds/212941/'
DOWNLOAD = 'https://cdn.freesound.org/previews/212/212941_3910980-hq.mp3'
LICENSE = 'https://creativecommons.org/publicdomain/zero/1.0/'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


decode = module('forklift_mp3', GAME / 'resource-pack/lab-audio/audio_io.py')
audio = module('forklift_vorbis', GAME / 'resource-pack/turbines/build_audio.py')
sha = lambda data: hashlib.sha256(data).hexdigest()
json_bytes = lambda value: (json.dumps(value, indent=2)+'\n').encode()


def overlay_files():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    files = {path.relative_to(ROOT).as_posix(): path.read_bytes()
             for path in (ROOT / 'assets').rglob('*') if path.is_file()}
    expected = {'assets/star_program_forklift/sounds.json',
                'assets/star_program_forklift/sounds/lift/move.ogg'}
    assert set(files) == expected
    sound = manifest['sounds']['lift.move']
    assert sha(files[sound['file']]) == sound['sha256']
    assert manifest['source']['sha256'] == SOURCE_SHA == sha(SOURCE.read_bytes())
    registration = json.loads(files['assets/star_program_forklift/sounds.json'])
    assert registration == {'lift.move': {'sounds': [{'name': 'star_program_forklift:lift/move',
                                                    'stream': False, 'attenuation_distance': 20}]}}
    files['compatibility/forklift-audio/manifest.json'] = (ROOT / 'manifest.json').read_bytes()
    files['credits/forklift-audio.txt'] = (ROOT / 'credits.txt').read_bytes()
    return files, manifest


def main():
    source_page = (ROOT / 'source/nuckan-212941.html').read_text()
    assert 'creativecommons.org/publicdomain/zero/1.0' in source_page
    assert sha(SOURCE.read_bytes()) == SOURCE_SHA, 'The reviewed creator preview changed'
    raw, source_rate = decode.decode_mp3(SOURCE.resolve())
    # A steady 240ms section avoids the recording's valve/transient bursts.
    start, end = 1.68, 1.92
    samples = raw[round(start*source_rate):round(end*source_rate)]
    samples = np.interp(np.arange(round((end-start)*RATE))*source_rate/RATE,
                        np.arange(len(samples)), samples)
    samples -= samples.mean()
    frequencies = np.fft.rfftfreq(len(samples), 1/RATE)
    gain = (frequencies/90)**2
    gain = gain/(1+gain)/np.sqrt(1+(frequencies/4200)**8)
    samples = np.fft.irfft(np.fft.rfft(samples)*gain, n=len(samples))
    samples *= min(.13/np.sqrt(np.mean(samples*samples)), .7/max(abs(samples)))
    fade = round(.04*RATE)
    envelope = np.sin(np.linspace(0,np.pi/2,fade))**2
    samples[:fade] *= envelope
    samples[-fade:] *= envelope[::-1]
    target = ROOT / 'assets/star_program_forklift/sounds/lift/move.ogg'
    io = audio.AudioIO(Path(r'C:\Program Files\Audacity\sndfile.dll'))
    io.write(target,samples,quality=.30)
    decoded, rate = io.read(target)
    assert rate == RATE and decoded.shape == (7680,1)
    assert max(abs(decoded[:,0])) < .75
    registration = {'lift.move': {'sounds': [{'name': 'star_program_forklift:lift/move',
                                             'stream': False, 'attenuation_distance': 20}]}}
    (ROOT / 'assets/star_program_forklift/sounds.json').write_bytes(json_bytes(registration))
    source = {'title':'hydraulics.wav','creator':'nuckan','page':PAGE,'downloadUrl':DOWNLOAD,
              'license':'CC0-1.0','licenseUrl':LICENSE,'sha256':sha(SOURCE.read_bytes()),
              'file':'source/nuckan-forklift-hydraulics-hq.mp3',
              'quality':'Public HQ MP3 preview, not the original WAV',
              'provenance':'Creator identifies this as their forklift recorded at work with reduced ambience.'}
    manifest = {'version':1,'namespace':'star_program_forklift','source':source,
                'processing':{'cropSeconds':[start,end],'mono':True,'highPassHz':90,'lowPassHz':4200,
                              'fadeInMs':40,'fadeOutMs':40,'syntheticAudio':False},
                'sounds':{'lift.move':{'event':'star_program_forklift:lift.move',
                                       'file':target.relative_to(ROOT).as_posix(),
                                       'sha256':sha(target.read_bytes()),'bytes':target.stat().st_size,
                                       'durationMs':240,'sampleRate':RATE,'channels':1,'frames':7680,
                                       'fadeInMs':40,'fadeOutMs':40}},
                'recommendedPlayback':{'upPitch':1.08,'downPitch':.98,'upVolume':.28,'downVolume':.22,
                                       'repeatTicks':4,'range':20,'maximumTailMs':240/.98},
                'creditsFile':'credits/forklift-audio.txt'}
    (ROOT / 'manifest.json').write_bytes(json_bytes(manifest))
    credits=('Forklift lift movement\nRecording: hydraulics.wav by nuckan\n'+PAGE+'\n'
             'License: CC0-1.0\n'+LICENSE+'\n'
             'Derived from the public HQ preview. Short crop, mono conversion, gentle filtering and fades.\n'
             'One source grain plays at distinct native up/down pitches. No synthesized motor is used.\n')
    (ROOT / 'credits.txt').write_text(credits,encoding='utf-8')
    (ROOT / 'source/license.txt').write_text(credits+'Source SHA256: '+source['sha256']+'\n',encoding='utf-8')
    # Audition two 0.8-second movements at their actual pitch/volume, with a
    # pause between. Native 200ms dispatch leaves a <=245ms stopping tail.
    preview = np.zeros(RATE*3)
    for origin,pitch,volume in [(.15,1.08,.28),(1.6,.98,.22)]:
        grain = np.interp(np.arange(round(len(samples)/pitch))*pitch,np.arange(len(samples)),samples)*volume
        for elapsed in [0,.2,.4,.6]:
            at=round((origin+elapsed)*RATE)
            preview[at:at+len(grain)] += grain
    with wave.open(str(ROOT / 'preview-lift-up-down.wav'),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes((np.clip(preview,-1,1)*32767).astype('<i2').tobytes())
    files,_=overlay_files()
    print(json.dumps({'oggBytes':target.stat().st_size,'durationMs':240,'sampleRate':RATE,
                      'sourceSHA256':source['sha256'],'files':sorted(files),
                      'preview':str(ROOT/'preview-lift-up-down.wav')},indent=2))


if __name__ == '__main__':
    main()
