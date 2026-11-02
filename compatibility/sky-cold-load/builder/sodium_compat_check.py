"""Compile the actual cold-load ZIP with the installed Sodium Extra transform.

Uses the existing 26.3 ShaderC/stage-interface validator. Does not start a game,
connect to the plot, transfer code, or publish files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
SKY = HERE.parent
DEFAULT_PACK = SKY / 'sp_sky-cold-load-mc26.3.zip'
EXPECTED_SHA256 = 'f934eea1eaae516f3dd7f6a5e2b36952c92bd6f0a7268d03a9f9b629e02411e6'


def module(name, source):
    spec = importlib.util.spec_from_file_location(name, source)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_audit(pack, camera):
    """Check the final archive has the exact formulas covered by bobbing_check.

    Exact source tests complement the independent CPU/GPU formula regression.
    They do not infer renderer behavior from an uncompiled source alone.
    """
    geometry = [
        ('assets/minecraft/shaders/core/terrain.vsh', 'dfskyRay', 'pos', 'ProjMat', 'ModelViewMat'),
        ('assets/minecraft/shaders/core/block.vsh', 'dfskyRay', 'pos', 'ProjMat', 'ModelViewMat'),
        ('assets/minecraft/shaders/core/item.vsh', 'dfskyRay', 'Position', 'ProjMat', 'ModelViewMat'),
        ('assets/sodium/shaders/blocks/block_layer_opaque.vsh', 'spSkyRay', 'position', 'u_ProjectionMatrix', 'u_ModelViewMatrix'),
    ]
    checked = []
    for name, varying, position, projection, view in geometry:
        data = pack.read(name)
        text = data.decode()
        assert camera.WORLD_RAY in text, name + ': full-projection ray helper differs'
        assert f'{varying} = spSkyWorldRay({position}, {projection}, {view});' in text
        checked.append({'file': name, 'sha256': sha(data)})
    particle_vertex = pack.read(camera.PARTICLE + 'vsh').decode()
    particle_fragment = pack.read(camera.PARTICLE + 'fsh').decode()
    reader = pack.read(camera.READER).decode()
    post = pack.read(camera.POST).decode()
    assert camera.CLIP_MATRIX in particle_vertex
    assert camera.CAMERA_CARRIER in particle_vertex
    assert 'mat3 map = inverse(mat3(ModelViewMat)) * inverse(clip);' in particle_vertex
    assert '? map / scale : mat3(0.0)' in particle_vertex
    assert 'spCameraRotation[component / 3][component % 3] * 0.5 + 0.5' in particle_fragment
    assert 'int(round(clamp(value, 0.0, 1.0) * 65535.0))' in particle_fragment
    assert 'spCameraWord(column * 3 + row) * (2.0 / 65535.0) - 1.0' in reader
    assert 'spCameraToWorld * vec3(uv * 2.0 - 1.0, 1.0)' in post
    assert 'spCameraToWorld * vec3((uv * 2.0 - 1.0) / spProjection, -1.0)' not in post
    assert 'ivec4(83, 80, 52, 3)' in reader
    return {
        'geometryHelpersMatchIndependentBobbingRegression': True,
        'projectionRowsUsed': ['x', 'y', 'w'],
        'geometryRay': 'p - inverse(ModelView3) * (-inverse(A) * t)',
        'postScreenMap': 'inverse(ModelView3) * inverse(A)',
        'screenMapEncoding': 'max-absolute normalize nine entries, then round [-1,1] into unsigned 16-bit words',
        'postRay': 'normalize(decodedScreenMap * vec3(ndc, 1))',
        'metadataCarriersPerMarkerSet': 1,
        'geometrySources': checked,
    }


def run(pack_path):
    helpers = module('cold_sodium_helpers', SKY / 'sodium_compat_test.py')
    validator = module('cold_sodium_validator', SKY / 'validate_shaders.py')
    camera = module('cold_camera_audit', HERE / 'patch_camera.py')
    digest = sha(pack_path.read_bytes())
    assert digest == EXPECTED_SHA256, 'The candidate archive changed. Audit the new hash before updating this test.'
    with ZipFile(helpers.EXTRA) as archive:
        transformer = archive.read('me/flashyreese/mods/sodiumextra/client/fog/FogShaderTransformer.class')
        strings = helpers.constant_strings(transformer)
    phases = [
        {}, {'OIT_DEPTH_BOUNDS': '1', 'OIT_ALPHA_ONLY': '1'},
        {'OIT_TRANSMITTANCE': '1', 'OIT_ALPHA_ONLY': '1'},
        {'OIT_ACCUMULATE': '1'}, {'OIT_ACCUMULATE': '1', 'OIT_ADDITIVE': '1'},
    ]
    rows = []
    with ZipFile(validator.DEFAULT_CLIENT) as client, ZipFile(pack_path) as pack:
        metadata = json.loads(pack.read('pack.mcmeta'))
        assert metadata['sodium']['ignored_shaders'] == ['terrain.vsh', 'terrain.fsh']
        audit = source_audit(pack, camera)
        transformed = {
            helpers.STEM + suffix: helpers.extra_transform(pack.read(helpers.STEM + suffix).decode(), strings).encode()
            for suffix in ['.vsh', '.fsh']
        }
        assert all(data != pack.read(name) for name, data in transformed.items()), 'Expected actual Sodium Extra injection'
        for mode in ['Sodium', 'Sodium + Sodium Extra']:
            compiler = validator.Compiler(helpers.Overlay(pack, {} if mode == 'Sodium' else transformed), client)
            try:
                for phase in phases:
                    for zero_to_one in [False, True]:
                        defines = {'USE_VERTEX_COMPRESSION': '1', 'USE_FOG': '1', **phase}
                        if phase:
                            defines.update(OIT='1', OIT_COEFF_COUNT='8', OIT_WAVELET_RANK='2', OIT_COEFF_ATTACHMENT_COUNT='2')
                        if zero_to_one:
                            defines['RENDERPEARL_DEPTH_IS_ZERO_TO_ONE'] = '1'
                        vertex = compiler.compile(helpers.STEM + '.vsh', defines)
                        fragment = compiler.compile(helpers.STEM + '.fsh', defines)
                        validator.stage_pair(vertex, fragment)
                        assert not vertex['warnings'] and not fragment['warnings']
                        assert vertex['interface']['outputs']['6']['name'] == 'spSkyRay'
                        if mode == 'Sodium + Sodium Extra':
                            assert vertex['interface']['outputs']['4']['name'] == 'v_PlanarDistance'
                            assert vertex['interface']['outputs']['5']['name'] == 'v_SodiumExtraCylindricalDistance'
                        rows.append({'mode': mode, 'defines': defines, 'warnings': 0,
                                     'vertexSpirvBytes': vertex['spirvBytes'], 'fragmentSpirvBytes': fragment['spirvBytes']})
            finally:
                compiler.close()
    report = {
        'pack': pack_path.name, 'packSHA256': digest,
        'installedSodiumExtra': helpers.EXTRA.name,
        'installedSodiumExtraSHA256': sha(helpers.EXTRA.read_bytes()),
        'transformerClassSHA256': sha(transformer),
        'transformSource': 'Exact UTF8 constants and concat recipe from installed FogShaderTransformer.class, using existing verified javap control flow',
        'injectedSources': {name: sha(data) for name, data in transformed.items()},
        'sodiumMetadataAccepted': True, 'shaderStagesCompiled': len(rows) * 2,
        'stagePairsChecked': len(rows), 'warnings': 0,
        'cameraSourceAudit': audit, 'variants': rows,
        'liveMinecraftTest': False,
        'limits': 'ShaderC compilation, reflected interfaces, and exact source audit. No runtime renderer or affected-player crash verification.',
    }
    (HERE / 'sodium-compat-check-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ['variants', 'cameraSourceAudit']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=DEFAULT_PACK)
    run(parser.parse_args().pack)
