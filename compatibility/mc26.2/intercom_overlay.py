"""Include only the approved elevator chime, with its CC0 provenance."""
import hashlib
import json


NAMESPACE = "star_program_intercom"
EVENT = NAMESPACE + ":chime.two_tone"
AUDIO_PATH = f"assets/{NAMESPACE}/sounds/chime/two_tone.ogg"
SOUNDS_PATH = f"assets/{NAMESPACE}/sounds.json"
CREDITS_PATH = f"credits/{NAMESPACE}/two_tone.txt"
EXPECTED_AUDIO_SHA256 = "15612357d1928c347b1a2a7f274d585482326b4892376bf8ab80a49dfe3aefe2"
EXPECTED_SOURCE_SHA256 = "7a35c22d17119adfdb4970219fec03033861882dd9c4cc3bcf6960efa3f74d43"


def intercom_patches(root):
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
