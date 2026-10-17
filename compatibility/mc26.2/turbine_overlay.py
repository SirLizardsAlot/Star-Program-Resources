"""Package the prepared turbine sounds without re-encoding or touching other assets."""
import hashlib
import json
import math
import struct


NAMESPACE = "star_program_turbines"
SOUNDS_PATH = f"assets/{NAMESPACE}/sounds.json"
CREDITS_PATH = f"credits/{NAMESPACE}/turbine_audio.txt"
EXPECTED_MANIFEST_SHA256 = "3f97875ae0200ffb20c533c2133892c47b3111d7ed9489ba01aca301dc229d26"
EXPECTED_CREDITS_SHA256 = "8320799e8224ff3f0e3bcabaecbd3667cbafc22334048df8d774d4f96aba6289"
EVENT_KEYS = (
    "turbine.idle_loop", "turbine.running_loop", "turbine.high_load_loop",
    "turbine.vibration_loop", "turbine.startup", "turbine.coastdown", "turbine.trip",
    "steam.release_01", "steam.release_02", "steam.release_03", "steam.release_04",
    "steam.release_05", "steam.flow_loop", "auxiliary.start", "auxiliary.end",
    "auxiliary.running_loop",
)
AUDIO_PATHS = {key: f"assets/{NAMESPACE}/sounds/{key.replace('.', '/')}.ogg" for key in EVENT_KEYS}
PA_IDS = ("turbine_1_starting", "turbine_2_starting", "turbine_1_online", "turbine_2_online",
          "turbine_1_stopping", "turbine_2_stopping", "steam_lost", "generation_lost")
PA_PATHS = {key: f"assets/{NAMESPACE}/sounds/pa/{key}.ogg" for key in PA_IDS}
PA_CREDITS_PATH = f"credits/{NAMESPACE}/pa_announcements.txt"
EXPECTED_ADDED_FILES = {SOUNDS_PATH, CREDITS_PATH, *AUDIO_PATHS.values(), PA_CREDITS_PATH, *PA_PATHS.values()}
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def vorbis_frames(data, rate=32000):
    """Check the mono Vorbis header and read its final Ogg granule/sample count."""
    offset = data.find(b"\x01vorbis")
    if (not data.startswith(b"OggS") or offset < 0
            or int.from_bytes(data[offset + 7:offset + 11], "little") != 0
            or data[offset + 11] != 1
            or int.from_bytes(data[offset + 12:offset + 16], "little") != rate):
        raise ValueError(f"Expected mono {rate} Hz Ogg Vorbis for every turbine recording.")
    cursor, final_granule = 0, None
    while cursor < len(data):
        if len(data) - cursor < 27 or data[cursor:cursor + 4] != b"OggS":
            raise ValueError("Malformed Ogg page in turbine recording.")
        segments = data[cursor + 26]
        header_end = cursor + 27 + segments
        if header_end > len(data):
            raise ValueError("Truncated Ogg page in turbine recording.")
        page_end = header_end + sum(data[cursor + 27:header_end])
        if page_end > len(data):
            raise ValueError("Truncated Ogg payload in turbine recording.")
        granule = struct.unpack_from("<Q", data, cursor + 6)[0]
        if granule != 0xFFFFFFFFFFFFFFFF:
            final_granule = granule
        cursor = page_end
    if not final_granule:
        raise ValueError("Turbine recording has no final sample count.")
    return final_granule


