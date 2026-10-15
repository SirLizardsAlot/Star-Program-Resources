"""Validate replacements of inherited stereo core audio with positional mono."""
import hashlib
import json
import struct

PREVIOUS_SHA256 = "ea925dd412e61facddffe10a21b678123570cb6516146c3e25b0de47ccd1be62"
EXPECTED_MANIFEST_SHA256 = "4efc661b595cf84f326c4e0ddc6652ba19f1ae502fa88ac74414d1c1d2a76e51"
EVENT_PATHS = {
    "custom.beep1": "assets/minecraft/sounds/custom/beep.ogg",
    "custom.explosioncharge": "assets/minecraft/sounds/custom/reactordetonationcharging.ogg",
    "custom.lasercharge": "assets/minecraft/sounds/custom/charged-laser.ogg",
    "custom.powercharge": "assets/minecraft/sounds/custom/powercharge.ogg",
    "custom.reactorboom": "assets/minecraft/sounds/custom/reactorexplosion.ogg",
    "custom.shieldboom": "assets/minecraft/sounds/custom/shieldboom.ogg",
}
SOURCE_HASHES = dict(zip(EVENT_PATHS.values(), (
    "f14107e83b5ddec84bc499b513b1776e6a1e1a39bc4cd1dbe3f284bc28dbe510",
    "a1ddae634ec19412a3509dccf9fbf77542aa21ed177d03c9dd72502e834dc3fc",
    "11ee7a376683e40ea386a4f3e0235d64ff1b133d8979e6e8ef411cef5737d18a",
    "b23df7d6b851d702863804f914fdb4dc2d81fa1c951a17946dd7ea1d46afd172",
    "daaed7c1ee57f02db9e25b3d285d213ba423268e6f84dc12614e655586c29bf3",
    "3db42a828ffbca17863c9e1982448991cc63a7832694c05882101b04f7bece7e",
)))
CHANGED_FILES = set(EVENT_PATHS.values())
# The beep source has an inherited 1024-frame initial granule offset. Its
# decoded waveform is 46080 frames; retain that waveform without adding silence.
SOURCE_DECODED_FRAMES = dict(zip(EVENT_PATHS, (46080, 2016256, 207936, 1004307, 1442816, 506880)))
POWERSWITCH_PATH = "assets/minecraft/sounds/custom/loud-lightswitch.ogg"
POWERSWITCH_SHA256 = "f84912587da3207c9c802539fd97e3282014eb4902bce2116b6d7dbac565b22a"
PROCESSING = {"downmix": "arithmetic mean of left and right channels",
              "gain": 1.0, "filter": False, "normalization": False,
              "resampling": False, "trimming": False, "pitchDsp": False,
              "vorbisQuality": 0.5}


def vorbis_info(data):
    """Read the identification packet and final granule without decoding audio."""
    offset = data.find(b"\x01vorbis")
    if (not data.startswith(b"OggS") or offset < 0
            or int.from_bytes(data[offset + 7:offset + 11], "little") != 0):
        raise ValueError("Expected Ogg Vorbis core audio")
    channels = data[offset + 11]
    rate = int.from_bytes(data[offset + 12:offset + 16], "little")
    cursor, frames = 0, None
    while cursor < len(data):
        if len(data) - cursor < 27 or data[cursor:cursor + 4] != b"OggS":
            raise ValueError("Malformed Ogg page in core audio")
        segments = data[cursor + 26]
        header_end = cursor + 27 + segments
        if header_end > len(data):
            raise ValueError("Truncated Ogg header in core audio")
        end = header_end + sum(data[cursor + 27:header_end])
        if end > len(data):
            raise ValueError("Truncated Ogg payload in core audio")
        granule = struct.unpack_from("<Q", data, cursor + 6)[0]
        if granule != 0xFFFFFFFFFFFFFFFF:
            frames = granule
        cursor = end
    if not frames or not channels or not rate:
        raise ValueError("Incomplete core audio metadata")
    return {"channels": channels, "sampleRate": rate, "frames": frames}


def core_audio_patches(root, source):
    manifest_bytes = (root / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Prepared core mono manifest changed; review its source and processing first")
    manifest = json.loads(manifest_bytes)
    if (manifest.get("version") != 1
            or manifest.get("sourceArchive") != {"file": "sp_v21-mc26.2.zip", "sha256": PREVIOUS_SHA256}
            or manifest.get("processing") != PROCESSING
            or set(manifest.get("sounds", {})) != set(EVENT_PATHS)):
        raise ValueError("Core downmix manifest must preserve all six source recordings and processing")
    if hashlib.sha256(source[POWERSWITCH_PATH]).hexdigest() != POWERSWITCH_SHA256:
        raise ValueError("The already mono power switch recording changed")
    if vorbis_info(source[POWERSWITCH_PATH])["channels"] != 1:
        raise ValueError("The power switch must remain the existing mono recording")
    mappings = json.loads(source["assets/minecraft/sounds.json"])
    patches, recordings = {}, {}
    for event, name in EVENT_PATHS.items():
        entry = manifest["sounds"][event]
        source_bytes = source[name]
        if (hashlib.sha256(source_bytes).hexdigest() != SOURCE_HASHES[name]
                or entry.get("sourceSha256") != SOURCE_HASHES[name]
                or entry.get("sourceBytes") != len(source_bytes)
                or entry.get("sourceFile") != "source/" + name):
            raise ValueError(f"Core source audio changed: {event}")
        source_info = vorbis_info(source_bytes)
        if source_info["channels"] != 2:
            raise ValueError(f"Core source audio is not stereo: {event}")
        if mappings[event] != {"category": "master", "sounds": [name.removeprefix("assets/minecraft/sounds/").removesuffix(".ogg")]}:
            raise ValueError(f"Core event mapping changed: {event}")
        data = (root / name).read_bytes()
        if (entry.get("file") != name or entry.get("sha256") != hashlib.sha256(data).hexdigest()
                or entry.get("bytes") != len(data)):
            raise ValueError(f"Core mono audio hash or byte count changed: {event}")
        expected = {**source_info, "channels": 1, "frames": SOURCE_DECODED_FRAMES[event]}
        if (vorbis_info(data) != expected
                or any(entry.get(key) != value for key, value in expected.items())
                or entry.get("sourceChannels") != 2
                or entry.get("sourceContainerFrames") != source_info["frames"]
                or abs(entry.get("durationSeconds", -1) - expected["frames"] / expected["sampleRate"]) > 1e-9):
            raise ValueError(f"Core mono audio timing or channel layout changed: {event}")
        patches[name] = data
        recordings[event] = entry
    return patches, {"soundClips": len(recordings), "monoVorbis": True,
                     "sourceArchive": manifest["sourceArchive"], "processing": PROCESSING,
                     "manifestSha256": EXPECTED_MANIFEST_SHA256,
                     "audioBytes": sum(len(data) for data in patches.values()), "sounds": recordings,
                     "unchangedMono": manifest["unchangedMono"], "provenance": manifest["provenance"]}
