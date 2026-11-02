"""Keep sky rays aligned with the complete world projection and reduce markers.

The existing 11-word binary camera transport and native control protocol stay
the same size. Only the legacy frequency marker carries camera metadata. All
other control particles rasterize their own one-pixel control cell.
"""
from __future__ import annotations


PARTICLE = 'assets/minecraft/shaders/core/particle.'
READER = 'assets/shader_selector/shaders/include/data_reader.glsl'
DATA = 'assets/shader_selector/shaders/post/data.fsh'
POST = 'assets/shader_selector/shaders/post/shader.fsh'


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError('Expected exactly one camera patch point: ' + old)
    return source.replace(old, new, 1)


CLIP_MATRIX = '''mat3 spSkyClipMatrix(mat4 projection) {
    // Rows x, y and w of the complete projection. Bobbing, hurt rotation and
    // other affine camera effects may be part of this matrix, not view alone.
    return mat3(
        vec3(projection[0][0], projection[0][1], projection[0][3]),
        vec3(projection[1][0], projection[1][1], projection[1][3]),
        vec3(projection[2][0], projection[2][1], projection[2][3]));
}
'''


WORLD_RAY = CLIP_MATRIX + '''
vec3 spSkyWorldRay(vec3 position, mat4 projection, mat4 view) {
    vec3 offset = vec3(projection[3][0], projection[3][1], projection[3][3]);
    // Ordinary projections have no shifted eye. Avoid matrix inverses in that
    // common case. An affine projection translation moves the virtual eye.
    if (all(equal(offset, vec3(0.0)))) return position;
    mat3 clip = spSkyClipMatrix(projection);
    vec3 eye = -inverse(clip) * offset;
    return position - inverse(mat3(view)) * eye;
}
'''


CAMERA_CARRIER = '''    if (isMarker == 1) {
        bool carrier = iColor.r == MARKER_RED && iColor.g == 253;
        vec2 pixel;
        if (carrier) {
            // Send current-frame rays only once per marker set. Map NDC x/y/1
            // directly to world direction, including projection-side bobbing.
            mat3 clip = spSkyClipMatrix(ProjMat);
            mat3 map = inverse(mat3(ModelViewMat)) * inverse(clip);
            vec3 maximum = max(max(abs(map[0]), abs(map[1])), abs(map[2]));
            float scale = max(max(maximum.x, maximum.y), maximum.z);
            spCameraRotation = !isnan(scale) && !isinf(scale) && scale > 0.0
                ? map / scale : mat3(0.0);
            spCameraProjection = vec2(abs(ProjMat[0][0]), abs(ProjMat[1][1]));
            pixel = corners[gl_VertexIndex % 4] * vec2(40.0, 8.0);
        } else {
            // Every non-carrier covers only its control pixel. Previously all
            // seven particles covered 104 by 8 pixels in every OIT phase.
            pixel = vec2(spMarkerPixel) + corners[gl_VertexIndex % 4];
        }
        gl_Position = vec4(-1.0 + pixel * (2.0 / ScreenSize), 1.0, 1.0);
        sphericalVertexDistance = 0.0;
        cylindricalVertexDistance = 0.0;
        texCoord0 = vec2(0.0);
        vertexColor = vec4(0.0);
        return;
    }
'''


def make_camera(base: dict[str, bytes]) -> dict[str, bytes]:
    """Return the nine camera/transport resources over the merged cold pack."""
    result: dict[str, bytes] = {}
    vertex = base[PARTICLE + 'vsh'].decode('utf-8')
    vertex = replace_once(vertex, 'void main() {', CLIP_MATRIX + '\nvoid main() {')
    start = vertex.index('    if (isMarker == 1) {')
    end = vertex.index('    // Vanilla code', start)
    vertex = vertex[:start] + CAMERA_CARRIER + vertex[end:]
    result[PARTICLE + 'vsh'] = vertex.encode()

    fragment = base[PARTICLE + 'fsh'].decode('utf-8')
    fragment = replace_once(fragment,
        'bool metadata = pixel.y >= 0 && pixel.y < 8 && pixel.x >= 8 && pixel.x <= 30;',
        'bool metadata = iColor.r == MARKER_RED && iColor.g == 253\n'
        '            && pixel.y >= 0 && pixel.y < 8 && pixel.x >= 8 && pixel.x <= 30;')
    # The fragment has no marker settings include in the original transport.
    # Use its existing constant wire identity without introducing an include.
    fragment = fragment.replace('iColor.r == MARKER_RED && iColor.g == 253',
                                'iColor.r == 254 && iColor.g == 253')
    result[PARTICLE + 'fsh'] = fragment.encode()

    reader = base[READER].decode('utf-8')
    reader = replace_once(reader, 'ivec4(83, 80, 51, 2)', 'ivec4(83, 80, 52, 3)')
    old_validation = '''    mat3 rotation = spWorldFromView();
    for (int column = 0; column < 3; ++column)
        if (abs(dot(rotation[column], rotation[column]) - 1.0) > 0.05) return false;
    return abs(determinant(rotation) - 1.0) < 0.05;'''
    new_validation = '''    mat3 map = spWorldFromView();
    for (int column = 0; column < 3; ++column) {
        if (any(isnan(map[column])) || any(isinf(map[column]))
            || any(greaterThan(abs(map[column]), vec3(1.0)))) return false;
    }
    return abs(determinant(map)) > 0.000001;'''
    reader = replace_once(reader, old_validation, new_validation)
    result[READER] = reader.encode()
    data = base[DATA].decode('utf-8')
    data = replace_once(data, 'vec4(83.0, 80.0, 51.0, 2.0)', 'vec4(83.0, 80.0, 52.0, 3.0)')
    result[DATA] = data.encode()

    post = base[POST].decode('utf-8')
    post = replace_once(post,
        'spCameraToWorld * vec3((uv * 2.0 - 1.0) / spProjection, -1.0)',
        'spCameraToWorld * vec3(uv * 2.0 - 1.0, 1.0)')
    result[POST] = post.encode()

    geometry = [
        ('assets/minecraft/shaders/core/terrain.vsh', 'dfskyRay = pos;', 'pos', 'ProjMat', 'ModelViewMat'),
        ('assets/minecraft/shaders/core/block.vsh', 'dfskyRay = pos;', 'pos', 'ProjMat', 'ModelViewMat'),
        ('assets/minecraft/shaders/core/item.vsh', 'dfskyRay = Position;', 'Position', 'ProjMat', 'ModelViewMat'),
        ('assets/sodium/shaders/blocks/block_layer_opaque.vsh', 'spSkyRay = position;', 'position', 'u_ProjectionMatrix', 'u_ModelViewMatrix'),
    ]
    for name, assignment, position, projection, view in geometry:
        source = base[name].decode('utf-8')
        source = replace_once(source, 'void main() {', WORLD_RAY + '\nvoid main() {')
        left = assignment.split('=')[0].strip()
        source = replace_once(source, assignment,
            f'{left} = spSkyWorldRay({position}, {projection}, {view});')
        result[name] = source.encode()
    return result
