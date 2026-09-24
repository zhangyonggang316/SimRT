"""Payload identity and interrupted-deployment checks without an SSH target."""

import ast
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from pyxcp_host.services.model_payload import file_hash, validate_payload
from pyxcp_host.services.ssh_deployment import SSHDeployment, _REMOTE_HELPER


def make_payload(root):
    root.mkdir()
    elf = bytearray(64)
    elf[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', elf, 16, 2, 62, 1)
    (root / 'model.elf').write_bytes(elf)
    (root / 'model.a2l').write_text('ASAP2_VERSION 1 71\n')
    manifest = dict(SchemaVersion=2, ModelName='model', XCPTransport='UDP', XCPPort=17725,
                    ELFFile='model.elf', ELFSHA256=file_hash(root / 'model.elf'),
                    A2LFile='model.a2l', A2LSHA256=file_hash(root / 'model.a2l'))
    (root / 'model.xcp-manifest.json').write_text(json.dumps(manifest))
    return manifest


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'payload'
        self.manifest = make_payload(self.root)

    def save_manifest(self):
        (self.root / 'model.xcp-manifest.json').write_text(json.dumps(self.manifest))

    def test_matching_payload_and_dependency_hashes(self):
        (self.root / 'lib').mkdir()
        library = self.root / 'lib' / 'custom.so'
        library.write_bytes(b'runtime')
        self.manifest['RuntimeFiles'] = {'lib/custom.so': file_hash(library)}
        self.save_manifest()
        result = validate_payload(self.root)
        self.assertEqual(len(result['files']), 4)
        self.assertEqual(result['elf_name'], 'model.elf')
        library.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            validate_payload(self.root)

    def test_a2l_from_another_build_rejected(self):
        (self.root / 'model.a2l').write_text('another build')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            validate_payload(self.root)

    def test_unlisted_source_is_not_deployable(self):
        (self.root / 'build_model.py').write_text('raise RuntimeError()')
        with self.assertRaisesRegex(ValueError, 'not covered'):
            validate_payload(self.root)

    def test_pie_and_wrong_architecture_rejected_even_with_matching_hash(self):
        for elf_type, machine in ((3, 62), (2, 183)):
            with self.subTest(elf_type=elf_type, machine=machine):
                path = self.root / 'model.elf'
                header = bytearray(path.read_bytes())
                struct.pack_into('<HH', header, 16, elf_type, machine)
                path.write_bytes(header)
                self.manifest['ELFSHA256'] = file_hash(path)
                self.save_manifest()
                with self.assertRaisesRegex(ValueError, 'ELF64'):
                    validate_payload(self.root)

    def test_traversal_and_absolute_paths_rejected(self):
        for name in ('../escape', '/escape', 'C:/escape', 'lib/../escape', '.pyxcp-payload.json'):
            self.manifest['RuntimeFiles'] = {name: '0' * 64}
            self.save_manifest()
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_payload(self.root)

    def service(self):
        service = SSHDeployment()
        service._begin = Mock()
        service._upload = Mock(return_value=3)
        service._request = Mock(side_effect=[{'remote_directory': '/home/test/model'},
                                             {'remote_directory': '/home/test/model', 'verified': True}])
        return service

    def test_upload_verifies_every_file_without_build_or_start(self):
        service = self.service()
        result = service.deploy_payload(self.root, 'model')
        self.assertEqual(result['elf_path'], '/home/test/model/model.elf')
        self.assertEqual(result['file_count'], 3)
        self.assertEqual([call.args[0] for call in service._request.call_args_list],
                         ['payload_begin', 'payload_verify'])
        self.assertEqual(service._request.call_args.kwargs['files'], validate_payload(self.root)['files'])

    def test_invalid_payload_never_connects_or_marks_remote(self):
        (self.root / 'model.elf').write_bytes(b'broken')
        service = self.service()
        with self.assertRaises(ValueError):
            service.deploy_payload(self.root, 'model')
        service._request.assert_not_called()
        service._upload.assert_not_called()

    def test_upload_failure_leaves_pending_without_verification(self):
        service = self.service()
        service._upload.side_effect = ConnectionError('interrupted')
        with self.assertRaises(ConnectionError):
            service.deploy_payload(self.root, 'model')
        service._request.assert_called_once_with('payload_begin', path='model')

    def test_local_change_during_upload_is_not_published(self):
        service = self.service()
        def mutate(*_):
            (self.root / 'model.a2l').write_text('changed while uploading')
        service._upload.side_effect = mutate
        with self.assertRaises(ValueError):
            service.deploy_payload(self.root, 'model')
        self.assertEqual(service._request.call_count, 1)

    def test_remote_must_explicitly_confirm_verification(self):
        service = self.service()
        service._request.side_effect = [{'remote_directory': '/home/test/model'}, {'verified': False}]
        with self.assertRaisesRegex(RuntimeError, 'confirm'):
            service.deploy_payload(self.root, 'model')

    def remote_functions(self):
        module = ast.parse(_REMOTE_HELPER)
        functions = ast.Module(body=[node for node in module.body if isinstance(node, ast.FunctionDef)], type_ignores=[])
        namespace = dict(Path=Path, home=self.root.parent.resolve(), hashlib=hashlib, json=json)
        exec(compile(functions, '<remote payload functions>', 'exec'), namespace)
        return namespace

    def test_pending_upload_blocks_start_after_reconnect(self):
        functions = self.remote_functions()
        (self.root / '.pyxcp-payload.pending').write_text('pending')
        with self.assertRaisesRegex(RuntimeError, 'did not complete'):
            functions['check_deployed_payload'](self.root / 'model.elf')

    def test_start_rechecks_remote_artifacts_against_persistent_receipt(self):
        payload = validate_payload(self.root)
        receipt = dict(elf_name='model.elf', files=payload['files'])
        (self.root / '.pyxcp-payload.json').write_text(json.dumps(receipt))
        check = self.remote_functions()['check_deployed_payload']
        check(self.root / 'model.elf')
        (self.root / 'model.a2l').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError, 'SHA256'):
            check(self.root / 'model.elf')


if __name__ == '__main__':
    unittest.main()
