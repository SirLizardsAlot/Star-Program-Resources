"""Export continuous Matthew announcements with room or subtle speaker shaping."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import audio_helpers as audio

np, RATE, ROOT = audio.np, audio.RATE, audio.ROOT
ROOM = {"tailMs": 650, "predelayMs": 25, "wet": 0.17, "decayMs": 180, "seed": 4118}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_rms(values, window_ms=20, hop_ms=5):
    window, hop = round(RATE * window_ms / 1000), round(RATE * hop_ms / 1000)
    sums = np.concatenate(([0.0], np.cumsum(values * values)))
    starts = np.arange(0, len(values) - window + 1, hop)
    return np.sqrt(np.maximum(0, (sums[starts + window] - sums[starts]) / window)), window, hop


def trim_padding(values):
    rms, window, hop = frame_rms(values, 5, 2.5)
    threshold = max(0.00015, float(np.max(rms)) * 0.004)
    active = np.flatnonzero(rms > threshold)
    if not len(active):
        raise ValueError("Announcement has no speech")
    start = max(0, int(active[0] * hop) - round(RATE * 0.010))
    end = min(len(values), int(active[-1] * hop + window) + round(RATE * 0.020))
    return values[start:end], {"leadingMs": round(start / RATE * 1000, 3),
        "trailingMs": round((len(values) - end) / RATE * 1000, 3), "thresholdRms": threshold}


def active_rms(values):
    levels, window, hop = frame_rms(values)
    threshold = max(0.003, float(np.percentile(levels, 90)) * 0.15)
    active = levels[levels > threshold]
    if not len(active):
        raise ValueError("Announcement is too quiet")
    return float(np.median(active))


def speaker_eq(values):
    # Smooth spectral tilt, preserving bass and consonants; no narrow telephone
    # band and no added distortion. Padding avoids circular wraparound.
    padding = round(RATE * 0.20)
    padded = np.pad(values, (padding, padding))
    nfft = 1 << math.ceil(math.log2(len(padded)))
    frequencies = np.fft.rfftfreq(nfft, 1 / RATE)
    high_pass = frequencies / np.sqrt(frequencies ** 2 + 90 ** 2)
    low_pass = 1 / np.sqrt(1 + (frequencies / 6500) ** 4)
    presence = 10 ** (0.75 / 20 * np.exp(-0.5 * (np.log2(np.maximum(frequencies, 1) / 1800) / 1.25) ** 2))
    shaped = np.fft.irfft(np.fft.rfft(padded, nfft) * high_pass * low_pass * presence, nfft)
    return shaped[padding:padding + len(values)]


def facility_room(values):
    count, offset = round(RATE * ROOM["tailMs"] / 1000), round(RATE * ROOM["predelayMs"] / 1000)
    rng = np.random.default_rng(ROOM["seed"])
    ir = np.zeros(count)
    noise = np.convolve(rng.normal(size=count - offset), np.ones(5) / 5, mode="same")
    ir[offset:] = noise * np.exp(-np.arange(count - offset) / RATE / (ROOM["decayMs"] / 1000))
    ir /= np.sqrt(np.sum(ir * ir))
    nfft = 1 << math.ceil(math.log2(len(values) + len(ir) - 1))
    wet = np.fft.irfft(np.fft.rfft(values, nfft) * np.fft.rfft(ir, nfft), nfft)[:len(values) + len(ir) - 1]
    return np.pad(values, (0, len(ir) - 1)) + wet * ROOM["wet"]


def prepare(entry, map_path):
    source = Path(entry["source"])
    if not source.is_absolute():
        source = map_path.parent / source
    digest = sha(source)
    if entry.get("sourceSha256") and digest != entry["sourceSha256"]:
        raise ValueError(f"Source hash mismatch: {source}")
    copied = ROOT / "sources" / source.name
    copied.parent.mkdir(parents=True, exist_ok=True)
    if copied.resolve() != source.resolve():
        if copied.exists() and sha(copied) != digest:
            raise ValueError(f"Conflicting source basename {source.name}")
        shutil.copyfile(source, copied)
    raw, source_rate, info = audio.decode_mp3(copied)
    dry, trimming = trim_padding(audio.resample(raw, source_rate))
    if not np.isfinite(dry).all() or float(np.max(np.abs(dry))) < 0.01:
        raise ValueError("Invalid source audio")
    return dry, {"file": "sources/" + copied.name, "sha256": digest, "bytes": copied.stat().st_size,
        "sourceRate": source_rate, "decodedFrames": info["decodedFrames"], "trimming": trimming,
        "requestText": entry["text"], "originalDownloadFilename": entry.get("originalDownloadFilename", copied.name)}


def render(map_path, effect, target_rms=0.075, preview_volume=0.8, master_gain=1.0, preview_tag=""):
    if not math.isfinite(master_gain) or master_gain <= 0:
        raise ValueError("Master gain must be positive and finite")
    if not re.fullmatch(r"[a-z0-9_-]*", preview_tag):
        raise ValueError("Preview tag must be a lowercase identifier")
    suffix = "-" + preview_tag if preview_tag else ""
    source_map = json.loads(map_path.read_text(encoding="utf-8"))
    entries = source_map["announcements"]
    ids = [entry["id"] for entry in entries]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z0-9_]+", key) for key in ids):
        raise ValueError("Announcement IDs must be unique lowercase identifiers")
    encoder = audio.HighQualityEncoder(audio.AUDACITY / "sndfile.dll")
    prepared = [(entry, *prepare(entry, map_path)) for entry in entries]
    effects = ("clear", "intercom") if effect == "compare" else (effect,)
    results = {}
    for flavor in effects:
        destination = ROOT / "variants" / flavor if effect == "compare" else ROOT
        manifest = {"version": 1, "namespace": "star_program", "mode": "announcements", "sampleRate": RATE, "channels": 1,
            "voiceId": f"matthew-whole-{flavor}-room",
            "engine": "ttsMP3 members UI / Matthew", "voice": "Matthew", "nativeRatePercent": source_map.get("ratePercent", 100),
            "processing": {"effect": flavor, "pitchDsp": False, "waveformSpeedDsp": False, "vorbisQuality": 0.65,
                "room": ROOM, "levelTargetActiveRms": target_rms, "linearGainBoundDb": 3,
                "masterGain": master_gain, "masterGainDb": round(20 * math.log10(master_gain), 6),
                "normalizationPeakCeiling": 0.85, "masterPeakCeiling": 0.95,
                "peakGuard": "Original0.85normalization ceiling;post-master constant attenuation only if needed for0.95source peak;no limiter/saturation",
                "speakerEq": "none" if flavor == "clear" else "90Hz gentle highpass,6500Hz soft lowpass,+0.75dB broad1800Hz presence",
                "timing": "ticks=ceil(full decoded duration/50ms), including room tail"}, "announcements": {}}
        for entry, natural, provenance in prepared:
            dry = speaker_eq(natural) if flavor == "intercom" else natural
            level = active_rms(dry)
            gain = float(np.clip(target_rms / level, 10 ** (-3 / 20), 10 ** (3 / 20)))
            wet = facility_room(dry)
            level_match_gain = min(gain, 0.85 / max(float(np.max(np.abs(wet))), 1e-9))
            headroom_gain = min(1.0, 0.95 / max(float(np.max(np.abs(wet))) * level_match_gain * master_gain, 1e-9))
            gain = level_match_gain * master_gain * headroom_gain
            source_peak = float(np.max(np.abs(wet * gain)))
            if source_peak > 0.95 + 1e-12:
                raise ValueError(f"Source peak exceeds headroom for {entry['id']}")
            relative = f"assets/star_program/sounds/announcements/{entry['id']}.ogg"
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            encoder.write(path, wet * gain)
            decoded = encoder.read(path)
            if not np.isfinite(decoded).all() or np.max(np.abs(decoded)) >= 0.99:
                raise ValueError(f"Invalid exported announcement {entry['id']}")
            duration = len(decoded) / RATE * 1000
            record = {"text": entry["text"], "aliases": entry.get("aliases", []),
                "event": f"star_program:announcement.{entry['id']}", "file": relative,
                "speechMs": round(len(natural) / RATE * 1000, 3), "durationMs": round(duration, 3),
                "ticks": math.ceil(len(decoded) * 20 / RATE), "sha256": sha(path), "bytes": path.stat().st_size,
                "linearGain": gain, "levelMatchGain": level_match_gain, "masterGain": master_gain,
                "masterHeadroomGain": headroom_gain, "sourcePeak": source_peak,
                "activeRmsBefore": level, "peak": float(np.max(np.abs(decoded))),
                "rms": float(np.sqrt(np.mean(decoded ** 2))),
                "channels": entry.get("channels", []),
                "source": {**provenance, "file": os.path.relpath(ROOT / provenance["file"], destination)}}
            manifest["announcements"][entry["id"]] = record
            preview = ROOT / "previews" / f"preview-whole-matthew-{entry['id']}-{flavor}-room{suffix}.wav"
            audio.base.write_wave(preview, decoded * preview_volume)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        results[flavor] = {"manifest": str((destination / "manifest.json").relative_to(ROOT)),
            "clips": len(manifest["announcements"]), "oggBytes": sum(row["bytes"] for row in manifest["announcements"].values()),
            "announcements": manifest["announcements"]}
        if effect != "compare":
            gap = round(RATE * 0.35)
            montage_parts = []
            montage_schedule, cursor = [], 0
            for key, entry in manifest["announcements"].items():
                decoded = encoder.read(destination / entry["file"]) * preview_volume
                montage_schedule.append({"id": key, "event": entry["event"], "startMs": round(cursor / RATE * 1000, 3),
                                         "durationMs": entry["durationMs"], "gain": preview_volume})
                montage_parts.extend((decoded, np.zeros(gap)))
                cursor += len(decoded) + gap
            montage = np.concatenate(montage_parts)
            montage_name = f"preview-announcements-{flavor}-montage{suffix}"
            audio.base.write_wave(ROOT / "previews" / f"{montage_name}.wav", montage)
            encoder.write(ROOT / "previews" / f"{montage_name}.ogg", montage)
            (ROOT / "previews" / f"{montage_name}.json").write_text(json.dumps({"reviewMontage": True,
                "reviewPauseMs": 350, "volume": preview_volume, "masterGain": master_gain, "schedule": montage_schedule,
                "durationMs": round(len(montage) / RATE * 1000, 3), "peak": float(np.max(np.abs(montage)))}, indent=2) + "\n")
    report = {"sourceMap": str(map_path), "pitchDsp": False, "wholeMessage": True, "previewVolume": preview_volume,
        "masterGain": master_gain, "previewTag": preview_tag, "sourceMapSha256": sha(map_path), "effects": results}
    (ROOT / ("comparison-report.json" if effect == "compare" else "audio-report.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, default=ROOT / "source-map.json")
    parser.add_argument("--effect", choices=("compare", "clear", "intercom"), default="intercom")
    parser.add_argument("--target-rms", type=float, default=0.075)
    parser.add_argument("--preview-volume", type=float, default=0.8)
    parser.add_argument("--master-gain", type=float, default=1.0,
                        help="Uniform gain after the original clip matching;1 reproduces original level")
    parser.add_argument("--preview-tag", default="", help="Unique suffix for preview filenames")
    args = parser.parse_args()
    render(args.source_map, args.effect, args.target_rms, args.preview_volume, args.master_gain, args.preview_tag)
