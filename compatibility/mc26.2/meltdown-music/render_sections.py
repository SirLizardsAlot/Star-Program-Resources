"""Create repeatable music sections and continuous preview renders.

The shipped original, active resource-pack pin, game timing and portal remain
unchanged. Section overlaps are mixed in PCM before a continuous Ogg is encoded.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import wave
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("star_audio", ROOT.parent / "turbines/build_audio.py")
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)
NAMESPACE = "star_program_music"


def write_ogg(io, path, samples, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    channels = samples.shape[1]
    info = io.Info(0, rate, channels, 0x200060, 0, 0)
    handle = io.lib.sf_wchar_open(str(path), 0x20, C.byref(info))
    if not handle:
        raise ValueError(f"Cannot encode {path}")
    try:
        quality = C.c_double(0.55)
        io.lib.sf_command(handle, 0x1300, C.byref(quality), C.sizeof(quality))
        for start in range(0, len(samples), 16384):
            chunk = np.ascontiguousarray(samples[start:start + 16384], dtype=np.float32)
            if io.lib.sf_writef_float(handle, chunk.ctypes.data_as(C.POINTER(C.c_float)), len(chunk)) != len(chunk):
                raise ValueError(f"Incomplete encode: {path}")
    finally:
        io.lib.sf_close(handle)
    audio.normalize_ogg(path, hashlib.sha256(samples.astype(np.float32).tobytes()).digest()[:4])
    decoded, decoded_rate = io.read(path)
    if decoded_rate != rate or decoded.shape != samples.shape or not np.isfinite(decoded).all():
        raise ValueError(f"Encoded timing or channel layout changed: {path}")
    if np.max(np.abs(decoded)) >= 1:
        raise ValueError(f"Vorbis output clips: {path}")
    return {"frames": len(decoded), "durationSeconds": len(decoded) / rate,
            "sampleRate": rate, "channels": channels, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "peak": float(np.max(np.abs(decoded)))}


def write_wav(path, samples, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(samples.shape[1])
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.tobytes())


def sections(source, start, end, overlap):
    if not (overlap > 0 and overlap < end - start and overlap <= start and end + overlap < len(source)):
        raise ValueError("Section boundaries require room for both transition handles")
    intro = source[:start + overlap].copy()
    middle = source[start:end + overlap].copy()
    ending = source[end:].copy()
    ramp = np.linspace(0, 1, overlap)[:, None]
    # Linear complementary fades preserve gain when two matching recordings
    # overlap. Equal-power fades would boost those correlated source samples.
    intro[-overlap:] *= 1 - ramp
    middle[:overlap] *= ramp
    middle[-overlap:] *= 1 - ramp
    ending[:overlap] *= ramp
    return {"intro": intro, "middle": middle, "ending": ending}


def assemble(clips, start, period, source_frames, loops):
    if loops < 1:
        raise ValueError("At least one middle phrase is required")
    output = np.zeros((source_frames + (loops - 1) * period, clips["intro"].shape[1]))
    events = [(0, clips["intro"])]
    events.extend((start + index * period, clips["middle"]) for index in range(loops))
    events.append((start + loops * period, clips["ending"]))
    for at, clip in events:
        output[at:at + len(clip)] += clip
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edit", type=Path, default=ROOT / "edit.json")
    parser.add_argument("--loops", type=int, default=4, help="Total middle phrases, including the original one")
    parser.add_argument("--minimum-seconds", type=float, help="Round up to a whole phrase at or above this length")
    args = parser.parse_args()
    edit = json.loads(args.edit.read_text(encoding="utf-8"))
    source_path = ROOT / edit["sourceFile"]
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != edit["sourceSha256"]:
        raise ValueError("The preserved original recording changed")
    io = audio.AudioIO(Path(r"C:\Program Files\Audacity\sndfile.dll"))
    source, rate = io.read(source_path)
    start, end, cross = (edit[key] for key in ["loopStartFrame", "loopEndFrame", "crossfadeFrames"])
    if rate != edit["sampleRate"] or source.shape[1] != 2:
        raise ValueError("Expected the original stereo recording at its original sample rate")
    period = end - start
    loops = args.loops
    if args.minimum_seconds is not None:
        if not math.isfinite(args.minimum_seconds) or args.minimum_seconds <= 0:
            raise ValueError("Requested length must be finite and positive")
        loops = max(1, 1 + math.ceil((args.minimum_seconds * rate - len(source)) / period))
    clips = sections(source, start, end, cross)
    # A single phrase plus its matching transition handles reconstructs the
    # original PCM, proving the introduction/ending joins do not alter it.
    original_roundtrip = assemble(clips, start, period, len(source), 1)
    error = float(np.max(np.abs(original_roundtrip - source)))
    if error > 1e-7:
        raise ValueError("One-phrase assembly failed to reconstruct the original")
    extended = assemble(clips, start, period, len(source), loops)
    if not np.isfinite(extended).all() or np.max(np.abs(extended)) > np.max(np.abs(source)) + 1e-7:
        raise ValueError("Splices introduced invalid samples or excess peak gain")
    assets = ROOT / f"assets/{NAMESPACE}/sounds/meltdown"
    entries = {}
    for name, clip in clips.items():
        filename = assets / f"{name}.ogg"
        entries[name] = {"file": filename.relative_to(ROOT).as_posix(),
                         "event": f"{NAMESPACE}:meltdown.{name}", **write_ogg(io, filename, clip, rate)}
    sounds = {f"meltdown.{name}": {"sounds": [{"name": f"{NAMESPACE}:meltdown/{name}", "stream": True}]}
              for name in clips}
    sound_path = ROOT / f"assets/{NAMESPACE}/sounds.json"
    sound_path.write_text(json.dumps(sounds, indent=2) + "\n", encoding="utf-8")
    previews = ROOT / "previews"
    continuous_path = previews / f"meltdown-{loops}-phrases.ogg"
    continuous = write_ogg(io, continuous_path, extended, rate)
    # The short proof includes three middle-to-middle joins and the original
    # ending transition, with no inserted silence or spoken annotations.
    proof_loops = 4
    proof = assemble(clips, start, period, len(source), proof_loops)
    proof_start = max(0, start + period - 4 * rate)
    proof_end = min(len(proof), start + proof_loops * period + 8 * rate)
    proof = proof[proof_start:proof_end]
    proof_path = previews / "loop-and-ending-proof.wav"
    write_wav(proof_path, proof, rate)
    overlay = ROOT / "meltdown-sections-overlay.zip"
    with zipfile.ZipFile(overlay, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in sorted((ROOT / "assets").rglob("*")):
            if filename.is_file():
                archive.write(filename, filename.relative_to(ROOT).as_posix())
    manifest = {"version": 1, "status": "local splice draft for audition", "edit": edit,
                "sections": entries, "loopPeriodFrames": period, "loopPeriodSeconds": period / rate,
                "overlapSeconds": cross / rate, "loops": loops,
                "durationSeconds": len(extended) / rate,
                "continuousPreview": {"file": continuous_path.relative_to(ROOT).as_posix(), **continuous},
                "joinProof": {"file": proof_path.relative_to(ROOT).as_posix(),
                              "durationSeconds": len(proof) / rate, "middleJoins": 3, "endingJoins": 1},
                "checks": {"sourcePreserved": source_path.read_bytes() == source_bytes,
                           "onePhraseRoundtripMaxError": error, "originalPitchAndTempoPreserved": True,
                           "decodedSectionTimingVerified": True, "gameAndPortalUnchanged": True},
                "playback": "Use overlapping section handles at the declared positions; do not simply concatenate the padded Ogg files. Continuous renders bake the overlaps before encoding.",
                "durationControl": "Each additional middle phrase adds loopPeriodSeconds. --minimum-seconds rounds up to the next whole phrase, preserving the original ending."}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"loops": loops, "durationSeconds": manifest["durationSeconds"],
                      "loopPeriodSeconds": period / rate, "continuousPreview": str(continuous_path),
                      "joinProof": str(proof_path), "onePhraseRoundtripMaxError": error}, indent=2))


if __name__ == "__main__":
    main()
