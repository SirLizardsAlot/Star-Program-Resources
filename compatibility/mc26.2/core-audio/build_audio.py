"""Downmix the six inherited core recordings for positional Minecraft playback.

Only channel layout changes. The preserved v21 originals, frame counts, sample
rates, event registrations, and all unrelated resources remain untouched.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np

ROOT = Path(__file__).resolve().parent
PACK_ROOT = ROOT.parent
sys.path.insert(0, str(PACK_ROOT))
from core_audio_overlay import (EVENT_PATHS, SOURCE_HASHES, PREVIOUS_SHA256,
                                POWERSWITCH_PATH, POWERSWITCH_SHA256, vorbis_info)

spec = importlib.util.spec_from_file_location("prepared_audio_io", PACK_ROOT / "turbines/build_audio.py")
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)
QUALITY = 0.5


def write_mono(io, path, samples, rate):
    """Use the shared encoder while retaining each source's native sample rate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    info = io.Info(0, rate, 1, 0x200060, 0, 0)
    handle = io.lib.sf_wchar_open(str(path), 0x20, C.byref(info))
    if not handle:
        raise ValueError(f"Cannot encode {path}")
    try:
        quality = C.c_double(QUALITY)
        io.lib.sf_command(handle, 0x1300, C.byref(quality), C.sizeof(quality))
        values = np.asarray(samples, dtype=np.float32)
        # libsndfile's conversion buffer can exhaust the Windows thread stack
        # for a long charge recording passed in one call. Bound each write.
        for start in range(0, len(values), 65536):
            chunk = values[start:start + 65536]
            count = io.lib.sf_writef_float(handle, chunk.ctypes.data_as(C.POINTER(C.c_float)), len(chunk))
            if count != len(chunk):
                raise ValueError(f"Incomplete encode: {path}")
    finally:
        io.lib.sf_close(handle)
    audio.normalize_ogg(path, hashlib.sha256(values.tobytes()).digest()[:4])


def rms(samples):
    return float(np.sqrt(np.mean(np.square(samples))))


def main():
    archive = PACK_ROOT / "sp_v21-mc26.2.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PREVIOUS_SHA256:
        raise ValueError("Expected the preserved published v21 archive")
    io = audio.AudioIO(Path(r"C:\Program Files\Audacity\sndfile.dll"))
    recordings = {}
    with ZipFile(archive) as pack:
        if hashlib.sha256(pack.read(POWERSWITCH_PATH)).hexdigest() != POWERSWITCH_SHA256:
            raise ValueError("The already mono power switch recording changed")
        for event, asset in EVENT_PATHS.items():
            original = pack.read(asset)
            if hashlib.sha256(original).hexdigest() != SOURCE_HASHES[asset]:
                raise ValueError(f"Unexpected original recording: {asset}")
            source = ROOT / "source" / asset
            if source.exists() and source.read_bytes() != original:
                raise ValueError(f"Refusing to overwrite a different original: {source}")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(original)
            stereo, rate = io.read(source)
            if stereo.ndim != 2 or stereo.shape[1] != 2:
                raise ValueError(f"Expected stereo original: {event}")
            mono = np.mean(stereo, axis=1)
            destination = ROOT / asset
            write_mono(io, destination, mono, rate)
            decoded, output_rate = io.read(destination)
            if output_rate != rate or decoded.shape != (len(stereo), 1):
                raise ValueError(f"Encoding changed source timing: {event}")
            output = destination.read_bytes()
            recordings[event] = {
                "file": asset, "sourceFile": source.relative_to(ROOT).as_posix(),
                "sourceSha256": SOURCE_HASHES[asset], "sourceBytes": len(original),
                "sourceChannels": 2, "channels": 1, "sampleRate": rate,
                "sourceContainerFrames": vorbis_info(original)["frames"],
                "frames": len(stereo), "durationSeconds": len(stereo) / rate,
                "sha256": hashlib.sha256(output).hexdigest(), "bytes": len(output),
                "sourceRms": rms(stereo), "downmixRms": rms(mono),
                "encodedRms": rms(decoded), "sourcePeak": float(np.max(np.abs(stereo))),
                "downmixPeak": float(np.max(np.abs(mono))),
                "encodedPeak": float(np.max(np.abs(decoded))),
            }
    manifest = {
        "version": 1,
        "sourceArchive": {"file": archive.name, "sha256": PREVIOUS_SHA256},
        "provenance": "Existing STAR PROGRAM audio inherited unchanged from the preserved original resource pack; no new recordings or attribution claims.",
        "processing": {"downmix": "arithmetic mean of left and right channels",
                       "gain": 1.0, "filter": False, "normalization": False,
                       "resampling": False, "trimming": False, "pitchDsp": False,
                       "vorbisQuality": QUALITY},
        "sounds": recordings,
        "unchangedMono": {"event": "custom.powerswitch", "file": POWERSWITCH_PATH,
                          "sha256": POWERSWITCH_SHA256, "channels": 1, "sampleRate": 44100},
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sounds": len(recordings), "sourceBytes": sum(row["sourceBytes"] for row in recordings.values()),
                      "outputBytes": sum(row["bytes"] for row in recordings.values()),
                      "manifest": str(ROOT / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
