"""Render the separate turbine PA bank using the existing Matthew intercom DSP."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
EXISTING_RENDERER = ROOT.parents[1] / "tts/announcements/render_announcements.py"
NAMESPACE = "star_program_turbines"
IDS = ("turbine_1_starting", "turbine_2_starting", "turbine_1_online", "turbine_2_online",
       "turbine_1_stopping", "turbine_2_stopping", "steam_lost", "generation_lost")
LICENSE = {"voice": "Matthew",
           "permission": "ttsMP3 permits commercial and non-commercial use of generated audio, for free and paid usage",
           "permissionUrl": "https://ttsmp3.com/faq", "generation": "Normal website download interface; stock Matthew regular voice"}


def load_helpers():
    # Import only processing/audio helpers. All output roots are redirected to
    # this separate bank before invoking preparation; the original bank is read-only.
    sys.path.insert(0, str(EXISTING_RENDERER.parent))
    spec = importlib.util.spec_from_file_location("star_existing_announcement_dsp", EXISTING_RENDERER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    if module.ROOT.resolve() == EXISTING_RENDERER.parent.resolve():
        raise ValueError("Turbine PA output must be separate from the existing announcement bank.")
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(map_path, preview_tag="v21"):
    if not re.fullmatch(r"[a-z0-9_-]+", preview_tag):
        raise ValueError("Preview tag must be a lowercase identifier.")
    source_map = json.loads(map_path.read_text(encoding="utf-8"))
    provider = source_map.get("provider")
    if provider not in {"ttsMP3 standard Matthew UI", "ttsMP3 paid members UI"}:
        raise ValueError("Expected documented ttsMP3 Matthew website source provenance.")
    entries = source_map.get("announcements", [])
    if (len(entries) != len(IDS) or {entry.get("id") for entry in entries} != set(IDS)
            or source_map.get("voice", "Matthew") != "Matthew"
            or source_map.get("ratePercent", 100) != 100):
        raise ValueError("Expected the eight complete Matthew turbine announcements at native rate 100%.")
    for entry in entries:
        if not entry.get("text", "").strip() or not re.fullmatch(r"[a-f0-9]{64}", entry.get("sourceSha256", "")):
            raise ValueError("Every turbine announcement needs authored text and a source SHA-256.")
    dsp = load_helpers()
    audio, np, rate = dsp.audio, dsp.np, dsp.RATE
    encoder = audio.HighQualityEncoder(audio.AUDACITY / "sndfile.dll")
    master_gain, target_rms = 1.5, 0.075
    processing = {"effect": "intercom", "pitchDsp": False, "waveformSpeedDsp": False,
                  "vorbisQuality": 0.65, "room": dsp.ROOM, "levelTargetActiveRms": target_rms,
                  "linearGainBoundDb": 3, "masterGain": master_gain,
                  "masterGainDb": round(20 * math.log10(master_gain), 6),
                  "normalizationPeakCeiling": 0.85, "masterPeakCeiling": 0.95,
                  "peakGuard": "Original0.85normalization ceiling;post-master constant attenuation only if needed for0.95source peak;no limiter/saturation",
                  "speakerEq": "90Hz gentle highpass,6500Hz soft lowpass,+0.75dB broad1800Hz presence",
                  "timing": "ticks=ceil(full decoded duration/50ms), including room tail"}
    manifest = {"version": 1, "namespace": NAMESPACE, "mode": "announcements", "sampleRate": rate,
                "channels": 1, "voiceId": "matthew-whole-intercom-room", "engine": provider,
                "voice": "Matthew", "nativeRatePercent": 100, "processing": processing,
                "license": {**LICENSE, "provider": provider}, "sourceMapSha256": digest(map_path),
                "sourceMapMetadata": {key: value for key, value in source_map.items() if key != "announcements"},
                "announcements": {}}
    montage_parts, schedule, cursor = [], [], 0
    gap = round(rate * 0.35)
    for entry in entries:
        natural, provenance = dsp.prepare(entry, map_path)
        dry = dsp.speaker_eq(natural)
        level = dsp.active_rms(dry)
        gain = float(np.clip(target_rms / level, 10 ** (-3 / 20), 10 ** (3 / 20)))
        wet = dsp.facility_room(dry)
        level_match_gain = min(gain, 0.85 / max(float(np.max(np.abs(wet))), 1e-9))
        headroom_gain = min(1.0, 0.95 / max(float(np.max(np.abs(wet))) * level_match_gain * master_gain, 1e-9))
        gain = level_match_gain * master_gain * headroom_gain
        source_peak = float(np.max(np.abs(wet * gain)))
        if source_peak > 0.95 + 1e-12:
            raise ValueError(f"Source peak exceeds headroom for {entry['id']}")
        relative = f"assets/{NAMESPACE}/sounds/pa/{entry['id']}.ogg"
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoder.write(destination, wet * gain)
        decoded = encoder.read(destination)
        if not np.isfinite(decoded).all() or np.max(np.abs(decoded)) >= 0.99:
            raise ValueError(f"Invalid exported announcement {entry['id']}")
        record = {"text": entry["text"], "event": f"{NAMESPACE}:pa.{entry['id']}", "file": relative,
                  "speechMs": round(len(natural) / rate * 1000, 3), "durationMs": round(len(decoded) / rate * 1000, 3),
                  "ticks": math.ceil(len(decoded) * 20 / rate), "sha256": digest(destination), "bytes": destination.stat().st_size,
                  "frames": len(decoded), "linearGain": gain, "levelMatchGain": level_match_gain,
                  "masterGain": master_gain, "masterHeadroomGain": headroom_gain, "sourcePeak": source_peak,
                  "activeRmsBefore": level, "peak": float(np.max(np.abs(decoded))),
                  "rms": float(np.sqrt(np.mean(decoded ** 2))), "source": provenance,
                  "sourceMetadata": {key: value for key, value in entry.items() if key not in ("id", "text", "source")}}
        manifest["announcements"][entry["id"]] = record
        preview = ROOT / "previews" / f"preview-whole-matthew-{entry['id']}-intercom-room-{preview_tag}.wav"
        preview.parent.mkdir(parents=True, exist_ok=True)
        audio.base.write_wave(preview, decoded)
        schedule.append({"id": entry["id"], "event": record["event"], "startMs": round(cursor / rate * 1000, 3),
                         "durationMs": record["durationMs"], "gain": 1})
        montage_parts.extend((decoded, np.zeros(gap)))
        cursor += len(decoded) + gap
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    montage = np.concatenate(montage_parts)
    montage_name = f"preview-turbine-announcements-intercom-montage-{preview_tag}"
    audio.base.write_wave(ROOT / "previews" / f"{montage_name}.wav", montage)
    encoder.write(ROOT / "previews" / f"{montage_name}.ogg", montage)
    (ROOT / "previews" / f"{montage_name}.json").write_text(json.dumps({"reviewMontage": True,
        "reviewPauseMs": 350, "volume": 1, "masterGain": master_gain, "schedule": schedule,
        "durationMs": round(len(montage) / rate * 1000, 3), "peak": float(np.max(np.abs(montage)))}, indent=2) + "\n", encoding="utf-8")
    report = {"sourceMap": str(map_path), "sourceMapSha256": digest(map_path), "pitchDsp": False,
              "waveformSpeedDsp": False, "wholeMessage": True, "previewVolume": 1, "masterGain": master_gain,
              "previewTag": preview_tag, "clips": len(entries), "sampleRate": rate,
              "oggBytes": sum(entry["bytes"] for entry in manifest["announcements"].values()),
              "announcements": manifest["announcements"]}
    (ROOT / "audio-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, default=ROOT / "source-map.json")
    parser.add_argument("--preview-tag", default="v21")
    args = parser.parse_args()
    render(args.source_map.resolve(), args.preview_tag)
