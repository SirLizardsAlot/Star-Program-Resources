"""Validate complete turbine audio and byte-preserving integration into the current pack."""
import hashlib
import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from build import OUTPUT, PREVIOUS, EXPECTED_PREVIOUS_SHA256, MAX_PACK_BYTES
from turbine_overlay import (turbine_patches, vorbis_frames, EVENT_KEYS, AUDIO_PATHS,
                             NAMESPACE, SOUNDS_PATH, CREDITS_PATH, EXPECTED_ADDED_FILES,
                             PA_IDS, PA_PATHS, PA_CREDITS_PATH)

ROOT = Path(__file__).resolve().parent


class TurbinePack(unittest.TestCase):
    def test_all_prepared_clips_resolve_with_duration_hashes_and_credits(self):
        patches, report = turbine_patches(ROOT / "turbines")
        self.assertEqual(set(patches), EXPECTED_ADDED_FILES)
        self.assertEqual(report["soundClips"], 16)
        self.assertEqual(set(report["sounds"]), set(EVENT_KEYS))
        self.assertLess(report["audioBytes"], 512 * 1024)
        self.assertEqual(report["audioBytes"], sum(len(patches[name]) for name in AUDIO_PATHS.values()))
        self.assertEqual(len(report["sources"]), 5)
        for source in report["sources"]:
            self.assertEqual(source["license"], "CC0-1.0")
            self.assertIn(source["page"].encode(), patches[CREDITS_PATH])
        sounds = json.loads(patches[SOUNDS_PATH])
        for key, entry in report["sounds"].items():
            data = patches[entry["file"]]
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(sounds[key], {"sounds": [{
                "name": f"{NAMESPACE}:{key.replace('.', '/')}", "stream": False}]})
            self.assertAlmostEqual(entry["durationTicks"], vorbis_frames(data) / 32000 * 20, delta=0.001)
        self.assertEqual(report["sounds"]["turbine.running_loop"]["durationTicks"], 120)
        self.assertEqual(report["sounds"]["steam.flow_loop"]["durationTicks"], 8)

    def test_units_have_distinct_stop_sound_events_without_duplicate_audio(self):
        patches, report = turbine_patches(ROOT / "turbines")
        sounds = json.loads(patches[SOUNDS_PATH])
        self.assertEqual(report["unitAliasEvents"], 32)
        self.assertEqual(report["soundEvents"], 56)
        self.assertEqual(len([name for name in patches if name.endswith(".ogg")]), 24)
        for key in EVENT_KEYS:
            for unit in (1, 2):
                alias = f"turbine{unit}.{key}"
                self.assertEqual(sounds[alias], sounds[key])
                self.assertEqual(report["unitEventAliases"][f"unit{unit}"][key], f"{NAMESPACE}:{alias}")
            self.assertNotEqual(report["unitEventAliases"]["unit1"][key], report["unitEventAliases"]["unit2"][key])

    def test_eight_new_pa_messages_use_the_selected_intercom_processing(self):
        patches, report = turbine_patches(ROOT / "turbines")
        pa = report["announcements"]
        self.assertEqual(pa["announcementClips"], 8)
        self.assertEqual(set(pa["announcements"]), set(PA_IDS))
        original = json.loads((ROOT / "tts/announcements/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(pa["processing"], original["processing"])
        sounds = json.loads(patches[SOUNDS_PATH])
        for key, entry in pa["announcements"].items():
            self.assertEqual(entry["event"], f"{NAMESPACE}:pa.{key}")
            self.assertEqual(sounds[f"pa.{key}"], {"sounds": [{"name": f"{NAMESPACE}:pa/{key}", "stream": False}]})
            self.assertEqual(entry["sampleRate"], 22050)
            self.assertEqual(entry["ticks"], math.ceil(vorbis_frames(patches[PA_PATHS[key]], 22050) / 22050 * 20))
        self.assertIn(b"https://ttsmp3.com/faq", patches[PA_CREDITS_PATH])
        self.assertIn(b"commercial and non-commercial", patches[PA_CREDITS_PATH])

    def test_current_pack_preserves_every_v20_entry_and_only_adds_turbine_assets(self):
        patches, _ = turbine_patches(ROOT / "turbines")
        self.assertEqual(hashlib.sha256(PREVIOUS.read_bytes()).hexdigest(), EXPECTED_PREVIOUS_SHA256)
        self.assertLessEqual(OUTPUT.stat().st_size, MAX_PACK_BYTES)
        with ZipFile(PREVIOUS) as old, ZipFile(OUTPUT) as current:
            names = current.namelist()
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(set(names) - set(old.namelist()), EXPECTED_ADDED_FILES)
            self.assertFalse(set(old.namelist()) - set(names))
            for name in old.namelist():
                self.assertEqual(current.read(name), old.read(name), name)
            for name, data in patches.items():
                self.assertEqual(current.read(name), data, name)
            self.assertFalse(any(name.startswith(("turbines/source/", "turbines/previews/")) for name in names))
            self.assertIsNone(current.testzip())

    def test_audio_mutation_is_rejected(self):
        read_bytes = Path.read_bytes

        def changed_audio(path):
            data = read_bytes(path)
            return data + b"changed" if path.as_posix().endswith(AUDIO_PATHS["turbine.running_loop"]) else data

        with patch.object(Path, "read_bytes", changed_audio):
            with self.assertRaisesRegex(ValueError, "audio hash or byte count changed"):
                turbine_patches(ROOT / "turbines")

    def test_registration_cannot_redirect_a_prepared_event(self):
        read_bytes = Path.read_bytes

        def changed_mapping(path):
            data = read_bytes(path)
            return data.replace(b"turbine/running_loop", b"turbine/startup") if path.as_posix().endswith(SOUNDS_PATH) else data

        with patch.object(Path, "read_bytes", changed_mapping):
            with self.assertRaisesRegex(ValueError, "16 deterministic recordings"):
                turbine_patches(ROOT / "turbines")

    def test_changed_provenance_is_rejected(self):
        read_bytes = Path.read_bytes

        def changed_provenance(path):
            data = read_bytes(path)
            return data.replace(b"CC0-1.0", b"CC-BY-4.0") if path.as_posix().endswith("turbines/source/sources.json") else data

        with patch.object(Path, "read_bytes", changed_provenance):
            with self.assertRaisesRegex(ValueError, "source provenance changed"):
                turbine_patches(ROOT / "turbines")

    def test_truncated_ogg_payload_is_rejected(self):
        data = (ROOT / "turbines" / AUDIO_PATHS["turbine.idle_loop"]).read_bytes()
        with self.assertRaisesRegex(ValueError, "Truncated Ogg"):
            vorbis_frames(data[:-1])

    def test_pa_audio_mutation_is_rejected(self):
        read_bytes = Path.read_bytes

        def changed_audio(path):
            data = read_bytes(path)
            return data + b"changed" if path.as_posix().endswith(PA_PATHS["steam_lost"]) else data

        with patch.object(Path, "read_bytes", changed_audio):
            with self.assertRaisesRegex(ValueError, "announcement hash or byte count changed"):
                turbine_patches(ROOT / "turbines")

    def test_pa_timing_cannot_truncate_the_room_tail(self):
        read_text = Path.read_text

        def changed_ticks(path, *args, **kwargs):
            data = read_text(path, *args, **kwargs)
            if path.as_posix().endswith("turbines/announcements/manifest.json"):
                document = json.loads(data)
                document["announcements"]["steam_lost"]["ticks"] = 1
                return json.dumps(document)
            return data

        with patch.object(Path, "read_text", changed_ticks):
            with self.assertRaisesRegex(ValueError, "announcement timing mismatch"):
                turbine_patches(ROOT / "turbines")


if __name__ == "__main__":
    unittest.main()
