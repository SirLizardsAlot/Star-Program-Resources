import unittest

import prepare_data as data


class SkyDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.arrays = data.source_data()
        cls.patches = data.make_data()
        cls.png = cls.patches['assets/dfsky/textures/block/sky_marker.png']
        cls.pixels = data.decode_generated_png(cls.png)

    def test_every_native_cloud_and_celestial_texel_is_preserved(self):
        result = data.verify_pixels(self.pixels, self.arrays)
        self.assertEqual(result['cloudCellsCompared'], 65536)
        self.assertEqual(result['occupiedCloudCells'], 18103)
        self.assertEqual(result['celestialTexelsCompared'], 2048)

    def test_both_texture_resources_are_identical_and_fully_opaque(self):
        self.assertEqual(self.png, self.patches['assets/dfsky/textures/effect/sky_data.png'])
        self.assertTrue(all(alpha == 255 for alpha in self.pixels[3::4]))
        self.assertEqual(data.decode_generated_png(data.png_rgba(self.pixels)), self.pixels)

    def test_marker_header_and_payload_regions_do_not_overlap(self):
        regions = [value for key, value in data.LAYOUT.items() if key != 'header']
        for i, (ax, ay, aw, ah) in enumerate(regions):
            for bx, by, bw, bh in regions[i + 1:]:
                self.assertTrue(ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)
        for x, y in data.LAYOUT['header']:
            self.assertTrue(all(not (rx <= x < rx + rw and ry <= y < ry + rh) for rx, ry, rw, rh in regions))

    def test_wrapped_cloud_coordinates_keep_old_bitmask_semantics(self):
        for x, y in [(-1, -1), (-256, 256), (256, 256), (511, 1023), (-1001, 9123)]:
            index = (x & 255) + (y & 255) * 256
            byte_index = index >> 3
            offset = ((16 + (byte_index >> 7)) * data.WIDTH + (byte_index & 127)) * 4
            self.assertEqual(bool(self.pixels[offset] & (1 << (index & 7))), data.cloud_value(self.arrays, x, y))

    def test_shader_access_preserves_old_uv_edges_without_constant_arrays(self):
        source = self.patches[data.SOURCE_INCLUDE].decode()
        self.assertIn('#ifndef DFSKY_SAMPLER', source)
        self.assertIn('ivec2 dfskyDataOrigin = ivec2(0);', source)
        self.assertIn('min(ivec2(floor(uv * 32.0)), ivec2(31))', source)
        self.assertEqual(source.count('any(greaterThan(uv, vec2(1.0)))'), 2)
        self.assertNotIn('const uint ', source)
        self.assertNotIn('DFSKY_CLOUD_MASK[', source)
        self.assertLess(len(source), len(self.original) // 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
