"""Whole-announcement audio I/O; no speech engine, pitch or rate processing."""
from __future__ import annotations
import ctypes as C
import os
if os.name == "nt":
    C.windll.kernel32.SetErrorMode(0x8003)
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".tools/python"))
sys.path.insert(0, str(ROOT.parent / "wordbank/.tools/python"))
sys.path.insert(0, str(ROOT.parent))
import numpy as np
import build_audio as base
RATE = 22050
AUDACITY = Path(r"C:\Program Files\Audacity")

def decode_mp3(path):
    keep = os.add_dll_directory(str(AUDACITY))
    library = C.CDLL(str(AUDACITY / "mpg123.dll"))
    library.mpg123_init.restype = C.c_int
    library.mpg123_new.argtypes = [C.c_char_p, C.POINTER(C.c_int)]
    library.mpg123_new.restype = C.c_void_p
    library.mpg123_open.argtypes = [C.c_void_p, C.c_char_p]
    library.mpg123_getformat.argtypes = [C.c_void_p, C.POINTER(C.c_long), C.POINTER(C.c_int), C.POINTER(C.c_int)]
    library.mpg123_outblock.argtypes = [C.c_void_p]
    library.mpg123_outblock.restype = C.c_size_t
    library.mpg123_read.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    library.mpg123_close.argtypes = [C.c_void_p]
    library.mpg123_delete.argtypes = [C.c_void_p]
    if library.mpg123_init() != 0:
        raise RuntimeError("MP3 decoder initialization failed")
    handle, error = None, C.c_int()
    try:
        handle = library.mpg123_new(None, C.byref(error))
        if not handle or library.mpg123_open(handle, str(path).encode("utf-8")) != 0:
            raise RuntimeError("MP3 decoder could not open the supplied file")
        rate, channels, encoding = C.c_long(), C.c_int(), C.c_int()
        if library.mpg123_getformat(handle, C.byref(rate), C.byref(channels), C.byref(encoding)) != 0:
            raise RuntimeError("MP3 output format unavailable")
        if encoding.value != 0xD0 or channels.value not in (1, 2):
            raise RuntimeError(f"Unsupported MP3 output format {encoding.value}/{channels.value}")
        buffer = C.create_string_buffer(library.mpg123_outblock(handle))
        chunks = []
        while True:
            done = C.c_size_t()
            status = library.mpg123_read(handle, buffer, len(buffer), C.byref(done))
            if done.value:
                chunks.append(buffer.raw[:done.value])
            if status == -12:  # MPG123_DONE
                break
            if status != 0:
                raise RuntimeError(f"MP3 decode error {status}")
        values = np.frombuffer(b"".join(chunks), dtype="<i2").astype(np.float64) / 32768
        if channels.value == 2:
            values = values.reshape(-1, 2).mean(axis=1)
        assert len(values) and np.isfinite(values).all()
        return values, rate.value, {"decoder": "Installed Audacity mpg123.dll", "inputRate": rate.value,
                                   "inputChannels": channels.value, "decodedFrames": len(values)}
    finally:
        if handle:
            library.mpg123_close(handle)
            library.mpg123_delete(handle)
        library.mpg123_exit()
        keep.close()

class HighQualityEncoder(base.Sndfile):
    def write(self, path, audio):
        info = self.Info(0, RATE, 1, 0x200060, 0, 0)
        handle = self.lib.sf_wchar_open(str(path), 0x20, C.byref(info))
        if not handle:
            raise RuntimeError(f"Cannot create OGG: {path}")
        quality = C.c_double(0.65)
        self.lib.sf_command(handle, 0x1300, C.byref(quality), C.sizeof(quality))
        values = np.asarray(audio, dtype=np.float32)
        try:
            # libsndfile's Vorbis adapter may allocate a temporary conversion
            # buffer on the stack. Bound writes for a long review montage.
            # Preserve the established encoder call sequence for short assets;
            # only long review audio needs the bounded conversion buffer.
            block = len(values) if len(values) <= RATE * 6 else 16384
            for begin in range(0, len(values), block):
                chunk = values[begin:begin + block]
                written = self.lib.sf_writef_float(handle, chunk.ctypes.data_as(C.POINTER(C.c_float)), len(chunk))
                if written != len(chunk):
                    raise RuntimeError("Incomplete OGG write")
        finally:
            self.lib.sf_close(handle)
        base.normalize_ogg(path, hashlib.sha256(values.tobytes()).digest()[:4])

@lru_cache
def phases(source_rate, target_rate):
    divisor = math.gcd(source_rate, target_rate)
    count = target_rate // divisor
    offsets = np.arange(-47, 49)
    distance = offsets[None, :] - np.arange(count)[:, None] / count
    cutoff, beta = min(1, target_rate / source_rate) * 0.97, 8.6
    window = np.i0(beta * np.sqrt(np.clip(1 - (distance / 48) ** 2, 0, 1))) / np.i0(beta)
    weights = cutoff * np.sinc(cutoff * distance) * window
    weights[np.abs(distance) > 48] = 0
    weights /= weights.sum(axis=1, keepdims=True)
    return weights, offsets, divisor

def resample(audio, source_rate):
    if source_rate == RATE:
        return audio.copy()
    weights, offsets, divisor = phases(source_rate, RATE)
    count = round(len(audio) * RATE / source_rate)
    output = np.empty(count)
    for begin in range(0, count, 4096):
        numerators = np.arange(begin, min(count, begin + 4096)) * source_rate
        indices = (numerators // RATE)[:, None] + offsets[None, :]
        phase = (numerators % RATE) // divisor
        values = audio[np.clip(indices, 0, len(audio) - 1)]
        values[(indices < 0) | (indices >= len(audio))] = 0
        output[begin:begin + len(numerators)] = np.sum(values * weights[phase], axis=1)
    return output