def turbine_pa_patches(root):
    """Keep the eight whole-message turbine notices separate from the original PA bank."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    map_bytes = (root / "source-map.json").read_bytes()
    source_map = json.loads(map_bytes)
    source_entries = {entry["id"]: entry for entry in source_map["announcements"]}
    if (manifest.get("version") != 1 or manifest.get("namespace") != NAMESPACE
            or manifest.get("mode") != "announcements" or manifest.get("sampleRate") != 22050
            or manifest.get("channels") != 1 or manifest.get("voice") != "Matthew"
            or manifest.get("nativeRatePercent") != 100 or set(manifest.get("announcements", {})) != set(PA_IDS)
            or len(source_map["announcements"]) != len(PA_IDS) or set(source_entries) != set(PA_IDS)
            or hashlib.sha256(map_bytes).hexdigest() != manifest.get("sourceMapSha256")):
        raise ValueError("Expected all eight complete source-mapped Matthew turbine announcements.")
    processing = manifest.get("processing", {})
    if (processing.get("effect") != "intercom" or processing.get("masterGain") != 1.5
            or processing.get("vorbisQuality") != 0.65 or processing.get("pitchDsp") is not False
            or processing.get("waveformSpeedDsp") is not False
            or processing.get("room") != {"tailMs": 650, "predelayMs": 25, "wet": 0.17, "decayMs": 180, "seed": 4118}):
        raise ValueError("Turbine announcements must preserve the selected whole-message intercom processing.")
    license_data = manifest.get("license", {})
    if (license_data.get("permissionUrl") != "https://ttsmp3.com/faq"
            or license_data.get("provider") not in {"ttsMP3 standard Matthew UI", "ttsMP3 paid members UI"}
            or license_data.get("provider") != source_map.get("provider")
            or manifest.get("engine") != source_map.get("provider") or license_data.get("voice") != "Matthew"):
        raise ValueError("Turbine announcements must retain the provider's commercial-use permission provenance.")
    patches, sounds, recordings = {}, {}, {}
    for key in PA_IDS:
        entry, source, name = manifest["announcements"][key], source_entries[key], PA_PATHS[key]
        event = f"{NAMESPACE}:pa.{key}"
        if (entry.get("file") != name or entry.get("event") != event or entry.get("text") != source.get("text")
                or entry.get("source", {}).get("sha256") != source.get("sourceSha256")):
            raise ValueError(f"Turbine announcement source or registration mismatch: {key}")
        source_path = root / entry["source"]["file"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sourceSha256"]:
            raise ValueError(f"Turbine announcement source recording changed: {key}")
        data = (root / name).read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Turbine announcement hash or byte count changed: {key}")
        frames = vorbis_frames(data, 22050)
        if (abs(entry.get("durationMs", -1) - frames * 1000 / 22050) > 0.001
                or entry.get("ticks") != math.ceil(frames * 20 / 22050)):
            raise ValueError(f"Turbine announcement timing mismatch: {key}")
        patches[name] = data
        sounds[f"pa.{key}"] = {"sounds": [{"name": f"{NAMESPACE}:pa/{key}", "stream": False}]}
        recordings[key] = {**entry, "sampleRate": 22050, "channelCount": 1, "frames": frames}
    credits = ("STAR PROGRAM - turbine hall PA announcements\n\n"
               f"Eight new whole-message Matthew stock-voice renders generated through {license_data['provider']}.\n"
               "ttsMP3 permits commercial and non-commercial use of generated audio, for free and paid usage.\n"
               "https://ttsmp3.com/faq\n\n"
               "Source MP3s are preserved outside the resource pack. Existing facility announcements are unchanged.\n"
               "No pitch or waveform-speed manipulation. Mono 22050 Hz Vorbis quality 0.65; speaker EQ and facility room; master gain 1.5.\n\n"
               "Generation provenance:\n" + json.dumps(manifest.get("sourceMapMetadata", {}), indent=2) + "\n\n"
               "Recordings, source hashes, and processing:\n" + json.dumps(recordings, indent=2) + "\n").encode("utf-8")
    patches[PA_CREDITS_PATH] = credits
    return patches, sounds, {"announcementClips": len(recordings), "audioBytes": sum(row["bytes"] for row in recordings.values()),
                             "processing": processing, "license": license_data, "creditsFile": PA_CREDITS_PATH,
                             "sourceMapSha256": manifest["sourceMapSha256"], "announcements": recordings}


def turbine_patches(root):
    manifest_bytes = (root / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Prepared turbine manifest changed; review and rebuild its audio provenance first.")
    manifest = json.loads(manifest_bytes)
    if (manifest.get("version") != 1 or manifest.get("namespace") != NAMESPACE
            or manifest.get("sampleRate") != 32000
            or set(manifest.get("sounds", {})) != set(EVENT_KEYS)):
        raise ValueError("Expected exactly the 16 prepared turbine recordings.")
    provenance_bytes = (root / "source/sources.json").read_bytes()
    if hashlib.sha256(provenance_bytes).hexdigest() != manifest["sources"]["sources.json"]:
        raise ValueError("Turbine source provenance changed.")
    sources = json.loads(provenance_bytes)["sources"]
    if len(sources) != 5 or any(source.get("license") != "CC0-1.0"
                               or source.get("license_url") != LICENSE_URL for source in sources):
        raise ValueError("All turbine audio sources must retain their CC0 provenance.")
    source_credits = [{"id": source["id"], "title": source["title"], "creator": source["creator"],
                       "page": source["page_url"], "license": source["license"],
                       "licenseUrl": source["license_url"]} for source in sources]
    expected_sounds = {key: {"sounds": [{"name": f"{NAMESPACE}:{key.replace('.', '/')}", "stream": False}]}
                       for key in EVENT_KEYS}
    sound_bytes = (root / SOUNDS_PATH).read_bytes()
    if json.loads(sound_bytes) != expected_sounds:
        raise ValueError("Turbine registrations must resolve to exactly the 16 deterministic recordings.")
    credits = (root / "CREDITS.txt").read_bytes()
    if hashlib.sha256(credits).hexdigest() != EXPECTED_CREDITS_SHA256:
        raise ValueError("Prepared turbine sound credits changed.")
    unit_event_aliases = {f"unit{unit}": {key: f"{NAMESPACE}:turbine{unit}.{key}" for key in EVENT_KEYS}
                          for unit in (1, 2)}
    alias_sounds = {f"turbine{unit}.{key}": expected_sounds[key] for unit in (1, 2) for key in EVENT_KEYS}
    patches, recordings = {SOUNDS_PATH: sound_bytes, CREDITS_PATH: credits}, {}
    for key in EVENT_KEYS:
        entry, name = manifest["sounds"][key], AUDIO_PATHS[key]
        seconds, ticks = entry.get("durationSeconds"), entry.get("durationTicks")
        if (entry.get("event") != f"{NAMESPACE}:{key}" or entry.get("file") != name
                or entry.get("sampleRate") != 32000 or entry.get("channels") != 1
                or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0
                or not isinstance(ticks, (int, float)) or abs(ticks - seconds * 20) > 0.0001):
            raise ValueError(f"Prepared turbine metadata mismatch: {key}")
        data = (root / name).read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Prepared turbine audio hash or byte count changed: {key}")
        frames = vorbis_frames(data)
        if abs(frames / 32000 - seconds) > 2 / 32000:
            raise ValueError(f"Turbine duration does not match its encoded sample count: {key}")
        patches[name] = data
        recordings[key] = {"event": entry["event"], "file": name, "loop": entry["loop"],
                           "durationSeconds": seconds, "durationTicks": ticks,
                           "frames": frames, "sampleRate": 32000, "channels": 1,
                           "audioBytes": len(data), "sha256": entry["sha256"],
                           "processing": entry["processing"]}
    pa_assets, pa_sounds, pa_report = turbine_pa_patches(root / "announcements")
    if set(patches) & set(pa_assets) or set(expected_sounds) & set(pa_sounds):
        raise ValueError("Turbine PA would overwrite another turbine sound.")
    patches.update(pa_assets)
    patches[SOUNDS_PATH] = (json.dumps({**expected_sounds, **alias_sounds, **pa_sounds}, indent=2) + "\n").encode("utf-8")
    return patches, {"namespace": NAMESPACE, "soundClips": len(recordings),
                     "audioBytes": sum(entry["audioBytes"] for entry in recordings.values()),
                     "monoVorbis": True, "deterministicEvents": True,
                     "creditsFile": CREDITS_PATH, "sources": source_credits,
                     "manifestSha256": EXPECTED_MANIFEST_SHA256, "sounds": recordings,
                     "unitEventAliases": unit_event_aliases, "unitAliasEvents": len(alias_sounds),
                     "soundEvents": len(expected_sounds) + len(alias_sounds) + len(pa_sounds),
                     "announcements": pa_report,
                     "totalAudioBytes": sum(entry["audioBytes"] for entry in recordings.values()) + pa_report["audioBytes"]}
