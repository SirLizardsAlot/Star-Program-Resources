"""Generate a tiny offline ARPABET voice bank with light intercom ambience.

Uses a local eSpeak NG shared library for forced phonemes, never its executable.
Only generated OGG assets and the manifest enter the Minecraft resource pack.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import wave

import numpy as np

ROOT = Path(__file__).resolve().parent
RATE = 22050
NAMESPACE = "star_program"
PHONE_CODES = {
    "AA": "A:", "AE": "a", "AH": "V", "AO": "O:", "AW": "aU", "AY": "aI",
    "B": "b", "CH": "tS", "D": "d", "DH": "D", "EH": "E", "ER": "3:",
    "EY": "eI", "F": "f", "G": "g", "HH": "h", "IH": "I", "IY": "i:",
    "JH": "dZ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "N",
    "OW": "oU", "OY": "OI", "P": "p", "R": "r", "S": "s", "SH": "S",
    "T": "t", "TH": "T", "UH": "U", "UW": "u:", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "Z", "AX": "@",
}
EXAMPLES = dict(zip(PHONE_CODES, [
    "father", "cat", "cup", "thought", "out", "eye", "bat", "church", "dog", "this",
    "bed", "bird", "day", "fan", "go", "hat", "sit", "see", "judge", "key",
    "light", "man", "no", "sing", "goat", "boy", "pen", "red", "sun", "ship",
    "top", "thin", "book", "blue", "van", "wet", "yes", "zoo", "measure", "about",
]))
VOWELS = set("AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW AX".split())


class Espeak:
    class EventId(C.Union):
        _fields_ = [("number", C.c_int), ("name", C.c_void_p), ("string", C.c_char * 8)]

    class Event(C.Structure):
        pass

    Event._fields_ = [("type", C.c_int), ("unique_identifier", C.c_uint), ("text_position", C.c_int),
                     ("length", C.c_int), ("audio_position", C.c_int), ("sample", C.c_int),
                     ("user_data", C.c_void_p), ("id", EventId)]

    def __init__(self, directory: Path):
        # Suppress Windows crash/error dialogs even if a vendor DLL fails.
        if os.name == "nt":
            C.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
        filename = "libespeak-ng.dll" if os.name == "nt" else "libespeak-ng.so"
        self.lib = C.CDLL(str(directory / filename))
        self.lib.espeak_Initialize.argtypes = [C.c_int, C.c_int, C.c_char_p, C.c_int]
        self.lib.espeak_Initialize.restype = C.c_int
        self.lib.espeak_SetVoiceByName.argtypes = [C.c_char_p]
        self.lib.espeak_SetParameter.argtypes = [C.c_int, C.c_int, C.c_int]
        self.lib.espeak_Synth.argtypes = [C.c_void_p, C.c_size_t, C.c_uint, C.c_int, C.c_uint,
                                       C.c_uint, C.POINTER(C.c_uint), C.c_void_p]
        self.lib.espeak_Synth.restype = C.c_int
        self.chunks = []
        self.events = []
        self.callback_type = C.CFUNCTYPE(C.c_int, C.POINTER(C.c_short), C.c_int, C.POINTER(self.Event))

        @self.callback_type
        def callback(samples, count, events):
            if samples and count:
                self.chunks.append(C.string_at(samples, count * 2))
            if events:
                index = 0
                while events[index].type:
                    event = events[index]
                    if event.type == 7:
                        self.events.append((event.audio_position, event.id.string.decode("ascii", errors="replace")))
                    index += 1
            return 0

        self.callback = callback
        self.lib.espeak_SetSynthCallback.argtypes = [self.callback_type]
        self.rate = self.lib.espeak_Initialize(2, 0, str(directory).encode("utf-8"), 0x8001)
        if self.rate != RATE:
            raise RuntimeError(f"Expected {RATE} Hz eSpeak data, got {self.rate}")
        self.lib.espeak_SetSynthCallback(self.callback)
        if self.lib.espeak_SetVoiceByName(b"en-us") != 0:
            raise RuntimeError("eSpeak en-us voice unavailable")
        # A narrow pitch range and modestly lower voice suit a facility intercom.
        for parameter, value in ((1, 215), (2, 100), (3, 43), (4, 0), (7, 0)):
            if self.lib.espeak_SetParameter(parameter, value, 0) != 0:
                raise RuntimeError(f"Could not set eSpeak parameter {parameter}")

    def synthesize(self, text: str, phonemes=True):
        self.chunks.clear()
        self.events.clear()
        buffer = C.create_string_buffer(text.encode("utf-8"))
        flags = 1 | (0x100 if phonemes else 0)
        result = self.lib.espeak_Synth(buffer, len(buffer), 0, 1, 0, flags, None, None)
        if result != 0:
            raise RuntimeError(f"eSpeak failed: {result}")
        return np.frombuffer(b"".join(self.chunks), dtype="<i2").astype(np.float64) / 32768.0

    def close(self):
        self.lib.espeak_Terminate()


class Sndfile:
    class Info(C.Structure):
        _fields_ = [("frames", C.c_int64), ("samplerate", C.c_int), ("channels", C.c_int),
                    ("format", C.c_int), ("sections", C.c_int), ("seekable", C.c_int)]

    def __init__(self, dll: Path):
        self.directory_handle = os.add_dll_directory(str(dll.parent)) if os.name == "nt" else None
        self.lib = C.CDLL(str(dll))
        self.lib.sf_wchar_open.argtypes = [C.c_wchar_p, C.c_int, C.POINTER(self.Info)]
        self.lib.sf_wchar_open.restype = C.c_void_p
        self.lib.sf_writef_float.argtypes = [C.c_void_p, C.POINTER(C.c_float), C.c_int64]
        self.lib.sf_writef_float.restype = C.c_int64
        self.lib.sf_readf_float.argtypes = [C.c_void_p, C.POINTER(C.c_float), C.c_int64]
        self.lib.sf_readf_float.restype = C.c_int64
        self.lib.sf_close.argtypes = [C.c_void_p]
        self.lib.sf_command.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int]

    def write(self, path: Path, audio):
        info = self.Info(0, RATE, 1, 0x200060, 0, 0)  # OGG | VORBIS
        handle = self.lib.sf_wchar_open(str(path), 0x20, C.byref(info))
        if not handle:
            raise RuntimeError(f"Cannot create Vorbis output: {path}")
        quality = C.c_double(0.15)
        self.lib.sf_command(handle, 0x1300, C.byref(quality), C.sizeof(quality))
        values = np.asarray(audio, dtype=np.float32)
        count = self.lib.sf_writef_float(handle, values.ctypes.data_as(C.POINTER(C.c_float)), len(values))
        self.lib.sf_close(handle)
        if count != len(values):
            raise RuntimeError(f"Incomplete Vorbis output: {path}")
        # libvorbis chooses a random Ogg stream ID. Normalize it and recompute
        # each page CRC so identical input regenerates identical pack assets.
        normalize_ogg(path, hashlib.sha256(values.tobytes()).digest()[:4])

    def read(self, path: Path):
        info = self.Info()
        handle = self.lib.sf_wchar_open(str(path), 0x10, C.byref(info))
        if not handle or info.channels != 1 or info.samplerate != RATE:
            raise RuntimeError(f"Invalid mono Vorbis output: {path}")
        values = np.zeros(info.frames, dtype=np.float32)
        count = self.lib.sf_readf_float(handle, values.ctypes.data_as(C.POINTER(C.c_float)), info.frames)
        self.lib.sf_close(handle)
        if count != info.frames or not np.isfinite(values).all():
            raise RuntimeError(f"Invalid decoded audio: {path}")
        return values


def normalize_ogg(path: Path, serial: bytes):
    data = bytearray(path.read_bytes())
    offset = 0
    while offset < len(data):
        if data[offset:offset + 4] != b"OggS":
            raise ValueError(f"Malformed Ogg page at {offset}: {path}")
        count = data[offset + 26]
        end = offset + 27 + count + sum(data[offset + 27:offset + 27 + count])
        data[offset + 14:offset + 18] = serial
        data[offset + 22:offset + 26] = b"\0" * 4
        crc = 0
        for value in data[offset:end]:
            crc ^= value << 24
            for _ in range(8):
                crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
        data[offset + 22:offset + 26] = struct.pack("<I", crc)
        offset = end
    path.write_bytes(data)


def write_wave(path: Path, values):
    path.parent.mkdir(exist_ok=True, parents=True)
    pcm = np.asarray(np.clip(values, -1, 1) * 32767, dtype="<i2")
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes(pcm.tobytes())


def trim(audio):
    if len(audio) < 2:
        raise ValueError("Empty phoneme")
    peak = np.max(np.abs(audio))
    active = np.flatnonzero(np.abs(audio) > max(0.0012, peak * 0.008))
    if len(active) < 50 or peak < 0.01:
        raise ValueError("Phoneme has too little audible content")
    margin = int(0.002 * RATE)
    return audio[max(0, active[0] - margin):min(len(audio), active[-1] + margin + 1)]


def bandpass(audio):
    # Two cascaded first-order filters, 240 Hz high-pass and 4100 Hz low-pass.
    high = np.zeros_like(audio)
    low = np.zeros_like(audio)
    high_alpha = 1.0 / (1.0 + 2 * math.pi * 240 / RATE)
    low_alpha = (2 * math.pi * 4100 / RATE) / (1 + 2 * math.pi * 4100 / RATE)
    for index in range(1, len(audio)):
        high[index] = high_alpha * (high[index - 1] + audio[index] - audio[index - 1])
        low[index] = low[index - 1] + low_alpha * (high[index] - low[index - 1])
    return np.tanh(low * 1.25) / 1.25


def intercom(audio):
    dry = bandpass(audio)
    # Restrained early reflections: understandable speech with a small room tail.
    reflections = [(0.029, 0.11), (0.047, 0.08), (0.071, 0.055), (0.103, 0.035)]
    output = np.zeros(len(dry) + round(RATE * 0.13))
    output[:len(dry)] += dry
    for delay, gain in reflections:
        offset = round(delay * RATE)
        output[offset:offset + len(dry)] += dry * gain
    fade = min(round(RATE * 0.003), len(output) // 3)
    output[:fade] *= np.linspace(0, 1, fade)
    output[-fade:] *= np.linspace(1, 0, fade)
    return output


def build(args):
    output_dir = ROOT / "assets" / NAMESPACE / "sounds" / "tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = ROOT / "raw"
    raw_dir.mkdir(exist_ok=True)
    encoder = Sndfile(args.sndfile)
    engine = Espeak(args.espeak)
    clips = {}
    phonemes = {}
    try:
        for phone, code in PHONE_CODES.items():
            # Stops and glides need a following vowel for their actual acoustic
            # release. Extract only the consonant from a neutral schwa carrier,
            # using the synthesizer's own phoneme timing, plus 8ms transition.
            # This produces /b/, /t/, /w/, etc., never spoken letter names.
            carrier = phone not in VOWELS
            raw = engine.synthesize(f"[[{code}{'@' if carrier else ''}]]")
            write_wave(raw_dir / f"{phone.lower()}.wav", raw)
            if carrier:
                events = [(ms, name) for ms, name in engine.events if not name.startswith("_")]
                if len(events) < 2:
                    raise ValueError(f"No carrier boundary for {phone}: {engine.events}")
                start = max(0, round((events[0][0] - 2) * RATE / 1000))
                end = min(len(raw), round((events[1][0] + 8) * RATE / 1000))
                raw = raw[start:end]
            cropped = trim(raw)
            # Place the next onset on an exact DF tick; resampling is limited to
            # the nearest 50ms so each phone preserves its defining transition.
            ticks = max(1, min(8, round(len(cropped) / RATE / 0.05)))
            target = round(ticks * 0.05 * RATE)
            fitted = np.interp(np.linspace(0, len(cropped) - 1, target), np.arange(len(cropped)), cropped)
            peak = np.max(np.abs(fitted))
            rms = math.sqrt(float(np.mean(fitted ** 2)))
            fitted *= min(0.68 / peak, 0.16 / max(rms, 1e-7))
            processed = intercom(fitted)
            event = f"{NAMESPACE}:tts.{phone.lower()}"
            asset = f"assets/{NAMESPACE}/sounds/tts/{phone.lower()}.ogg"
            path = ROOT / asset
            encoder.write(path, processed)
            decoded = encoder.read(path)
            if np.max(np.abs(decoded)) > 0.99 or np.sqrt(np.mean(decoded ** 2)) < 0.005:
                raise ValueError(f"Clipping or silent export: {phone}")
            clips[phone] = decoded
            phonemes[phone] = {
                "event": event, "file": asset, "ticks": ticks,
                "durationMs": round(len(decoded) / RATE * 1000, 3),
                "speechMs": round(target / RATE * 1000, 3), "example": EXAMPLES[phone],
                "espeak": code, "extraction": "neutral-schwa onset" if carrier else "isolated vowel",
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        manifest = {
            "version": 1, "namespace": NAMESPACE, "sampleRate": RATE, "channels": 1,
            "voice": "eSpeak NG 1.52.0 en-us, pitch 43, range 0, rate 215",
            "processing": {"highPassHz": 240, "lowPassHz": 4100, "reverbTailMs": 130,
                           "vorbisQuality": 0.15},
            "phonemes": phonemes,
        }
        (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        sounds = {f"tts.{phone.lower()}": {"sounds": [{"name": f"{NAMESPACE}:tts/{phone.lower()}", "stream": False}]} for phone in PHONE_CODES}
        (ROOT / "assets" / NAMESPACE / "sounds.json").write_text(json.dumps(sounds, indent=2) + "\n", encoding="utf-8")
        preview_from_assets(encoder, manifest)
        print(json.dumps({"phones": len(phonemes), "oggBytes": sum(p["bytes"] for p in phonemes.values()),
                          "ticks": {key: value["ticks"] for key, value in phonemes.items()}}, indent=2))
    finally:
        engine.close()


def preview_from_assets(encoder, manifest=None, config_path=None):
    """Render only from existing exports; never resynthesize or change assets."""
    if manifest is None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if config_path is None:
        workspace_config = ROOT.parents[1] / "config" / "tts.json"
        config_path = workspace_config if workspace_config.exists() else ROOT / "pronunciations.json"
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    # All fixed preview words exist in the same on-plot pronunciation dictionary.
    # Native compile appends '_' to every word, then '#' for each period.
    sequence = []
    for token in ("attention", ".", "reactor", "temperature", "critical", "."):
        sequence += ["#"] if token == "." else config["dictionary"][token].split() + ["_"]
    clips = {phone: encoder.read(ROOT / entry["file"]) for phone, entry in manifest["phonemes"].items()}
    render_preview(sequence, clips, manifest["phonemes"], encoder, ROOT / "preview-intercom", config)


def render_preview(sequence, clips, phonemes, encoder, base, config):
    cursor = 0
    scheduled = []
    total_ticks = 0
    for token in sequence:
        if token in ("_", "#"):
            ticks = config["wordGapTicks"] if token == "_" else config["sentenceGapTicks"]
        else:
            scheduled.append((cursor, clips[token]))
            ticks = phonemes[token]["ticks"]
        total_ticks += ticks
        # Round the absolute timeline, avoiding cumulative half-sample drift.
        cursor = round(RATE * total_ticks * 0.05)
    output = np.zeros(cursor + round(RATE * 0.2))
    for offset, clip in scheduled:
        output[offset:offset + len(clip)] += clip * config["volume"]
    if np.max(np.abs(output)) > 0.99:
        raise ValueError("Preview unexpectedly clips at native playback gain")
    write_wave(base.with_suffix(".wav"), output)
    encoder.write(base.with_suffix(".ogg"), output)
    base.with_suffix(".json").write_text(json.dumps({"text": "Attention. Reactor temperature critical.",
        "phonemes": " ".join(sequence), "totalTicks": total_ticks,
        "wordGapTicks": config["wordGapTicks"], "sentenceGapTicks": config["sentenceGapTicks"],
        "volume": config["volume"], "durationMs": round(len(output) / RATE * 1000, 3),
        "description": "Spliced exported OGG phones at the exact 20 TPS onset spacing used on plot."}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--espeak", type=Path, default=ROOT / "vendor" / "espeak-ng")
    parser.add_argument("--sndfile", type=Path, default=Path(r"C:\Program Files\Audacity\sndfile.dll"))
    parser.add_argument("--preview-only", action="store_true", help="Render preview from existing OGG exports without changing the voice bank")
    parser.add_argument("--config", type=Path, help="Pronunciation config for preview (defaults to game/config/tts.json or adjacent pronunciations.json)")
    args = parser.parse_args()
    if args.preview_only:
        preview_from_assets(Sndfile(args.sndfile), config_path=args.config)
    else:
        build(args)
