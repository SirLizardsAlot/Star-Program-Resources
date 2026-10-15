"""Validate and merge the approved chime and elevator door sound overlays."""
import hashlib
import json
import re


NAMESPACE = "star_program_intercom"
EVENT = NAMESPACE + ":chime.two_tone"
AUDIO_PATH = f"assets/{NAMESPACE}/sounds/chime/two_tone.ogg"
SOUNDS_PATH = f"assets/{NAMESPACE}/sounds.json"
CREDITS_PATH = f"credits/{NAMESPACE}/two_tone.txt"
EXPECTED_AUDIO_SHA256 = "15612357d1928c347b1a2a7f274d585482326b4892376bf8ab80a49dfe3aefe2"
EXPECTED_SOURCE_SHA256 = "7a35c22d17119adfdb4970219fec03033861882dd9c4cc3bcf6960efa3f74d43"
DOOR_CREDITS_PATH = f"credits/{NAMESPACE}/elevator_doors.txt"
DOOR_KEYS = ("door_large", "door_small")
DOOR_PATHS = {key: f"assets/{NAMESPACE}/sounds/elevator/{key}.ogg" for key in DOOR_KEYS}


def chime_patches(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("namespace") != NAMESPACE:
        raise ValueError("Expected the versioned intercom chime manifest.")
    entry = manifest.get("sounds", {}).get("two_tone", {})
    if (entry.get("event") != EVENT or entry.get("file") != AUDIO_PATH
            or entry.get("sha256") != EXPECTED_AUDIO_SHA256
            or entry.get("sourceSha256") != EXPECTED_SOURCE_SHA256
            or entry.get("sampleRate") != 32000 or entry.get("channels") != 1):
        raise ValueError("Elevator chime metadata does not match the approved two-tone recording.")

    data = (root / AUDIO_PATH).read_bytes()
    offset = data.find(b"\x01vorbis")
    if (hashlib.sha256(data).hexdigest() != EXPECTED_AUDIO_SHA256
            or len(data) != entry.get("bytes")):
        raise ValueError("Elevator chime audio changed without approval.")
    if (not data.startswith(b"OggS") or offset < 0
            or int.from_bytes(data[offset + 7:offset + 11], "little") != 0
            or data[offset + 11] != 1
            or int.from_bytes(data[offset + 12:offset + 16], "little") != 32000):
        raise ValueError("Expected mono 32000 Hz Ogg Vorbis for the elevator chime.")
    expected_sound = {"sounds": [{"name": NAMESPACE + ":chime/two_tone", "stream": False}]}
    source_sounds = json.loads((root / SOUNDS_PATH).read_text(encoding="utf-8"))
    if source_sounds.get("chime.two_tone") != expected_sound:
        raise ValueError("The elevator chime must resolve to its one deterministic recording.")

    sources = json.loads((root / "source/sources.json").read_text(encoding="utf-8"))["sources"]
    matches = [source for source in sources if source.get("id") == 370176]
    if len(matches) != 1:
        raise ValueError("Expected one source provenance record for the two-tone chime.")
    source = matches[0]
    source_page = "https://freesound.org/people/mpaol2023/sounds/370176/"
    license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
    if (source.get("license") != "CC0-1.0" or source.get("license_url") != license_url
            or source.get("creator") != "mpaol2023" or source.get("source_page") != source_page
            or source.get("sha256") != EXPECTED_SOURCE_SHA256):
        raise ValueError("Elevator chime source or CC0 license provenance changed.")
    credits = (
        "STAR PROGRAM - elevator two-tone chime\n\n"
        "Source: 2-tone chime by mpaol2023, Freesound\n"
        f"{source_page}\n"
        f"License: CC0-1.0\n{license_url}\n\n"
        "Input: public high-quality Ogg preview; original source audio is not included.\n"
        f"Source SHA-256: {EXPECTED_SOURCE_SHA256}\n"
        "Edits: doubled note cadence, preserved pitch, speaker filter, saturation, short room reverb.\n"
        f"Processed SHA-256: {EXPECTED_AUDIO_SHA256}\n"
    ).encode("utf-8")
    patches = {
        SOUNDS_PATH: (json.dumps({"chime.two_tone": expected_sound}, indent=2) + "\n").encode(),
        AUDIO_PATH: data,
        CREDITS_PATH: credits,
    }
    return patches, {
        "event": EVENT, "namespace": NAMESPACE, "file": AUDIO_PATH,
        "audioBytes": len(data), "sha256": EXPECTED_AUDIO_SHA256,
        "durationMs": round(entry["durationSeconds"] * 1000),
        "sampleRate": 32000, "channels": 1, "monoVorbis": True,
        "deterministicEvent": True, "creditsFile": CREDITS_PATH,
        "source": {"creator": "mpaol2023", "page": source_page,
                   "license": "CC0-1.0", "licenseUrl": license_url,
                   "sha256": EXPECTED_SOURCE_SHA256},
        "processing": manifest["processing"],
    }


def elevator_door_patches(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("namespace") != NAMESPACE
            or set(manifest.get("sounds", {})) != set(DOOR_KEYS)):
        raise ValueError("Expected exactly the two versioned elevator door recordings.")
    source = manifest.get("source", {})
    source_page = "https://freesound.org/people/joedeshon/sounds/368738/"
    license_url = "https://creativecommons.org/licenses/by/4.0/"
    if (source.get("creator") != "joedeshon" or source.get("page") != source_page
            or source.get("license") != "CC-BY-4.0" or source.get("licenseUrl") != license_url
            or not isinstance(source.get("title"), str) or not source["title"].strip()
            or not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", ""))):
        raise ValueError("Expected the elevator door recording's CC BY 4.0 attribution and source hash.")
    if not manifest.get("processing"):
        raise ValueError("The modified elevator recordings need processing provenance.")
    expected_sounds = {f"elevator.{key}": {"sounds": [{
        "name": f"{NAMESPACE}:elevator/{key}", "stream": False,
    }]} for key in DOOR_KEYS}
    source_sounds = json.loads((root / SOUNDS_PATH).read_text(encoding="utf-8"))
    if source_sounds != expected_sounds:
        raise ValueError("Elevator door registrations must resolve to exactly their two recordings.")
    patches, recordings = {}, {}
    for key, duration, pitch in [("door_large", 4.0, 1.0), ("door_small", 4.5, 1.5)]:
        entry = manifest["sounds"][key]
        event = f"{NAMESPACE}:elevator.{key}"
        name = DOOR_PATHS[key]
        rate = entry.get("sampleRate")
        if (entry.get("event") != event or entry.get("file") != name
                or entry.get("sourceSha256") != source["sha256"]
                or not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", ""))
                or entry.get("channels") != 1 or rate not in {22050, 32000, 44100, 48000}
                or not isinstance(entry.get("durationSeconds"), (int, float))
                or abs(entry["durationSeconds"] - duration) > 0.1):
            raise ValueError(f"Elevator door metadata does not match the selected recording: {key}")
        data = (root / name).read_bytes()
        if (hashlib.sha256(data).hexdigest() != entry["sha256"]
                or len(data) != entry.get("bytes")):
            raise ValueError(f"Elevator door audio changed without rebuilding its manifest: {key}")
        offset = data.find(b"\x01vorbis")
        if (not data.startswith(b"OggS") or offset < 0
                or int.from_bytes(data[offset + 7:offset + 11], "little") != 0
                or data[offset + 11] != 1
                or int.from_bytes(data[offset + 12:offset + 16], "little") != rate):
            raise ValueError(f"Expected mono Ogg Vorbis for the elevator door recording: {key}")
        patches[name] = data
        recordings[key] = {
            "event": event, "file": name, "audioBytes": len(data), "sha256": entry["sha256"],
            "durationMs": round(entry["durationSeconds"] * 1000),
            "sampleRate": rate, "channels": 1, "playbackPitch": pitch,
            "playbackDurationMs": round(entry["durationSeconds"] / pitch * 1000),
            "processing": entry.get("processing", manifest["processing"]),
        }
    credits = (
        "STAR PROGRAM - elevator door mechanical sounds\n\n"
        f"Source: {source['title']} by joedeshon, Freesound\n{source_page}\n"
        f"License: Creative Commons Attribution 4.0 International (CC BY 4.0)\n{license_url}\n\n"
        "These are modified recordings. Source audio is not included in this resource pack.\n"
        f"Source SHA-256: {source['sha256']}\n\n"
        "Processing and modifications:\n" + json.dumps(manifest["processing"], indent=2) + "\n\n"
        "Derived recordings:\n" + json.dumps(recordings, indent=2) + "\n"
    ).encode("utf-8")
    patches[DOOR_CREDITS_PATH] = credits
    return patches, expected_sounds, {
        "namespace": NAMESPACE, "soundClips": 2,
        "audioBytes": sum(len(patches[DOOR_PATHS[key]]) for key in DOOR_KEYS),
        "monoVorbis": True, "deterministicEvents": True,
        "creditsFile": DOOR_CREDITS_PATH, "source": source,
        "processing": manifest["processing"], "sounds": recordings,
    }


def intercom_patches(root):
    patches, chime_report = chime_patches(root)
    doors, door_sounds, door_report = elevator_door_patches(root.parent / "elevator-audio")
    sounds = json.loads(patches[SOUNDS_PATH])
    if set(doors) & set(patches) or set(door_sounds) & set(sounds):
        raise ValueError("Elevator door overlay would overwrite an existing intercom resource.")
    patches.update(doors)
    patches[SOUNDS_PATH] = (json.dumps({**sounds, **door_sounds}, indent=2) + "\n").encode()
    return patches, {"chime": chime_report, "doors": door_report}
