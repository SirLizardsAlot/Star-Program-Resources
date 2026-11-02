"""Make Sky Panel models while retaining vanilla oak-trapdoor block states.

The body uses tinted glass on every face. A single sky face points toward the
mounting side, leaving the exposed side as see-through tinted glass.
The sky sits 0.01 model pixels inside the mounting face to avoid a coplanar
surface with a supporting block.
"""
from __future__ import annotations

import json


FACES = ('down', 'up', 'north', 'south', 'west', 'east')
SKY_UV = [0, 0, 1, 2]  # 16 by 16 marker region in the 256 by 128 data sprite.
PANEL_SPEC = {
    'bottom': {
        'from': [0, 0, 0], 'to': [16, 3, 16],
        'mount': 'down', 'front': 'up',
        'back_from': [0, 0, 0], 'back_to': [16, 0.01, 16],
    },
    'top': {
        'from': [0, 13, 0], 'to': [16, 16, 16],
        'mount': 'up', 'front': 'down',
        'back_from': [0, 15.99, 0], 'back_to': [16, 16, 16],
    },
    'open': {
        'from': [0, 0, 13], 'to': [16, 16, 16],
        'mount': 'south', 'front': 'north',
        'back_from': [0, 0, 15.99], 'back_to': [16, 16, 16],
    },
}


def make_panels() -> dict[str, bytes]:
    """Return only the three oak-trapdoor model overrides, encoded as JSON."""
    result = {}
    for variant, spec in PANEL_SPEC.items():
        glass_faces = {face: {'uv': [0, 0, 16, 16], 'texture': '#glass'} for face in FACES}
        sky_faces = {face: {'uv': SKY_UV, 'texture': '#sky'}
                     for face in (spec['mount'],)}
        model = {
            'parent': 'minecraft:block/thin_block',
            'ambientocclusion': False,
            'textures': {
                'particle': 'minecraft:block/tinted_glass',
                'glass': 'minecraft:block/tinted_glass',
                'sky': 'dfsky:block/sky_marker',
            },
            'elements': [
                {'from': spec['from'], 'to': spec['to'], 'shade': False, 'faces': glass_faces},
                {'from': spec['back_from'], 'to': spec['back_to'], 'shade': False, 'faces': sky_faces},
            ],
        }
        name = f'assets/minecraft/models/block/oak_trapdoor_{variant}.json'
        result[name] = (json.dumps(model, indent=2) + '\n').encode('utf-8')
    return result
