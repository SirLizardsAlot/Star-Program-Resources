import itertools
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

from panel_models import FACES, PANEL_SPEC, make_panels


def rotated_bounds(element, degrees):
    """Exact quarter-turn model rotation about vanilla's block centre."""
    points = list(itertools.product(*zip(element['from'], element['to'])))
    for turn in range(degrees // 90):
        points = [(16 - point[2], point[1], point[0]) for point in points]
    return [min(point[axis] for point in points) for axis in range(3)], [max(point[axis] for point in points) for axis in range(3)]


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {name: json.loads(data) for name, data in make_panels().items()}
        jar = Path(__file__).resolve().parent.parent / 'mc26.3/reference/minecraft-client.jar'
        with ZipFile(jar) as archive:
            cls.variants = json.loads(archive.read('assets/minecraft/blockstates/oak_trapdoor.json'))['variants']

    def test_only_native_three_model_identifiers_are_overridden(self):
        self.assertEqual(set(self.models), {f'assets/minecraft/models/block/oak_trapdoor_{variant}.json' for variant in ('bottom', 'top', 'open')})
        self.assertEqual(len(self.variants), 16)
        for state, variant in self.variants.items():
            self.assertIn('assets/' + variant['model'].replace(':', '/models/') + '.json', self.models)

    def test_full_panel_bounds_follow_all_sixteen_native_states(self):
        for state, variant in self.variants.items():
            properties = dict(pair.split('=') for pair in state.split(','))
            model = self.models['assets/' + variant['model'].replace(':', '/models/') + '.json']
            actual = rotated_bounds(model['elements'][0], variant.get('y', 0))
            if properties['open'] == 'false':
                expected = ([0, 0, 0], [16, 3, 16]) if properties['half'] == 'bottom' else ([0, 13, 0], [16, 16, 16])
            else:
                expected = {
                    'north': ([0, 0, 13], [16, 16, 16]),
                    'east': ([0, 0, 0], [3, 16, 16]),
                    'south': ([0, 0, 0], [16, 16, 3]),
                    'west': ([13, 0, 0], [16, 16, 16]),
                }[properties['facing']]
            self.assertEqual(actual, expected, state)

    def test_only_exposed_side_and_edges_have_glass_and_mounting_side_is_pure_sky(self):
        for variant, spec in PANEL_SPEC.items():
            model = self.models[f'assets/minecraft/models/block/oak_trapdoor_{variant}.json']
            body, backing = model['elements']
            self.assertEqual(set(body['faces']), set(FACES) - {spec['mount']})
            self.assertIn(spec['front'], body['faces'])
            self.assertNotIn(spec['mount'], body['faces'])
            self.assertTrue(all(face['texture'] == '#glass' for face in body['faces'].values()))
            self.assertEqual(set(backing['faces']), {spec['mount']})
            self.assertNotIn(spec['front'], backing['faces'])
            self.assertTrue(all(face['texture'] == '#sky' for face in backing['faces'].values()))
            self.assertEqual(model['textures']['glass'], 'minecraft:block/tinted_glass')
            self.assertEqual(model['textures']['sky'], 'dfsky:block/sky_marker')

    def test_single_sided_backing_is_inside_body_and_never_neighbor_culled(self):
        axis_for = {'down': 1, 'up': 1, 'south': 2}
        for variant, spec in PANEL_SPEC.items():
            body, backing = self.models[f'assets/minecraft/models/block/oak_trapdoor_{variant}.json']['elements']
            axis = axis_for[spec['mount']]
            self.assertAlmostEqual(backing['to'][axis] - backing['from'][axis], .01)
            for coordinate in range(3):
                self.assertGreaterEqual(backing['from'][coordinate], body['from'][coordinate])
                self.assertLessEqual(backing['to'][coordinate], body['to'][coordinate])
            if spec['mount'] == 'down':
                self.assertEqual(backing['from'][axis], 0)
                self.assertGreater(backing['to'][axis], 0)
                self.assertLess(backing['to'][axis], body['to'][axis])
            else:
                self.assertEqual(backing['to'][axis], 16)
                self.assertLess(backing['from'][axis], 16)
                self.assertGreater(backing['from'][axis], body['from'][axis])
            for face in backing['faces'].values():
                self.assertNotIn('cullface', face)
            self.assertNotIn('cullface', body['faces'][spec['front']])

    def test_thin_block_inventory_parent_and_deterministic_output(self):
        self.assertEqual(make_panels(), make_panels())
        for model in self.models.values():
            self.assertEqual(model['parent'], 'minecraft:block/thin_block')
            self.assertFalse(model['ambientocclusion'])
            self.assertEqual(model['textures']['particle'], 'minecraft:block/tinted_glass')
            self.assertTrue(all(element['shade'] is False for element in model['elements']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
