"""Prepare the approved splice for runtime, removing only its silent Ogg tail.

Vorbis packets are copied without re-encoding. The final Ogg granule and CRC
are adjusted, and decoded PCM is required to equal the approved prefix exactly.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
ENDING_FRAMES = 2_976_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lossless_trim(data, frames):
    table = []
    for value in range(256):
        crc = value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
        table.append(crc)
    cursor = 0
    while cursor < len(data):
        if data[cursor:cursor + 4] != b"OggS":
            raise ValueError("Invalid Ogg page.")
        segments = data[cursor + 26]
        size = 27 + segments + sum(data[cursor + 27:cursor + 27 + segments])
        granule = int.from_bytes(data[cursor + 6:cursor + 14], "little")
        if granule != 0xFFFFFFFFFFFFFFFF and granule >= frames:
            page = bytearray(data[cursor:cursor + size])
            page[5] |= 4
            page[6:14] = frames.to_bytes(8, "little")
            page[22:26] = b"\0" * 4
            crc = 0
            for value in page:
                crc = ((crc << 8) ^ table[((crc >> 24) ^ value) & 255]) & 0xFFFFFFFF
            page[22:26] = crc.to_bytes(4, "little")
            return data[:cursor] + page
        cursor += size
    raise ValueError("Requested trim is outside the recording.")


def main():
    spec = importlib.util.spec_from_file_location("star_audio", ROOT.parent / "turbines/build_audio.py")
    audio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audio)
    io = audio.AudioIO(Path(r"C:\Program Files\Audacity\sndfile.dll"))
    approved = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    runtime = {"version": 1, "sections": {}, "introBoundaryTicks": 1350, "loopPeriodTicks": 300,
               "endingTicks": 1240, "overlapSeconds": 0.06,
               "firstBoundarySeconds": 67.5, "loopPeriodSeconds": 15.0,
               "approvedManifestSha256": digest((ROOT / "manifest.json").read_bytes()),
               "processing": "Lossless Ogg packet copy; only digital-zero ending samples removed."}
    for key, original in approved["sections"].items():
        source = ROOT / original["file"]
        data = source.read_bytes()
        if digest(data) != original["sha256"]:
            raise ValueError("Approved section changed: " + key)
        samples, rate = io.read(source)
        if samples.shape != (original["frames"], original["channels"]) or rate != original["sampleRate"]:
            raise ValueError("Approved decoded geometry changed: " + key)
        target = RUNTIME / original["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        frames = len(samples)
        if key == "ending":
            if rate != 48000 or np.any(samples[ENDING_FRAMES:]):
                raise ValueError("Refusing to remove any nonzero ending sample.")
            frames = ENDING_FRAMES
            data = lossless_trim(data, frames)
        target.write_bytes(data)
        decoded, decoded_rate = io.read(target)
        if decoded_rate != rate or not np.array_equal(decoded, samples[:frames]):
            raise ValueError("Runtime PCM must exactly equal the approved prefix: " + key)
        runtime["sections"][key] = {**original, "frames": frames, "durationSeconds": frames / rate,
                                      "sha256": digest(data), "bytes": len(data)}
    registry = "assets/star_program_music/sounds.json"
    (RUNTIME / registry).write_bytes((ROOT / registry).read_bytes())
    runtime["checks"] = {"introAndMiddleByteIdentical": True, "allRetainedPcmSamplesIdentical": True,
                         "removedEndingSamplesAllZero": True, "removedEndingFrames": approved["sections"]["ending"]["frames"] - ENDING_FRAMES,
                         "removedEndingSeconds": approved["sections"]["ending"]["durationSeconds"] - ENDING_FRAMES / 48000,
                         "noReencoding": True}
    (RUNTIME / "manifest.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(runtime, indent=2))


if __name__ == "__main__":
    main()
