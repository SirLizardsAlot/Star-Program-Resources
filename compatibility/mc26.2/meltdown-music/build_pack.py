"""Replace v24's complete meltdown recording with the approved three sections.

All other ZIP members are preserved byte for byte. No game connection is used.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
PACK_ROOT = ROOT.parent
BASELINE = PACK_ROOT / "sp_v24-mc26.2.zip"
BASELINE_SHA256 = "7ee12833506276d2bb1b90f5facc21e64bd023563ecf0a7a5507bf58f53c5a7c"
OUTPUT = PACK_ROOT / "sp_v25-mc26.2.zip"
REPORT = PACK_ROOT / "build-report-v25.json"
LIMIT = 40 * 1024 * 1024
REMOVED = "assets/minecraft/sounds/custom/overloadmusic.ogg"
LEGACY_REGISTRY = "assets/minecraft/sounds.json"
REGISTRY = "assets/star_program_music/sounds.json"
ALIAS = b'{"name": "star_program_music:meltdown.intro", "type": "event"}'


def digest(data, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def patches(previous):
    approved = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "runtime/manifest.json").read_text(encoding="utf-8"))
    if set(manifest["sections"]) != {"intro", "middle", "ending"}:
        raise ValueError("Expected exactly the approved three music sections.")
    if digest(previous.read(REMOVED)) != approved["edit"]["sourceSha256"]:
        raise ValueError("Prepared sections did not come from v24's original song.")
    if (manifest["introBoundaryTicks"] != 1350 or manifest["loopPeriodTicks"] != 300
            or manifest["endingTicks"] != 1240 or not all(manifest["checks"][key] for key in
                ("introAndMiddleByteIdentical", "allRetainedPcmSamplesIdentical", "removedEndingSamplesAllZero", "noReencoding"))
            or manifest["approvedManifestSha256"] != digest((ROOT / "manifest.json").read_bytes())):
        raise ValueError("Unexpected runtime playback geometry or approval source.")
    payload = {REGISTRY: (ROOT / "runtime" / REGISTRY).read_bytes()}
    sounds = json.loads(payload[REGISTRY])
    if set(sounds) != {"meltdown.intro", "meltdown.middle", "meltdown.ending"}:
        raise ValueError("Expected exactly three deterministic music events.")
    for key, section in manifest["sections"].items():
        data = (ROOT / "runtime" / section["file"]).read_bytes()
        marker = data.find(b"\x01vorbis")
        if (not data.startswith(b"OggS") or marker < 0
                or data[marker + 11] != section["channels"]
                or int.from_bytes(data[marker + 12:marker + 16], "little") != section["sampleRate"]
                or digest(data) != section["sha256"] or len(data) != section["bytes"]):
            raise ValueError("Approved section geometry or bytes changed: " + key)
        expected_name = "star_program_music:" + section["file"].split("/sounds/", 1)[1][:-4]
        if (section["event"] != "star_program_music:meltdown." + key
                or sounds["meltdown." + key] != {"sounds": [{"name": expected_name, "stream": True}]}):
            raise ValueError("Unexpected streamed event routing: " + key)
        payload[section["file"]] = data
    old_registry = previous.read(LEGACY_REGISTRY)
    old_sounds = json.loads(old_registry)
    if (old_sounds["custom.overloadmusic"] != {"category": "master", "sounds": ["custom/overloadmusic"]}
            or old_registry.count(b'"custom/overloadmusic"') != 1):
        raise ValueError("Legacy song registration changed; preserve it for review.")
    # Replace only this value, preserving every unrelated registry byte and line ending.
    payload[LEGACY_REGISTRY] = old_registry.replace(b'"custom/overloadmusic"', ALIAS, 1)
    return payload, manifest


def validate():
    baseline_data = BASELINE.read_bytes()
    if digest(baseline_data) != BASELINE_SHA256:
        raise ValueError("Published v24 baseline changed.")
    with ZipFile(BASELINE) as previous, ZipFile(OUTPUT) as current:
        payload, manifest = patches(previous)
        old_names, new_names = set(previous.namelist()), set(current.namelist())
        added = set(payload) - old_names
        changed = {name for name in old_names & new_names if previous.read(name) != current.read(name)}
        if (len(new_names) != len(current.namelist()) or current.testzip()
                or new_names != (old_names - {REMOVED}) | added
                or changed != {LEGACY_REGISTRY}
                or any(current.read(name) != data for name, data in payload.items())):
            raise ValueError("Music overlay changed an unrelated asset or is incomplete.")
        old_sounds, new_sounds = (json.loads(archive.read(LEGACY_REGISTRY)) for archive in (previous, current))
        old_sounds.pop("custom.overloadmusic")
        alias = new_sounds.pop("custom.overloadmusic")
        if (old_sounds != new_sounds or alias != {"category": "master", "sounds": [json.loads(ALIAS)]}):
            raise ValueError("Legacy registration must change only the old music entry.")
    data = OUTPUT.read_bytes()
    if len(data) > LIMIT:
        raise ValueError("DiamondFire 40 MiB pack limit exceeded.")
    music = {**manifest, "namespace": "star_program_music",
             "legacyEvent": "minecraft:custom.overloadmusic", "legacyAlias": "star_program_music:meltdown.intro",
             "originalSourceSha256": json.loads((ROOT / "edit.json").read_text(encoding="utf-8"))["sourceSha256"],
             "originalPitchAndTempoPreserved": True}
    return {"version": 1, "output": OUTPUT.name, "size": len(data), "sizeLimitBytes": LIMIT,
            "sha1": digest(data, "sha1"), "sha256": digest(data),
            "gitBlob": digest(f"blob {len(data)}\0".encode() + data, "sha1"),
            "previousPack": {"archive": BASELINE.name, "sha256": BASELINE_SHA256},
            "unrelatedAssetsPreserved": True, "originalCoreRecordingsPreserved": True,
            "warningAlarmsPreserved": True, "unrelatedSoundRegistryBytesPreserved": True,
            "changedPreviousFiles": [LEGACY_REGISTRY], "removedFiles": [REMOVED],
            "addedFiles": sorted(added), "meltdownMusic": music}


def main(check_only=False):
    if not check_only:
        if digest(BASELINE.read_bytes()) != BASELINE_SHA256:
            raise ValueError("Published v24 baseline changed.")
        result = io.BytesIO()
        with ZipFile(BASELINE) as previous, ZipFile(result, "w", compression=ZIP_DEFLATED, compresslevel=9) as current:
            payload, _ = patches(previous)
            names = set(previous.namelist())
            if (set(payload) - {LEGACY_REGISTRY}) & names:
                raise ValueError("New namespace would overwrite existing assets.")
            for info in previous.infolist():
                if info.filename != REMOVED:
                    current.writestr(info, payload.get(info.filename, previous.read(info.filename)))
            for name in sorted(set(payload) - names):
                info = ZipInfo(name, date_time=(2026, 10, 17, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                current.writestr(info, payload[name])
        data = result.getvalue()
        if OUTPUT.exists() and OUTPUT.read_bytes() != data:
            raise ValueError("Refusing to replace a different existing immutable v25 archive.")
        OUTPUT.write_bytes(data)
    report = validate()
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("output", "size", "sha1", "sha256", "warningAlarmsPreserved")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate the existing archive without rebuilding it.")
    main(parser.parse_args().check)
