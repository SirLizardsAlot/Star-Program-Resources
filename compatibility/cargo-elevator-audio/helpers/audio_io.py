"""Decode preserved MP3 audio with Audacity's installed mpg123 library."""
from __future__ import annotations
import ctypes as C
import os
from pathlib import Path
import numpy as np

def decode_mp3(path):
    dll_root = Path(r'C:\Program Files\Audacity')
    keep = os.add_dll_directory(str(dll_root))
    lib = C.CDLL(str(dll_root / 'mpg123.dll'))
    lib.mpg123_new.argtypes = [C.c_char_p, C.POINTER(C.c_int)]
    lib.mpg123_new.restype = C.c_void_p
    lib.mpg123_open.argtypes = [C.c_void_p, C.c_char_p]
    lib.mpg123_getformat.argtypes = [C.c_void_p, C.POINTER(C.c_long), C.POINTER(C.c_int), C.POINTER(C.c_int)]
    lib.mpg123_outblock.argtypes = [C.c_void_p]
    lib.mpg123_outblock.restype = C.c_size_t
    lib.mpg123_read.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    lib.mpg123_close.argtypes = [C.c_void_p]
    lib.mpg123_delete.argtypes = [C.c_void_p]
    if lib.mpg123_init() != 0:
        raise RuntimeError('MP3 decoder initialization failed')
    handle = None
    try:
        handle = lib.mpg123_new(None, C.byref(C.c_int()))
        if not handle or lib.mpg123_open(handle, str(path).encode('utf-8')) != 0:
            raise ValueError(f'Cannot open preserved MP3: {path}')
        rate, channels, encoding = C.c_long(), C.c_int(), C.c_int()
        if lib.mpg123_getformat(handle, C.byref(rate), C.byref(channels), C.byref(encoding)) != 0:
            raise ValueError('MP3 output format unavailable')
        if encoding.value != 0xD0 or channels.value not in (1, 2):
            raise ValueError(f'Unexpected MP3 encoding/channels: {encoding.value}/{channels.value}')
        buffer = C.create_string_buffer(lib.mpg123_outblock(handle))
        chunks = []
        while True:
            done = C.c_size_t()
            status = lib.mpg123_read(handle, buffer, len(buffer), C.byref(done))
            chunks.append(buffer.raw[:done.value])
            if status == -12:  # MPG123_DONE
                break
            if status:
                raise RuntimeError(f'MP3 decoder failed: {status}')
        data = np.frombuffer(b''.join(chunks), dtype='<i2').astype(np.float64)
        data = data.reshape(-1, channels.value).mean(axis=1) / 32768
        if not len(data) or not np.isfinite(data).all():
            raise ValueError('Invalid MP3 sample data')
        return data, rate.value
    finally:
        if handle:
            lib.mpg123_close(handle)
            lib.mpg123_delete(handle)
        lib.mpg123_exit()
        keep.close()
