"""Add only Code Black assets to the active published v21 pack.

The original core recordings were deliberately restored from v22 to v21.
Consequently this standalone overlay uses v21 directly and preserves every
one of its files byte-for-byte, including the restored core recordings.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
PACK_ROOT = ROOT.parent
BASELINE = PACK_ROOT / "sp_v21-mc26.2.zip"
BASELINE_SHA256 = "ea925dd412e61facddffe10a21b678123570cb6516146c3e25b0de47ccd1be62"
OUTPUT = PACK_ROOT / "sp_v23-mc26.2.zip"
LIMIT = 40 * 1024 * 1024


def digest(data, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def patches():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("namespace") != "star_program_emergency" or set(manifest["sounds"]) != {"code_black.siren", "pa.code_black"}:
        raise ValueError("Expected exactly the Code Black siren and complete PA.")
    payload = {}
    for key, entry in manifest["sounds"].items():
        data = (ROOT / entry["file"]).read_bytes()
        marker = data.find(b"\x01vorbis")
        if (not data.startswith(b"OggS") or marker < 0 or data[marker + 11] != 1
                or int.from_bytes(data[marker + 12:marker + 16], "little") != entry["sampleRate"]
                or digest(data) != entry["sha256"]):
            raise ValueError(f"Audio geometry or hash mismatch: {key}")
        payload[entry["file"]] = data
    sounds_path = "assets/star_program_emergency/sounds.json"
    sounds_data = (ROOT / sounds_path).read_bytes()
    sounds = json.loads(sounds_data)
    if set(sounds) != set(manifest["sounds"]):
        raise ValueError("Missing deterministic emergency event.")
    for key, entry in manifest["sounds"].items():
        expected = "star_program_emergency:" + entry["file"].split("/sounds/", 1)[1][:-4]
        if sounds[key] != {"sounds": [{"name": expected, "stream": False}]}:
            raise ValueError(f"Unexpected event routing: {key}")
    if (manifest["sounds"]["code_black.siren"]["ticks"] != 268
            or manifest["sounds"]["code_black.siren"]["frames"] != 428800
            or manifest["sounds"]["code_black.siren"]["durationMs"] != 13400):
        raise ValueError("Runtime cadence requires exactly one 268-tick sweep.")
    payload[sounds_path] = sounds_data
    payload["credits/star_program_emergency/code_black_audio.txt"] = (ROOT / "CREDITS.txt").read_bytes()
    return payload, manifest


def validate():
    if digest(BASELINE.read_bytes()) != BASELINE_SHA256:
        raise ValueError("Published v21 baseline changed.")
    payload, manifest = patches()
    with ZipFile(BASELINE) as previous, ZipFile(OUTPUT) as current:
        old_names, new_names = set(previous.namelist()), set(current.namelist())
        if (len(new_names) != len(current.namelist()) or new_names - old_names != set(payload)
                or old_names - new_names or any(previous.read(name) != current.read(name) for name in old_names)
                or any(current.read(name) != data for name, data in payload.items()) or current.testzip()):
            raise ValueError("Code Black overlay changed an unrelated asset or is incomplete.")
    data = OUTPUT.read_bytes()
    if len(data) > LIMIT:
        raise ValueError("DiamondFire 40 MiB pack size limit exceeded.")
    return {"version": 1, "output": OUTPUT.name, "size": len(data), "sizeLimitBytes": LIMIT,
            "sha1": digest(data, "sha1"), "sha256": digest(data),
            "gitBlob": digest(f"blob {len(data)}\0".encode() + data, "sha1"),
            "previousPack": {"archive": BASELINE.name, "sha256": BASELINE_SHA256},
            "existingAssetsPreserved": True, "originalCoreRecordingsPreserved": True,
            "changedPreviousFiles": [], "addedFiles": sorted(payload), "emergencyAudio": manifest}


def main():
    if digest(BASELINE.read_bytes()) != BASELINE_SHA256:
        raise ValueError("Published v21 baseline changed.")
    payload, _ = patches()
    with ZipFile(BASELINE) as previous, ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as current:
        if set(previous.namelist()) & set(payload):
            raise ValueError("Emergency namespace already exists in baseline.")
        for info in previous.infolist():
            current.writestr(info, previous.read(info.filename))
        for name, data in sorted(payload.items()):
            info = ZipInfo(name, (2026, 10, 15, 0, 0, 0))
            info.compress_type, info.external_attr = ZIP_DEFLATED, 0o644 << 16
            current.writestr(info, data, compresslevel=9)
    report = validate()
    (PACK_ROOT / "build-report-v23.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("output", "size", "sha1", "sha256", "existingAssetsPreserved")}, indent=2))


if __name__ == "__main__":
    main()
