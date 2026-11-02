"""Build the Sky Block and visual recoil pack over the exact current pack pin.

This command is local. It does not publish, change the pin, or contact Minecraft.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import zlib
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GAME = ROOT.parent
CLIENT = ROOT / 'mc26.3/reference/minecraft-client.jar'
PACK = HERE / 'sp_sky-recoil-panels-mc26.3.zip'
BASE_SHA = 'f9f36c225616efa4005ac39e460b3a8c30656654bf9733993c67fba177dbc22d'
BASE_NAME = 'sp_main-menu-font-mc26.3.zip'
LIMIT = 41943040


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def png():
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    pixels = (b'\0' + bytes([17, 239, 173, 255]) * 16) * 16
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels, 9)) + chunk(b'IEND', b''))


def sky_geometry(client):
    patches = {}
    for kind, location in [('terrain', 5), ('block', 4), ('item', 7)]:
        vertex_name = f'assets/minecraft/shaders/core/{kind}.vsh'
        fragment_name = f'assets/minecraft/shaders/core/{kind}.fsh'
        vertex, fragment = client[vertex_name].decode(), client[fragment_name].decode()
        vertex = vertex.replace('void main() {', f'layout(location = {location}) out vec3 dfskyRay;\n\nvoid main() {{', 1)
        if kind == 'item':
            vertex = vertex.replace('    gl_Position =', '    dfskyRay = Position;\n    gl_Position =', 1)
        else:
            vertex = vertex.replace('    gl_Position =', '    dfskyRay = pos;\n    gl_Position =', 1)
        fragment = fragment.replace('uniform sampler2D Sampler0;',
            f'#include <dfsky:sky.glsl>\nlayout(location = {location}) in vec3 dfskyRay;\nuniform sampler2D Sampler0;', 1)
        # Fully opaque marker texels keep this block in the solid render layer.
        # Only the framebuffer alpha is zero, carrying sky visibility through
        # ordinary premultiplied glass composition to the final sky correction.
        alpha = '1.0' if kind == 'item' else '0.0'
        fragment = fragment.replace('void main() {', '''void main() {
    float ignoredClock;
    if (dfsky_marker(Sampler0, texCoord0, ignoredClock)) {
        #ifdef OIT_ALPHA_ONLY
        executeAlphaOnlyPhase(gl_FragCoord.z, 1.0);
        #else
        fragColor = vec4(dfsky_render(dfskyRay, 0.0), SKY_ALPHA);
        #endif
        return;
    }'''.replace('SKY_ALPHA', alpha), 1)
        patches[vertex_name], patches[fragment_name] = vertex.encode(), fragment.encode()
    faces = {face: {'uv': [0, 0, 16, 16], 'texture': '#sky', 'cullface': face}
             for face in ['north', 'south', 'east', 'west', 'up', 'down']}
    patches['assets/dfsky/models/block/sky_block.json'] = encoded({
        'parent': 'minecraft:block/block', 'ambientocclusion': False,
        'textures': {'particle': 'dfsky:block/sky_marker', 'sky': 'dfsky:block/sky_marker'},
        'elements': [{'from': [0, 0, 0], 'to': [16, 16, 16], 'shade': False, 'faces': faces}],
    })
    patches['assets/minecraft/models/block/red_glazed_terracotta.json'] = encoded({'parent': 'dfsky:block/sky_block'})
    patches['assets/dfsky/textures/block/sky_marker.png'] = png()
    return patches


def post_shaders(base):
    vertex_name = 'assets/shader_selector/shaders/post/shader.vsh'
    fragment_name = 'assets/shader_selector/shaders/post/shader.fsh'
    vertex, fragment = base[vertex_name].decode(), base[fragment_name].decode()
    vertex = vertex.replace('uniform sampler2D BlurSampler;', '')
    vertex = vertex.replace('#include <minecraft:globals.glsl>',
        '#include <minecraft:globals.glsl>\n#include <star_program:recoil.glsl>')
    vertex = vertex.replace('texCoord', 'baseTexCoord')
    declarations = '''
float spAngleDegrees(float controlValue) {
    float value = controlValue * 255.0 - 128.0;
    return value * (value < 0.0 ? 8.0 / 128.0 : 8.0 / 127.0);
}
layout(location = 1) flat out vec2 spProjection;
layout(location = 2) flat out mat3 spCameraToWorld;
layout(location = 5) flat out vec2 spAngles;
layout(location = 6) flat out float spCrop;
layout(location = 7) flat out float spTime;
layout(location = 8) flat out int spHasCamera;
'''
    vertex = vertex.replace('void main(){', declarations + '''
void main(){
    spHasCamera = int(spCameraValid());
    spProjection = spProjectionScale();
    spCameraToWorld = spWorldFromView();
    spAngles = radians(vec2(spAngleDegrees(readChannel(RECOIL_PITCH)), spAngleDegrees(readChannel(RECOIL_YAW))));
    if (spHasCamera == 0) spAngles = vec2(0.0);
    spCrop = spRecoilCrop(spProjection, spAngles.x, spAngles.y);
    spTime = spSkyTime();''', 1)
    fragment = fragment.replace('uniform sampler2D MainSampler;',
        'uniform sampler2D MainSampler;\nuniform sampler2D MainDepthSampler;', 1)
    fragment = fragment.replace('#include <minecraft:globals.glsl>', '''#include <minecraft:globals.glsl>
#include <star_program:recoil.glsl>
#include <dfsky:sky.glsl>''', 1)
    fragment = fragment.replace('layout(location = 0) in vec2 texCoord;', '''layout(location = 0) in vec2 baseTexCoord;
layout(location = 1) flat in vec2 spProjection;
layout(location = 2) flat in mat3 spCameraToWorld;
layout(location = 5) flat in vec2 spAngles;
layout(location = 6) flat in float spCrop;
layout(location = 7) flat in float spTime;
layout(location = 8) flat in int spHasCamera;
vec2 texCoord;''', 1)
    # Apply the sky correction at every source sample, including warped samples.
    fragment = fragment.replace('texture(MainSampler, texCoord)', 'spScene(texCoord)')
    fragment = fragment.replace('texture(MainSampler, pulledTexCoord)', 'spScene(pulledTexCoord)')
    scene = '''
vec4 spScene(vec2 uv) {
    vec4 source = texture(MainSampler, uv);
    float visibility = clamp(1.0 - source.a, 0.0, 1.0);
    // A cleared background has no world depth. Ordinary opaque geometry has
    // alpha one. Ignore byte-sized incidental coverage errors on cutout edges.
    if (spHasCamera != 0 && visibility > 0.02 && texture(MainDepthSampler, uv).r > 0.0) {
        vec3 ray = normalize(spCameraToWorld * vec3((uv * 2.0 - 1.0) / spProjection, -1.0));
        dfsky_setTime(6000.0);
        vec3 baseline = dfsky_render(ray, 0.0);
        dfsky_setTime(spTime);
        float cloudClock = mod(GameTime * 1200.0 * 0.6, 3072.0);
        vec3 replacement = dfsky_render(ray, cloudClock);
        source.rgb = clamp(source.rgb + visibility * (replacement - baseline), 0.0, 1.0);
    }
    return vec4(source.rgb, 1.0);
}
'''
    fragment = fragment.replace('float random(float x)', scene + '\nfloat random(float x)', 1)
    fragment = fragment.replace('void main() {', '''void main() {
    texCoord = spRecoilUV(baseTexCoord, spProjection, spAngles.x, spAngles.y, spCrop);''', 1)
    return {vertex_name: vertex.encode(), fragment_name: fragment.encode()}


def build():
    pin = json.loads((GAME / 'config/resource-pack.json').read_text())
    if pin['sha256'] != BASE_SHA:
        prior = json.loads((HERE / 'build-report.json').read_text())
        saved = json.loads((HERE / 'base-pin.json').read_text())
        require(saved['sha256'] == BASE_SHA and pin.get('skyRecoil', {}).get('version') == 1
                and pin['sha256'] == prior['sha256'], 'Preserve the different current pack pin')
    base_path = ROOT / BASE_NAME
    base_data = base_path.read_bytes()
    require(sha(base_data) == BASE_SHA, 'Pinned base archive changed')
    with ZipFile(BytesIO(base_data)) as archive:
        base = {name: archive.read(name) for name in archive.namelist()}
        metadata = {entry.filename: entry for entry in archive.infolist()}
    with ZipFile(CLIENT) as archive:
        client = {name: archive.read(name) for name in archive.namelist() if name.startswith('assets/minecraft/shaders/')}
    module('sp_sodium', HERE / 'sodium_patch.py').prepare()
    patches = {path.relative_to(HERE / 'overrides').as_posix(): path.read_bytes()
               for path in (HERE / 'overrides').rglob('*') if path.is_file()}
    patches.update(sky_geometry(client))
    patches.update(module('sp_panels', HERE / 'panel_models.py').make_panels())
    patches.update(module('sp_transport', HERE / 'transport.py').make_transport(base))
    patches.update(post_shaders(base))
    language = json.loads(base.get('assets/minecraft/lang/en_us.json', b'{}'))
    language['block.minecraft.red_glazed_terracotta'] = 'Sky Block'
    language['block.minecraft.oak_trapdoor'] = 'Sky Panel'
    patches['assets/minecraft/lang/en_us.json'] = encoded(language)
    post_name = 'assets/minecraft/post_effect/end_of_frame.json'
    post = json.loads(base[post_name])
    post['targets']['data']['height'] = post['targets']['data_swap']['height'] = 14
    effect = next(row for row in post['passes'] if row['fragment_shader'] == 'shader_selector:post/shader')
    effect['inputs'].append({'sampler_name': 'MainDepth', 'target': 'minecraft:main', 'use_depth_buffer': True})
    patches[post_name] = encoded(post)
    for name, content in patches.items():
        path = HERE / 'overrides' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    final = {**base, **patches}
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in final.items():
            info = metadata.get(name)
            if info is None:
                info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    data = output.getvalue()
    require(len(data) <= LIMIT, 'Pack exceeds 40 MiB upload limit')
    candidate = HERE / 'candidate.zip'
    candidate.write_bytes(data)
    validator = module('sp_shader_validator', HERE / 'validate_shaders.py')
    validation = validator.validate(candidate, CLIENT)
    with ZipFile(candidate) as archive:
        require(archive.testzip() is None, 'CRC failure')
        for name in archive.namelist():
            if name.endswith('.json') or name == 'pack.mcmeta':
                json.loads(archive.read(name))
    changed = sorted(name for name in base if base[name] != final[name])
    added = sorted(set(final) - set(base))
    report = {'version': 1, 'basePack': BASE_NAME, 'baseSHA256': BASE_SHA,
              'pack': PACK.name, 'sha256': sha(data), 'sha1': hashlib.sha1(data).hexdigest(),
              'size': len(data), 'sizeLimit': LIMIT, 'changedExistingFiles': changed,
              'addedFiles': added, 'removedFiles': [], 'unchangedEntries': len(base) - len(changed),
              'existingAudioPreserved': all(final[name] == content for name, content in base.items() if name.endswith('.ogg')),
              'skySource': 'Simulation DF plot / DF Sky Window',
              'shaderValidation': validation}
    PACK.write_bytes(data)
    (HERE / 'build-report.json').write_bytes(encoded(report))
    print(json.dumps({**report, 'shaderValidation': {key: value for key, value in validation.items()
        if key not in ['stages', 'pairs', 'postPassBindings']}}, indent=2))


if __name__ == '__main__':
    build()
