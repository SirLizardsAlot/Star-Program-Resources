"""Compile a resource pack using the 26.3 ShaderC frontend without starting a game.

The official GlslCompiler targets Vulkan 1.2 SPIR-V on BOTH render backends.
OpenGL receives translated SPIR-V later. This validator uses that same frontend,
resolves actual resource-pack includes, checks compiled stage locations, and
compares core vertex inputs with the official client. GPU rendering is not tested.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
DEFAULT_CLIENT = HERE / 'reference/minecraft-client.jar'
DEFAULT_DLL = HERE.parents[2] / 'plot-locations/.local/shader-validation/natives/shaderc.dll'


class IncludeResult(ct.Structure):
    _fields_ = [('source_name', ct.c_char_p), ('source_name_length', ct.c_size_t),
                ('content', ct.c_char_p), ('content_length', ct.c_size_t),
                ('user_data', ct.c_void_p)]


Resolve = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_char_p, ct.c_int, ct.c_char_p, ct.c_size_t)
Release = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p)


class Compiler:
    def __init__(self, pack, client, dll=DEFAULT_DLL):
        self.pack, self.client = pack, client
        self.dll = ct.CDLL(str(Path(dll).resolve()))
        signatures = {
            'compiler_initialize': (ct.c_void_p, []),
            'compiler_release': (None, [ct.c_void_p]),
            'compile_options_initialize': (ct.c_void_p, []),
            'compile_options_release': (None, [ct.c_void_p]),
            'compile_options_set_target_env': (None, [ct.c_void_p, ct.c_int, ct.c_uint]),
            'compile_options_set_auto_bind_uniforms': (None, [ct.c_void_p, ct.c_bool]),
            'compile_options_set_preserve_bindings': (None, [ct.c_void_p, ct.c_bool]),
            'compile_options_set_generate_debug_info': (None, [ct.c_void_p]),
            'compile_options_add_macro_definition': (None, [ct.c_void_p, ct.c_char_p, ct.c_size_t, ct.c_char_p, ct.c_size_t]),
            'compile_options_set_include_callbacks': (None, [ct.c_void_p, Resolve, Release, ct.c_void_p]),
            'compile_into_spv': (ct.c_void_p, [ct.c_void_p, ct.c_char_p, ct.c_size_t, ct.c_int, ct.c_char_p, ct.c_char_p, ct.c_void_p]),
            'result_get_compilation_status': (ct.c_int, [ct.c_void_p]),
            'result_get_error_message': (ct.c_char_p, [ct.c_void_p]),
            'result_get_length': (ct.c_size_t, [ct.c_void_p]),
            'result_get_bytes': (ct.c_void_p, [ct.c_void_p]),
            'result_get_num_warnings': (ct.c_size_t, [ct.c_void_p]),
            'result_release': (None, [ct.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.dll, 'shaderc_' + name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)
        self.compiler = self.compiler_initialize()
        if not self.compiler:
            raise RuntimeError('ShaderC compiler initialization failed')

    def close(self):
        self.compiler_release(self.compiler)

    def read(self, name, vanilla=False):
        if not vanilla and name in self.pack.namelist():
            return self.pack.read(name)
        return self.client.read(name)

    def compile(self, name, defines, vanilla=False):
        source = self.read(name, vanilla)
        if b'#moj_import' in source:
            raise ValueError(name + ': obsolete #moj_import in 26.3 shader')
        keep_alive, includes, include_errors = [], set(), []

        @Resolve
        def resolve(_user, requested, _kind, _requester, depth):
            identifier = requested.decode('utf-8')
            try:
                if depth > 128 or not re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', identifier):
                    raise ValueError('Malformed or recursive shader include: ' + identifier)
                namespace, local = identifier.split(':', 1)
                path = f'assets/{namespace}/shaders/include/{local}'
                data = self.read(path, vanilla)
                includes.add(path)
                label = path.encode()
            except Exception as error:
                include_errors.append(str(error))
                label, data = b'', str(error).encode()
            result = IncludeResult(label, len(label), data, len(data), None)
            keep_alive.extend([label, data, result])
            return ct.addressof(result)

        @Release
        def release(_user, _result):
            pass

        options, result = self.compile_options_initialize(), None
        try:
            # Bytecode evidence: official GlslCompiler.createBaseShaderOptions.
            self.compile_options_set_target_env(options, 0, (1 << 22) | (2 << 12))
            self.compile_options_set_auto_bind_uniforms(options, True)
            self.compile_options_set_preserve_bindings(options, False)
            self.compile_options_set_generate_debug_info(options)
            self.compile_options_set_include_callbacks(options, resolve, release, None)
            for key, value in defines.items():
                key, value = key.encode(), str(value).encode()
                self.compile_options_add_macro_definition(options, key, len(key), value, len(value))
            result = self.compile_into_spv(self.compiler, source, len(source),
                                           0 if name.endswith('.vsh') else 1,
                                           name.encode(), b'main', options)
            if not result:
                raise RuntimeError('ShaderC returned no compilation result: ' + name)
            status = self.result_get_compilation_status(result)
            diagnostics = self.result_get_error_message(result).decode(errors='replace')
            if status or include_errors:
                raise ValueError(f'{name} {defines}:\n{diagnostics}' + '\n'.join(include_errors))
            spirv = ct.string_at(self.result_get_bytes(result), self.result_get_length(result))
            return {'file': name, 'defines': defines, 'spirvBytes': len(spirv),
                    'warnings': self.result_get_num_warnings(result),
                    'diagnostics': diagnostics, 'includes': sorted(includes),
                    'interface': interface(spirv)}
        finally:
            if result:
                self.result_release(result)
            self.compile_options_release(options)


def interface(spirv):
    """Read actual compiled SPIR-V input/output locations and structural types."""
    words = struct.unpack('<' + 'I' * (len(spirv) // 4), spirv)
    if words[0] != 0x07230203:
        raise ValueError('ShaderC did not produce SPIR-V')
    names, types, variables, locations, constants = {}, {}, {}, {}, {}
    offset = 5
    while offset < len(words):
        count, opcode = words[offset] >> 16, words[offset] & 0xffff
        values = words[offset + 1:offset + count]
        if not count:
            raise ValueError('Invalid SPIR-V instruction')
        if opcode == 5:  # OpName
            names[values[0]] = struct.pack('<' + 'I' * (len(values) - 1), *values[1:]).split(b'\0')[0].decode()
        elif opcode == 71 and values[1] == 30:  # OpDecorate Location
            locations[values[0]] = values[2]
        elif opcode == 59:  # OpVariable
            variables[values[1]] = (values[0], values[2])
        elif 19 <= opcode <= 33:
            types[values[0]] = (opcode, values[1:])
        elif opcode == 43:
            constants[values[1]] = values[2]
        offset += count

    def describe(type_id):
        opcode, values = types[type_id]
        if opcode == 32:
            return describe(values[1])
        if opcode == 21:
            return ('int' if values[1] else 'uint') + str(values[0])
        if opcode == 22:
            return 'float' + str(values[0])
        if opcode in [23, 24]:
            return ('vector' if opcode == 23 else 'matrix') + str(values[1]) + '<' + describe(values[0]) + '>'
        if opcode in [28, 29]:
            return 'array<' + describe(values[0]) + ',' + str(constants.get(values[1], '?') if opcode == 28 else '*') + '>'
        return str((opcode, values))

    result = {'inputs': {}, 'outputs': {}}
    for var_id, location in locations.items():
        if var_id in variables:
            type_id, storage = variables[var_id]
            if storage in [1, 3]:
                result['inputs' if storage == 1 else 'outputs'][str(location)] = {
                    'name': names.get(var_id, ''), 'type': describe(type_id)}
    return result


def shader_path(identifier, extension):
    namespace, path = identifier.split(':', 1) if ':' in identifier else ('minecraft', identifier)
    return f'assets/{namespace}/shaders/{path}{extension}'


def stage_pair(vertex, fragment):
    outputs = vertex['interface']['outputs']
    for location, entry in fragment['interface']['inputs'].items():
        if location not in outputs or outputs[location]['type'] != entry['type']:
            raise ValueError(f"Stage interface mismatch: {vertex['file']} -> {fragment['file']} at location {location}: "
                             f"{outputs.get(location)} -> {entry}")


def validate(pack_path, client_path=DEFAULT_CLIENT, dll_path=DEFAULT_DLL):
    pack_path, client_path = Path(pack_path), Path(client_path)
    with ZipFile(pack_path) as pack, ZipFile(client_path) as client:
        version = json.loads(client.read('version.json'))
        if version['id'] != '26.3' or version['pack_version']['resource_major'] != 97:
            raise ValueError('Expected the official Minecraft 26.3 client')
        compiler = Compiler(pack, client, dll_path)
        stages, pairs, attributes = {}, [], []
        try:
            def compile_one(name, defines=None, vanilla=False):
                defines = defines or {}
                key = (name, tuple(sorted(defines.items())), vanilla)
                if key not in stages:
                    stages[key] = compiler.compile(name, defines, vanilla)
                return stages[key]

            for name in pack.namelist():
                if name.endswith(('.vsh', '.fsh')):
                    compile_one(name)
            # Core stages may be paired with an inherited vanilla counterpart.
            core = sorted({name.rsplit('.', 1)[0] for name in pack.namelist()
                           if name.startswith('assets/minecraft/shaders/core/') and name.endswith(('.vsh', '.fsh'))})
            for stem in core:
                variants = [{}]
                if stem.endswith('/particle'):
                    variants += [dict(OIT='1', OIT_COEFF_COUNT='8', OIT_WAVELET_RANK='2',
                                      OIT_COEFF_ATTACHMENT_COUNT='2', **variant) for variant in [
                        {'OIT_DEPTH_BOUNDS': '1', 'OIT_ALPHA_ONLY': '1'},
                        {'OIT_TRANSMITTANCE': '1', 'OIT_ALPHA_ONLY': '1'},
                        {'OIT_ACCUMULATE': '1'},
                        {'OIT_ACCUMULATE': '1', 'OIT_ADDITIVE': '1'}]]
                for variant in variants:
                    for depth in [False, True]:
                        defines = dict(variant)
                        if depth:
                            defines['RENDERPEARL_DEPTH_IS_ZERO_TO_ONE'] = '1'
                        vertex, fragment = compile_one(stem + '.vsh', defines), compile_one(stem + '.fsh', defines)
                        stage_pair(vertex, fragment)
                        pairs.append({'vertex': vertex['file'], 'fragment': fragment['file'], 'defines': defines})
                        native = compile_one(stem + '.vsh', defines, vanilla=True)
                        for location, entry in vertex['interface']['inputs'].items():
                            if native['interface']['inputs'].get(location) != entry:
                                raise ValueError(f'Core vertex attribute differs from 26.3: {stem} {location}: {entry}')
                        attributes.append({'file': vertex['file'], 'defines': defines})

            for name in pack.namelist():
                if '/post_effect/' not in name or not name.endswith('.json'):
                    continue
                effect = json.loads(pack.read(name))
                for effect_pass in effect.get('passes', []):
                    vertex = compile_one(shader_path(effect_pass['vertex_shader'], '.vsh'))
                    fragment = compile_one(shader_path(effect_pass['fragment_shader'], '.fsh'))
                    stage_pair(vertex, fragment)
                    pairs.append({'effect': name, 'vertex': vertex['file'], 'fragment': fragment['file'], 'defines': {}})
        finally:
            compiler.close()
    rows = list(stages.values())
    return {'compiler': 'ShaderC 3.4.1 native DLL, official 26.3 Vulkan 1.2 SPIR-V frontend',
            'packSHA256': hashlib.sha256(pack_path.read_bytes()).hexdigest(),
            'stagesCompiled': len(rows), 'stagePairsChecked': len(pairs),
            'coreAttributeVariantsChecked': len(attributes),
            'stages': rows, 'pairs': pairs,
            'checks': {'shaderCompilation': True, 'stageInterfaceLocations': True,
                       'coreVertexAttributeContract': True, 'bothDepthConventions': True,
                       'particleOitVariants': True},
            'limitations': ['GPU driver, backend SPIR-V translation, runtime bindings and rendered appearance are not checked.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--client', type=Path, default=DEFAULT_CLIENT)
    parser.add_argument('--dll', type=Path, default=DEFAULT_DLL)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = validate(args.pack, args.client, args.dll)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ['stages', 'pairs']}, indent=2))
