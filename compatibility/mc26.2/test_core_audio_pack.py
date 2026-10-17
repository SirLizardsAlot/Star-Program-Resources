"""Core audio becomes positional without changing events or unrelated pack data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from build import OUTPUT, PREVIOUS, MAX_PACK_BYTES
from core_audio_overlay import (core_audio_patches, vorbis_info, EVENT_PATHS,
                                SOURCE_HASHES, CHANGED_FILES, PREVIOUS_SHA256,
                                POWERSWITCH_PATH, POWERSWITCH_SHA256, PROCESSING,
                                SOURCE_DECODED_FRAMES)

ROOT = Path(__file__).resolve().parent


class CoreAudioPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ZipFile(PREVIOUS) as pack:
            cls.source = {name: pack.read(name) for name in pack.namelist()}
        cls.patches, cls.report = core_audio_patches(ROOT / "core-audio", cls.source)

    def test_all_six_mono_recordings_retain_native_rates_durations_and_event_mappings(self):
        self.assertEqual(set(self.patches), CHANGED_FILES)
        self.assertEqual(self.report["processing"], PROCESSING)
        self.assertEqual(self.report["soundClips"], 6)
        for event, name in EVENT_PATHS.items():
            original = vorbis_info(self.source[name])
            mono = vorbis_info(self.patches[name])
            self.assertEqual(original["channels"], 2, event)
            self.assertEqual(mono, {**original, "channels": 1, "frames": SOURCE_DECODED_FRAMES[event]}, event)
            self.assertIn(mono["sampleRate"], (24000, 48000))
            entry = self.report["sounds"][event]
            self.assertEqual(entry["sha256"], hashlib.sha256(self.patches[name]).hexdigest())
            self.assertEqual(entry["sourceSha256"], SOURCE_HASHES[name])
            self.assertEqual(entry["sourceContainerFrames"], original["frames"])
            self.assertEqual((ROOT / "core-audio" / entry["sourceFile"]).read_bytes(), self.source[name])

    def test_archive_changes_exactly_six_audio_files_and_preserves_all_other_bytes(self):
        self.assertEqual(hashlib.sha256(PREVIOUS.read_bytes()).hexdigest(), PREVIOUS_SHA256)
        self.assertLessEqual(OUTPUT.stat().st_size, MAX_PACK_BYTES)
        with ZipFile(OUTPUT) as current:
            names = current.namelist()
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(set(names), set(self.source))
            changed = {name for name in names if current.read(name) != self.source[name]}
            self.assertEqual(changed, CHANGED_FILES)
            self.assertIsNone(current.testzip())
            for name, data in self.patches.items():
                self.assertEqual(current.read(name), data, name)
            self.assertEqual(current.read("assets/minecraft/sounds.json"), self.source["assets/minecraft/sounds.json"])
            for name in names:
                if name.startswith(("credits/", "assets/star_program/", "assets/star_program_turbines/", "assets/star_program_intercom/")):
                    self.assertEqual(current.read(name), self.source[name], name)

    def test_already_mono_power_switch_is_byte_identical(self):
        self.assertNotIn(POWERSWITCH_PATH, self.patches)
        self.assertEqual(hashlib.sha256(self.source[POWERSWITCH_PATH]).hexdigest(), POWERSWITCH_SHA256)
        self.assertEqual(vorbis_info(self.source[POWERSWITCH_PATH])["channels"], 1)
        self.assertEqual(vorbis_info(self.source[POWERSWITCH_PATH])["sampleRate"], 44100)
        with ZipFile(OUTPUT) as current:
            self.assertEqual(current.read(POWERSWITCH_PATH), self.source[POWERSWITCH_PATH])

    def test_decoded_waveforms_follow_the_unfiltered_downmix_without_gain_or_timing_changes(self):
        spec = importlib.util.spec_from_file_location("core_downmix_builder", ROOT / "core-audio/build_audio.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        io = builder.audio.AudioIO(Path(r"C:\Program Files\Audacity\sndfile.dll"))
        for event, entry in self.report["sounds"].items():
            source, rate = io.read(ROOT / "core-audio" / entry["sourceFile"])
            encoded, output_rate = io.read(ROOT / "core-audio" / entry["file"])
            reference = np.mean(source, axis=1)
            self.assertEqual(output_rate, rate)
            self.assertEqual(encoded.shape, (len(reference), 1))
            actual = encoded[:, 0]
            self.assertTrue(np.isfinite(actual).all())
            # A second lossy encode can add small waveform error; it must still
            # closely follow the exact L/R average and retain its RMS level.
            self.assertLess(np.sqrt(np.mean((actual - reference) ** 2)),
                            np.sqrt(np.mean(reference ** 2)) * 0.13, event)
            self.assertAlmostEqual(np.sqrt(np.mean(actual ** 2)) / np.sqrt(np.mean(reference ** 2)),
                                   1, delta=0.02, msg=event)

    def test_mutated_mono_audio_is_rejected(self):
        read_bytes = Path.read_bytes
        changed_name = EVENT_PATHS["custom.beep1"]
        def changed(path):
            data = read_bytes(path)
            return data + b"changed" if path.as_posix().endswith(changed_name) else data
        with patch.object(Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "mono audio hash or byte count changed"):
                core_audio_patches(ROOT / "core-audio", self.source)

    def test_mutated_source_or_event_mapping_is_rejected(self):
        source = dict(self.source)
        source[EVENT_PATHS["custom.beep1"]] += b"changed"
        with self.assertRaisesRegex(ValueError, "source audio changed"):
            core_audio_patches(ROOT / "core-audio", source)
        source = dict(self.source)
        mapping = json.loads(source["assets/minecraft/sounds.json"])
        mapping["custom.beep1"]["sounds"] = ["custom/loud-lightswitch"]
        source["assets/minecraft/sounds.json"] = json.dumps(mapping).encode()
        with self.assertRaisesRegex(ValueError, "event mapping changed"):
            core_audio_patches(ROOT / "core-audio", source)

    def test_mutated_manifest_or_power_switch_is_rejected(self):
        read_bytes = Path.read_bytes
        def changed(path):
            data = read_bytes(path)
            return data + b" " if path.as_posix().endswith("core-audio/manifest.json") else data
        with patch.object(Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "mono manifest changed"):
                core_audio_patches(ROOT / "core-audio", self.source)
        source = dict(self.source)
        source[POWERSWITCH_PATH] += b"changed"
        with self.assertRaisesRegex(ValueError, "power switch recording changed"):
            core_audio_patches(ROOT / "core-audio", source)

    def test_truncated_vorbis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Truncated Ogg"):
            vorbis_info(self.patches[EVENT_PATHS["custom.beep1"]][:-1])


if __name__ == "__main__":
    unittest.main()
