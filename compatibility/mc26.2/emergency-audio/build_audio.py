"""Build Code Black audio from the selected siren and a complete Matthew take.

All existing resource-pack audio stays read-only. Runtime code repeats the
single siren sweep; this exporter never concatenates siren cycles.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
NAMESPACE = "star_program_emergency"
SIREN_NAME = "412171_poligonstudio_air_raid_siren_hq_preview.ogg"
SIREN_SHA = "341d9865a676be24a6625a293153e3ec9e5c73910e01ac92141cb92f2f90e669"
PA_SHA = "6f50ca39be1a9bfd9ae2bd8f625ebfb4a350c35cc471de0b620e775f820fd8da"
TEXT = ("Be advised. Code Black declared. Threat level five. Catastrophic containment failure confirmed. "
        "All personnel are ordered to evacuate off-planet immediately. This is not a drill. "
        "Repeat: Code Black. Evacuate immediately.")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def louder(values, rate, gain_db, np, ceiling=0.90):
    """Zero-delay anticipatory peak control, with gradual attack/release.

    Backward smoothing starts attenuation ahead of peaks; forward smoothing
    releases it without pumping at individual waveform cycles. The gain never
    exceeds each sample's safe value. No sample clipping, phase/pitch changes,
    padding, rate changes, or tail truncation are used.
    """
    raised = values * 10 ** (gain_db / 20)
    required = np.minimum(1.0, ceiling / np.maximum(np.abs(raised), 1e-12))
    attack, release = 0.003, 0.065
    gain = required.copy()
    alpha = math.exp(-1 / (rate * attack))
    for index in range(len(gain) - 2, -1, -1):
        gain[index] = min(gain[index], 1 - (1 - gain[index + 1]) * alpha)
    alpha = math.exp(-1 / (rate * release))
    for index in range(1, len(gain)):
        gain[index] = min(gain[index], 1 - (1 - gain[index - 1]) * alpha)
    output = raised * gain
    report = {"requestedGainDb": gain_db, "limiter": "anticipatory smoothed gain; no waveform clipping",
              "sourcePeakCeiling": ceiling, "attackMs": attack * 1000, "releaseMs": release * 1000,
              "maximumGainReductionDb": float(-20 * math.log10(float(np.min(gain)))),
              "rmsBefore": float(np.sqrt(np.mean(values * values))),
              "rmsAfterBeforeEncoding": float(np.sqrt(np.mean(output * output))),
              "sourcePeak": float(np.max(np.abs(output))), "unchangedFrames": len(output)}
    return output, report


def main():
    siren_source, pa_source = ROOT / "sources" / SIREN_NAME, ROOT / "sources/code_black.mp3"
    if sha(siren_source) != SIREN_SHA or sha(pa_source) != PA_SHA:
        raise ValueError("Preserved source audio changed; review it before rebuilding.")
    source_map = {
        "version": 1, "provider": "ttsMP3 regular Matthew website UI", "voice": "Matthew", "ratePercent": 100,
        "page": "https://ttsmp3.com/", "generation": "Download as MP3 button; whole message, no splicing",
        "announcements": [{"id": "code_black", "text": TEXT, "source": "sources/code_black.mp3",
                           "sourceSha256": PA_SHA,
                           "originalDownloadFilename": "ttsMP3.com_VoiceText_2026-10-15_3-50-30.mp3"}],
    }
    map_path = ROOT / "source-map.json"
    map_path.write_text(json.dumps(source_map, indent=2) + "\n", encoding="utf-8")
    audio = load_module("emergency_effect_audio", ROOT.parent / "turbines/build_audio.py")
    io = audio.AudioIO(Path(r"C:\Program Files\Audacity\sndfile.dll"))
    source = audio.load(io, siren_source)
    # First complete wind-up, held peak and wind-down. The next sweep starts
    # after this section. Exact tick duration avoids overlapping native plays.
    start, end = 0.0, 13.4
    sweep = source[round(start * audio.RATE):round(end * audio.RATE)]
    sweep = audio.fade(sweep, 0.025, 0.080)
    sweep = audio.level(sweep, target=0.115, peak=0.80)
    sweep, siren_loudness = louder(sweep, audio.RATE, 7.2, audio.np)
    siren_path = f"assets/{NAMESPACE}/sounds/code_black/siren.ogg"
    io.write(ROOT / siren_path, sweep)
    decoded, rate = io.read(ROOT / siren_path)
    if (rate != 32000 or decoded.shape != (428800, 1) or not audio.np.isfinite(decoded).all()
            or audio.np.max(audio.np.abs(decoded)) > 0.95):
        raise ValueError("Siren is not exactly one 13.4-second mono sweep.")
    siren = {"event": f"{NAMESPACE}:code_black.siren", "file": siren_path,
             "sha256": sha(ROOT / siren_path), "bytes": (ROOT / siren_path).stat().st_size,
             "frames": len(decoded), "sampleRate": rate, "channels": 1,
             "durationMs": len(decoded) / rate * 1000, "ticks": 268, "playbackPitch": 1,
             "singleSweep": True, "sourceTrimSeconds": [start, end],
             "peak": float(audio.np.max(audio.np.abs(decoded))), "rms": audio.rms(decoded),
             "processing": {"monoDownmix": True, "highPassHz": 32, "lowPassHz": 11000,
                            "attackFadeMs": 25, "releaseFadeMs": 80, "pitchDsp": False,
                            "waveformSpeedDsp": False, "vorbisQuality": 0.32,
                            "loudness": siren_loudness}}
    audio.write_wav(ROOT / "previews/code_black_siren_one_sweep.wav", decoded[:, 0])

    renderer_path = ROOT.parent / "tts/announcements/render_announcements.py"
    sys.path.insert(0, str(renderer_path.parent))
    dsp = load_module("emergency_existing_intercom_dsp", renderer_path)
    dsp.ROOT = ROOT
    natural, provenance = dsp.prepare(source_map["announcements"][0], map_path)
    dry = dsp.speaker_eq(natural)
    level = dsp.active_rms(dry)
    wet = dsp.facility_room(dry)
    master = 1.5
    gain = float(dsp.np.clip(0.075 / level, 10 ** (-3 / 20), 10 ** (3 / 20)))
    matched = min(gain, 0.85 / max(float(dsp.np.max(dsp.np.abs(wet))), 1e-9))
    guard = min(1.0, 0.95 / max(float(dsp.np.max(dsp.np.abs(wet))) * matched * master, 1e-9))
    gain = matched * master * guard
    pa_path = f"assets/{NAMESPACE}/sounds/pa/code_black.ogg"
    (ROOT / pa_path).parent.mkdir(parents=True, exist_ok=True)
    encoder = dsp.audio.HighQualityEncoder(dsp.audio.AUDACITY / "sndfile.dll")
    pa_audio, pa_loudness = louder(wet * gain, dsp.RATE, 4.0, dsp.np)
    encoder.write(ROOT / pa_path, pa_audio)
    rendered = encoder.read(ROOT / pa_path)
    if not dsp.np.isfinite(rendered).all() or dsp.np.max(dsp.np.abs(rendered)) > 0.95:
        raise ValueError("Invalid exported Code Black announcement.")
    pa = {"event": f"{NAMESPACE}:pa.code_black", "file": pa_path, "text": TEXT,
          "sha256": sha(ROOT / pa_path), "bytes": (ROOT / pa_path).stat().st_size,
          "sampleRate": dsp.RATE, "channels": 1, "frames": len(rendered),
          "speechMs": round(len(natural) / dsp.RATE * 1000, 3),
          "durationMs": round(len(rendered) / dsp.RATE * 1000, 3),
          "ticks": math.ceil(len(rendered) * 20 / dsp.RATE), "source": provenance,
          "peak": float(dsp.np.max(dsp.np.abs(rendered))),
          "rms": float(dsp.np.sqrt(dsp.np.mean(rendered * rendered))),
          "processing": {"effect": "existing Matthew intercom EQ and facility room",
                         "pitchDsp": False, "waveformSpeedDsp": False, "masterGain": master,
                         "linearGain": gain, "vorbisQuality": 0.65, "room": dsp.ROOM,
                         "loudness": pa_loudness}}
    dsp.audio.base.write_wave(ROOT / "previews/code_black_matthew_intercom.wav", rendered)
    manifest = {"version": 1, "namespace": NAMESPACE,
                "source": {"title": "Air Raid Siren Alarm", "creator": "Poligonstudio",
                           "page": "https://freesound.org/people/Poligonstudio/sounds/412171/",
                           "license": "CC0-1.0", "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                           "quality": "Public HQ Ogg preview; original requires login",
                           "url": "https://cdn.freesound.org/previews/412/412171_7383104-hq.ogg",
                           "sha256": SIREN_SHA, "durationSeconds": 122.44897959183673},
                "speechSource": {"provider": source_map["provider"], "voice": "Matthew", "ratePercent": 100,
                                 "permissionUrl": "https://ttsmp3.com/faq", "sha256": PA_SHA},
                "sounds": {"code_black.siren": siren, "pa.code_black": pa}}
    sounds = {key: {"sounds": [{"name": f"{NAMESPACE}:" + row["file"].split("/sounds/", 1)[1][:-4], "stream": False}]}
              for key, row in manifest["sounds"].items()}
    audio.write_json(ROOT / f"assets/{NAMESPACE}/sounds.json", sounds)
    credits = ("STAR PROGRAM - Code Black emergency audio\n\n"
               "Air Raid Siren Alarm by Poligonstudio\n"
               "https://freesound.org/people/Poligonstudio/sounds/412171/\n"
               "Creative Commons Zero 1.0 (CC0-1.0)\n"
               "https://creativecommons.org/publicdomain/zero/1.0/\n"
               "Source: public HQ Ogg preview. Changes: first single rise/hold/fall sweep\n"
               "(0.0-13.4 seconds), mono downmix, resampling, gentle filtering, level matching,\n"
               "25/80 ms endpoint fades, Ogg Vorbis encoding. No synthetic siren replacement.\n"
               "Runtime repeats this one sweep every 268 game ticks at pitch 1.0.\n"
               "v24: siren raised 7.2 dB in PCM, announcement raised 4.0 dB in PCM.\n"
               "Smoothed anticipatory peak control preserves timing and pitch without\n"
               "waveform clipping. The runtime keeps the siren playing through PA speech.\n\n"
               "Announcement: complete Matthew recording generated using the normal ttsMP3\n"
               "Download as MP3 website interface at native rate and pitch. Commercial and\n"
               "non-commercial distribution permitted by provider: https://ttsmp3.com/faq\n"
               "Processed with the existing STAR PROGRAM intercom EQ and facility room.\n")
    (ROOT / "CREDITS.txt").write_text(credits, encoding="utf-8")
    audio.write_json(ROOT / "manifest.json", manifest)
    print(json.dumps({key: {field: row[field] for field in ("event", "durationMs", "ticks", "bytes")}
                      for key, row in manifest["sounds"].items()}, indent=2))


if __name__ == "__main__":
    main()
