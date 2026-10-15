"""Build compact, positional turbine sounds from preserved CC0 source audio.

This stages a separate resource-pack overlay and audition files. It never writes
the published pack, game configuration, portal, or the original recordings.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import wave
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parent
RATE = 32000
NAMESPACE = "star_program_turbines"
LIMIT = 40 * 1024 * 1024


class AudioIO:
    class Info(C.Structure):
        _fields_ = [("frames", C.c_int64), ("samplerate", C.c_int), ("channels", C.c_int),
                    ("format", C.c_int), ("sections", C.c_int), ("seekable", C.c_int)]

    def __init__(self, dll):
        self.dll_directory = os.add_dll_directory(str(dll.parent)) if os.name == "nt" else None
        self.lib = C.CDLL(str(dll))
        self.lib.sf_wchar_open.argtypes = [C.c_wchar_p, C.c_int, C.POINTER(self.Info)]
        self.lib.sf_wchar_open.restype = C.c_void_p
        for method in ("sf_readf_float", "sf_writef_float"):
            fn = getattr(self.lib, method)
            fn.argtypes = [C.c_void_p, C.POINTER(C.c_float), C.c_int64]
            fn.restype = C.c_int64
        self.lib.sf_close.argtypes = [C.c_void_p]
        self.lib.sf_command.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int]

    def read(self, path):
        info = self.Info()
        handle = self.lib.sf_wchar_open(str(path), 0x10, C.byref(info))
        if not handle:
            raise ValueError(f"Cannot decode {path}")
        try:
            data = np.empty((info.frames, info.channels), dtype=np.float32)
            count = self.lib.sf_readf_float(handle, data.ctypes.data_as(C.POINTER(C.c_float)), info.frames)
            if count != info.frames or not np.isfinite(data).all():
                raise ValueError(f"Invalid decoded samples: {path}")
            return data.astype(np.float64), info.samplerate
        finally:
            self.lib.sf_close(handle)

    def write(self, path, data, quality=0.32):
        path.parent.mkdir(parents=True, exist_ok=True)
        info = self.Info(0, RATE, 1, 0x200060, 0, 0)  # Ogg Vorbis, mono.
        handle = self.lib.sf_wchar_open(str(path), 0x20, C.byref(info))
        if not handle:
            raise ValueError(f"Cannot encode {path}")
        try:
            q = C.c_double(quality)
            self.lib.sf_command(handle, 0x1300, C.byref(q), C.sizeof(q))
            data = np.asarray(data, dtype=np.float32)
            count = self.lib.sf_writef_float(handle, data.ctypes.data_as(C.POINTER(C.c_float)), len(data))
            if count != len(data):
                raise ValueError(f"Incomplete encode: {path}")
        finally:
            self.lib.sf_close(handle)
        normalize_ogg(path, hashlib.sha256(data.tobytes()).digest()[:4])


def normalize_ogg(path, serial):
    """Normalize stream serials and Ogg page CRCs for reproducible outputs."""
    table = []
    for value in range(256):
        crc = value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
        table.append(crc)
    data = bytearray(path.read_bytes())
    cursor = 0
    while cursor < len(data):
        if data[cursor:cursor + 4] != b"OggS":
            raise ValueError(f"Invalid Ogg page at {cursor}")
        segments = data[cursor + 26]
        size = 27 + segments + sum(data[cursor + 27:cursor + 27 + segments])
        data[cursor + 14:cursor + 18] = serial
        data[cursor + 22:cursor + 26] = b"\0" * 4
        crc = 0
        for value in data[cursor:cursor + size]:
            crc = ((crc << 8) ^ table[((crc >> 24) ^ value) & 255]) & 0xFFFFFFFF
        data[cursor + 22:cursor + 26] = crc.to_bytes(4, "little")
        cursor += size
    if cursor != len(data):
        raise ValueError("Truncated Ogg page")
    path.write_bytes(data)


def filtered(data, rate=RATE, highpass=35, lowpass=11000):
    data = data - np.mean(data)
    frequencies = np.fft.rfftfreq(len(data), 1 / rate)
    high = (frequencies / highpass) ** 2
    gain = high / (1 + high) / np.sqrt(1 + (frequencies / lowpass) ** 8)
    return np.fft.irfft(np.fft.rfft(data) * gain, n=len(data))


def load(io, path):
    data, rate = io.read(path)
    # Mono exports allow Minecraft to position the turbine/vent in the room.
    mono = np.mean(data, axis=1)
    mono = filtered(mono, rate, 32, min(11000, RATE * 0.43, rate * 0.43))
    count = round(len(mono) * RATE / rate)
    return np.interp(np.arange(count) * rate / RATE, np.arange(len(mono)), mono)


def rms(data):
    return float(np.sqrt(np.mean(data * data)))


def level(data, target=0.115, peak=0.80):
    data = data - np.mean(data)
    return data * min(target / max(rms(data), 1e-9), peak / max(float(np.max(np.abs(data))), 1e-9))


def fade(data, attack=0.02, release=0.04):
    data = data.copy()
    for seconds, end in ((attack, False), (release, True)):
        count = min(round(seconds * RATE), len(data) // 2)
        if count:
            curve = np.sin(np.linspace(0, np.pi / 2, count)) ** 2
            if end:
                data[-count:] *= curve[::-1]
            else:
                data[:count] *= curve
    return data


def stable_window(data, seconds, speed=1.0):
    count = math.ceil(seconds * RATE * speed) + 2
    if count >= len(data):
        raise ValueError("Source too short for requested stable window")
    candidates = []
    room = len(data) - count
    starts = sorted(set([0, room // 2, room - 1] + list(range(
        min(round(0.5 * RATE), room // 10), room, max(1, min(round(0.25 * RATE), room // 10))))))
    for start in starts:
        part = data[start:start + count]
        step = max(128, min(round(0.15 * RATE), count // 8))
        envelope = np.array([rms(part[i:i + step]) for i in range(0, len(part) - step, step)])
        if len(envelope) < 4 or np.mean(envelope) < 0.005:
            continue
        score = np.std(envelope) / np.mean(envelope)
        score += max(0, 0.035 - np.mean(envelope)) * 10
        candidates.append((score, start))
    if not candidates:
        raise ValueError("No stable, audible source region")
    _, start = min(candidates)
    positions = np.arange(round(seconds * RATE)) * speed + start
    part = np.interp(positions, np.arange(len(data)), data)
    return part, {"startSeconds": round(start / RATE, 5), "sourceSpeed": speed,
                  "sourceSeconds": round(seconds * speed, 5)}


def seamless(data, seconds, overlap=0.35):
    count, cross = round(seconds * RATE), round(overlap * RATE)
    if len(data) < count + cross:
        raise ValueError("Missing overlap samples")
    # The tail ends at the sample immediately before the retained head begins.
    # Smooth equal-power crossfade conceals the internal transition without a
    # fade to silence every time the resulting loop wraps.
    angle = np.linspace(0, np.pi / 2, cross)
    mixed = data[count:count + cross] * np.cos(angle) + data[:cross] * np.sin(angle)
    return filtered(np.concatenate([data[cross:count], mixed]))


def spun(loop, seconds, start_speed, end_speed):
    t = np.linspace(0, 1, round(seconds * RATE))
    smooth = t * t * (3 - 2 * t)
    speeds = start_speed + (end_speed - start_speed) * smooth
    positions = np.cumsum(speeds) % len(loop)
    return np.interp(positions, np.arange(len(loop) + 1), np.r_[loop, loop[0]])


def active_segments(data):
    """Separate chained steam bursts using 10 ms RMS gates and silence gaps."""
    step = round(0.01 * RATE)
    envelope = np.array([rms(data[i:i + step]) for i in range(0, len(data), step)])
    threshold = max(float(np.max(envelope)) * 0.025, 0.0006)
    active = np.flatnonzero(envelope > threshold)
    if not len(active):
        return []
    groups = np.split(active, np.flatnonzero(np.diff(active) > 18) + 1)
    result = []
    for group in groups:
        start = max(0, int(group[0] * step) - round(0.025 * RATE))
        end = min(len(data), int((group[-1] + 1) * step) + round(0.07 * RATE))
        if end - start >= round(0.10 * RATE):
            result.append((start, end))
    return result


def write_wav(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build(args):
    io = AudioIO(args.sndfile)
    source = ROOT / "source"
    original_hashes = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob("*") if p.is_file()}
    turbine_path = source / "453476_kyles_industrial_turbine_hq_preview.ogg"
    startup_path = source / "491407_samsterbirdies_jet_engine_startup_hq_preview.ogg"
    groan_path = source / "785570_genghisattenborough_groaning_turbine_hq_preview.ogg"
    turbine, startup, groan = [load(io, p) for p in (turbine_path, startup_path, groan_path)]
    asset_root = ROOT / "assets" / NAMESPACE
    sounds, manifest, decoded = {}, {}, {}

    def emit(name, data, loop=False, provenance=None, description="", target=0.115):
        if not loop:
            data = fade(data)
        data = level(data, target)
        relative = f"sounds/{name.replace('.', '/')}.ogg"
        path = asset_root / relative
        io.write(path, data)
        check, check_rate = io.read(path)
        check = check[:, 0]
        if check_rate != RATE or len(check) != len(data):
            raise ValueError(f"Rate/frame mismatch in {name}")
        if np.max(np.abs(check)) >= 0.98 or rms(check) < 0.008:
            raise ValueError(f"Clipped or silent export: {name}")
        boundary = abs(float(check[-1] - check[0]))
        steps95 = float(np.percentile(np.abs(np.diff(check)), 95))
        if loop and boundary > max(0.018, steps95 * 1.5):
            raise ValueError(f"Loop boundary too abrupt: {name}: {boundary}")
        sounds[name] = {"sounds": [{"name": f"{NAMESPACE}:{name.replace('.', '/')}", "stream": False}]}
        manifest[name] = {
            "event": f"{NAMESPACE}:{name}", "file": f"assets/{NAMESPACE}/{relative}",
            "description": description, "loop": loop, "durationSeconds": round(len(check) / RATE, 5),
            "durationTicks": round(len(check) / RATE * 20, 5), "sampleRate": RATE,
            "channels": 1, "peakDbFS": round(20 * math.log10(float(np.max(np.abs(check)))), 3),
            "rmsDbFS": round(20 * math.log10(rms(check)), 3), "bytes": path.stat().st_size,
            "sha256": sha(path), "loopBoundaryStep": round(boundary, 7),
            "adjacentStep95": round(steps95, 7), "processing": provenance,
        }
        decoded[name] = check

    rotor_loops = {}
    for name, speed, target in (("idle", 0.64, 0.095), ("running", 0.88, 0.115), ("high_load", 0.88, 0.135)):
        part, selection = stable_window(turbine, 6.35, speed)
        rotor = level(seamless(part, 6.0), target)
        low, low_selection = stable_window(groan, 6.35, 0.82)
        low = level(filtered(seamless(low, 6.0), lowpass=380), target=0.06)
        # Electrical load adds body/level without falsely implying a large RPM
        # increase once connected to the grid. Runtime pitch can track actual RPM.
        body_gain = {"idle": 0.12, "running": 0.20, "high_load": 0.42}[name]
        combined = rotor + low * body_gain
        emit(f"turbine.{name}_loop", combined, True,
             {"source": turbine_path.name, "selection": selection, "bodySource": groan_path.name,
              "bodySelection": low_selection, "bodyGain": body_gain, "crossfadeSeconds": 0.35},
             f"Six-second {name.replace('_', ' ')} rotor loop; no fade-to-silence at wrap.", target=target)
        rotor_loops[name] = decoded[f"turbine.{name}_loop"]

    body_part, body_selection = stable_window(groan, 4.35, 0.75)
    vibration = level(filtered(seamless(body_part, 4.0), lowpass=1250), 0.10)
    vibration *= 0.82 + 0.18 * np.cos(np.arange(len(vibration)) / RATE * 2 * np.pi * 7)
    emit("turbine.vibration_loop", vibration, True,
         {"source": groan_path.name, "selection": body_selection, "crossfadeSeconds": 0.35,
          "modulationHz": 7}, "Optional mechanical-stress layer; mix quietly over the rotor.", target=0.075)

    # Rotor-derived acceleration and deceleration keep the basic machine tone
    # consistent through the transitions; the approved jet adds a restrained whine.
    length = 14.0
    jet = startup
    bins = np.array([rms(jet[i:i + RATE // 10]) for i in range(0, len(jet), RATE // 10)])
    active = np.flatnonzero(bins > max(bins) * 0.035)
    jet_start = max(0, active[0] * RATE // 10 - RATE // 10)
    jet_end = min(len(jet), (active[-1] + 1) * RATE // 10)
    jet = np.interp(np.linspace(jet_start, jet_end - 1, round(length * RATE)), np.arange(len(jet)), jet)
    jet = level(filtered(jet, highpass=180, lowpass=6500), 0.07)
    rotor = spun(rotor_loops["running"], length, 0.25, 1.0)
    ramp = np.linspace(0, 1, len(rotor))
    start_sound = rotor * (0.12 + 0.88 * ramp ** 0.65) + fade(jet, 0.8, 2.5) * 0.24
    emit("turbine.startup", fade(start_sound, 0.3, 0.35), provenance={
        "rotor": "turbine.running_loop", "whineSource": startup_path.name,
        "sourceTrimSeconds": [round(jet_start / RATE, 4), round(jet_end / RATE, 4)],
        "rotorSpeedRange": [0.25, 1.0]}, description="Fourteen-second rotor acceleration with restrained startup whine.")

    coast = spun(rotor_loops["running"], 12.0, 1.0, 0.15)
    coast *= np.linspace(1, 0, len(coast)) ** 0.7
    emit("turbine.coastdown", fade(coast, 0.08, 1.0), provenance={
        "rotor": "turbine.running_loop", "rotorSpeedRange": [1.0, 0.15]},
        description="Twelve-second mechanical coastdown, derived from the running rotor.")

    trip = spun(rotor_loops["running"], 3.5, 1.05, 0.25)
    trip *= np.linspace(1, 0, len(trip)) ** 0.5
    emit("turbine.trip", fade(trip, 0.01, 0.8), provenance={
        "rotor": "turbine.running_loop", "rotorSpeedRange": [1.05, 0.25]},
        description="Short emergency deceleration cue; play a separate steam release alongside it.")

    steam_names = []
    for path in sorted((source / "steam_originals").glob("*.wav")):
        data = load(io, path)
        for start, end in active_segments(data):
            name = f"steam.release_{len(steam_names) + 1:02d}"
            emit(name, fade(data[start:end], 0.006, 0.025), provenance={
                "source": path.relative_to(source).as_posix(),
                "sourceTrimSeconds": [round(start / RATE, 5), round(end / RATE, 5)],
                "split": "10ms RMS, -32dB relative gate, 180ms silence separation"},
                description="One isolated steam release; surrounding silence removed.")
            steam_names.append(name)
    if len(steam_names) < 5:
        raise ValueError("Expected at least five isolated steam releases")

    # Give steam a compact continuous state as well as independent one-shots.
    longest = max(steam_names, key=lambda name: len(decoded[name]))
    steam = decoded[longest]
    seconds = min(1.0, (len(steam) / RATE - 0.12) * 0.55)
    seconds = math.floor(seconds * 20) / 20
    if seconds >= 0.25:
        steam_part, steam_selection = stable_window(steam, seconds + 0.08)
        emit("steam.flow_loop", seamless(steam_part, seconds, 0.08), True,
             {"derivedFrom": longest, "selection": steam_selection, "crossfadeSeconds": 0.08},
             "Short continuous steam-flow layer for an open intake valve.")

    # Preserve a separately named alternative from the coherent mechanical set.
    # These are optional and do not duplicate the main turbine state sounds.
    for state in ("start", "end"):
        path = source / f"jwiese_engine_{state}_original.flac"
        if path.exists():
            part = load(io, path)
            part = np.interp(np.arange(round(len(part) / 0.8)) * 0.8, np.arange(len(part)), part)
            emit(f"auxiliary.{state}", part, provenance={"source": path.name, "sourceSpeed": 0.8},
                 description="Slowed mechanical transition from the matching alternative set.", target=0.09)
    path = source / "jwiese_engine_loop_original.flac"
    if path.exists():
        part, selection = stable_window(load(io, path), 1.6, 0.8)
        emit("auxiliary.running_loop", seamless(part, 1.5, 0.1), True,
             {"source": path.name, "selection": selection, "crossfadeSeconds": 0.1},
             "Optional 1.5-second mechanical loop from the matching alternative set.", target=0.09)

    write_json(asset_root / "sounds.json", sounds)
    write_json(ROOT / "manifest.json", {"version": 1, "namespace": NAMESPACE, "sampleRate": RATE,
        "vorbisQuality": 0.32, "sources": original_hashes, "sounds": manifest})
    make_previews(decoded, steam_names)
    source_metadata = json.loads((source / "sources.json").read_text(encoding="utf-8"))
    credits = ["STAR PROGRAM - turbine audio", "", "Sources licensed CC0-1.0; credits retained voluntarily.",
               "License: https://creativecommons.org/publicdomain/zero/1.0/", ""]
    for row in source_metadata["sources"]:
        credits.extend([f'{row["title"]} - {row["creator"]}', row["page_url"], ""])
    credits.extend(["Freesound inputs use the public HQ OGG previews; authenticated originals were not used.",
                    "Steam WAVs and the alternative mechanical FLAC set are original public attachments.",
                    "Edited into mono Vorbis assets at 32 kHz. Raw sources and WAV previews are not included in the pack."])
    (ROOT / "CREDITS.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")
    package(manifest, args.base_pack)
    for name, digest in original_hashes.items():
        if sha(source / name) != digest:
            raise ValueError(f"Source changed during build: {name}")
    print(json.dumps({"sounds": len(manifest), "steamReleases": len(steam_names),
                      "oggBytes": sum(row["bytes"] for row in manifest.values()),
                      "preview": str(ROOT / "previews" / "turbine_sequence.wav")}, indent=2))


def make_previews(clips, steam_names):
    root = ROOT / "previews"
    sequence = [("turbine.startup", 1), ("turbine.running_loop", 2),
                ("turbine.high_load_loop", 1), ("turbine.coastdown", 1)]
    assembled, timeline = None, []
    for name, repeats in sequence:
        part = np.tile(clips[name], repeats)
        if assembled is None:
            assembled = part.copy()
            timeline.append({"sound": name, "startSeconds": 0})
        else:
            overlap = round(0.35 * RATE)
            start = len(assembled) - overlap
            angle = np.linspace(0, np.pi / 2, overlap)
            joined = assembled[-overlap:] * np.cos(angle) + part[:overlap] * np.sin(angle)
            assembled = np.concatenate([assembled[:-overlap], joined, part[overlap:]])
            timeline.append({"sound": name, "startSeconds": round(start / RATE, 3)})
    write_wav(root / "turbine_sequence.wav", assembled)
    write_json(root / "turbine_sequence_cues.json", timeline)
    # Two full cycles make the loop boundary audible for auditioning.
    for name in ("turbine.idle_loop", "turbine.running_loop", "turbine.high_load_loop", "turbine.vibration_loop"):
        write_wav(root / f"{name.replace('.', '_')}_twice.wav", np.tile(clips[name], 2))
    if "auxiliary.running_loop" in clips:
        auxiliary = clips["auxiliary.start"].copy()
        overlap = round(0.12 * RATE)
        angle = np.linspace(0, np.pi / 2, overlap)
        for part in (np.tile(clips["auxiliary.running_loop"], 4), clips["auxiliary.end"]):
            joined = auxiliary[-overlap:] * np.cos(angle) + part[:overlap] * np.sin(angle)
            auxiliary = np.concatenate([auxiliary[:-overlap], joined, part[overlap:]])
        write_wav(root / "alternative_mechanical_set.wav", auxiliary)
    silence = np.zeros(round(RATE * 0.6))
    montage, cues, cursor = [], [], 0
    for name in steam_names:
        cues.append({"sound": name, "startSeconds": round(cursor / RATE, 5),
                     "durationSeconds": round(len(clips[name]) / RATE, 5)})
        montage.extend([clips[name], silence])
        cursor += len(clips[name]) + len(silence)
    write_wav(root / "steam_releases.wav", np.concatenate(montage))
    write_json(root / "steam_cues.json", cues)


def package(manifest, base_pack):
    payload = {}
    for path in (ROOT / "assets").rglob("*"):
        if path.is_file():
            payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    # Ship the small provenance manifest and credits, never raw source media or WAV previews.
    for name in ("manifest.json", "CREDITS.txt"):
        path = ROOT / name
        if path.exists():
            payload[f"turbine-audio/{name}"] = path.read_bytes()
    overlay = ROOT / "turbine-audio-overlay.zip"
    meta = {"pack": {"description": "STAR PROGRAM turbine audio preview", "pack_format": 88,
                     "min_format": [88, 0], "max_format": [88, 0]}}
    write_archive(overlay, {**payload, "pack.mcmeta": (json.dumps(meta, indent=2) + "\n").encode()})
    report = {"overlayBytes": overlay.stat().st_size, "audioBytes": sum(row["bytes"] for row in manifest.values()),
              "soundCount": len(manifest), "sizeLimitBytes": LIMIT, "checks": {}}
    if base_pack is not None:
        base_hash = sha(base_pack)
        with zipfile.ZipFile(base_pack) as archive:
            if archive.testzip() is not None:
                raise ValueError("Base pack CRC failed")
            original = {entry.filename: archive.read(entry) for entry in archive.infolist()}
        collisions = set(original) & set(payload)
        if collisions:
            raise ValueError(f"Refusing to overwrite existing assets: {collisions}")
        candidate = ROOT / f"{base_pack.stem}-turbine-preview.zip"
        write_archive(candidate, {**original, **payload})
        if candidate.stat().st_size > LIMIT:
            raise ValueError("Candidate exceeds the DiamondFire 40 MiB limit")
        with zipfile.ZipFile(candidate) as archive:
            assert archive.testzip() is None
            for path, contents in original.items():
                if archive.read(path) != contents:
                    raise ValueError(f"Existing pack asset changed: {path}")
            for path in payload:
                if path.endswith(".json"):
                    json.loads(archive.read(path))
        if sha(base_pack) != base_hash:
            raise ValueError("Base pack was changed")
        report.update({"basePack": str(base_pack), "baseSha256": base_hash,
                       "candidate": str(candidate), "candidateBytes": candidate.stat().st_size,
                       "candidateMiB": round(candidate.stat().st_size / 1024 ** 2, 4),
                       "remainingMiB": round((LIMIT - candidate.stat().st_size) / 1024 ** 2, 4),
                       "candidateSha256": sha(candidate)})
        report["checks"].update({"existingAssetsByteIdentical": True, "baseUnchanged": True,
                                "candidateCrc": True, "below40MiB": True})
    report["checks"].update({"decodedMonoVorbis": True, "noClippingOrSilentFiles": True,
                            "loopBoundariesCheckedAfterEncoding": True})
    write_json(ROOT / "build-report.json", report)


def write_archive(path, files):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, contents, compresslevel=9)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sndfile", type=Path, default=Path(r"C:\Program Files\Audacity\sndfile.dll"))
    parser.add_argument("--base-pack", type=Path)
    build(parser.parse_args())
