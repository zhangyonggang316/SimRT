import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import zipfile
from pyxcp_host.demo import load_demo


class ManualDemoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='manual demo ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        self.elf = self.payload / 'model.elf'
        self.a2l = self.payload / 'model.a2l'
        header = bytearray(20)
        header[:6] = b'\x7fELF\x02\x01'
        header[16] = 2
        header[18] = 62
        self.elf.write_bytes(header)
        self.a2l.write_text('A2L test data', encoding='utf-8')
        self.manifest = {'ELFFile': self.elf.name, 'A2LFile': self.a2l.name,
                         'ELFSHA256': hashlib.sha256(header).hexdigest(),
                         'A2LSHA256': hashlib.sha256(self.a2l.read_bytes()).hexdigest(),
                         'XCPTransport': 'UDP', 'XCPPort': 17725}
        self.config = {'version': 1, 'host': 'test-host', 'username': 'test-user',
                       'manifest': 'payload/manifest.json'}
        self.save()

    def save(self):
        (self.payload / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (self.root / 'demo.json').write_text(json.dumps(self.config), encoding='utf-8')

    def test_loads_relocatable_paths_and_unique_safe_remote_directory(self):
        first = load_demo(self.root)
        self.assertEqual(first.a2l_path, self.a2l.resolve())
        self.assertEqual(first.host, 'test-host')
        self.assertTrue(first.remote_dir.startswith('MATLAB_ws/manual_demo_'))
        self.assertNotEqual(first.remote_dir, load_demo(self.root).remote_dir)

    def test_changed_a2l_is_rejected(self):
        self.a2l.write_text('different addresses')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            load_demo(self.root)

    def test_changed_elf_is_rejected(self):
        self.elf.write_bytes(self.elf.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            load_demo(self.root)

    def test_pie_elf_is_rejected_even_if_hash_matches(self):
        header = bytearray(self.elf.read_bytes())
        header[16] = 3
        self.elf.write_bytes(header)
        self.manifest['ELFSHA256'] = hashlib.sha256(header).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, 'fixed-address'):
            load_demo(self.root)

    def test_manifest_cannot_escape_demo_directory(self):
        self.config['manifest'] = '../manifest.json'
        self.save()
        with self.assertRaisesRegex(ValueError, 'inside'):
            load_demo(self.root)

    def test_artifact_name_cannot_escape_payload(self):
        self.manifest['A2LFile'] = '../model.a2l'
        self.save()
        with self.assertRaisesRegex(ValueError, 'basenames'):
            load_demo(self.root)

    def test_missing_file_is_rejected(self):
        self.a2l.unlink()
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            load_demo(self.root)

    def test_wrong_transport_is_rejected(self):
        self.manifest['XCPTransport'] = 'CAN'
        self.save()
        with self.assertRaisesRegex(ValueError, 'UDP'):
            load_demo(self.root)

    def test_tcp_and_nondefault_port_are_accepted(self):
        self.manifest.update(XCPTransport='TCP', XCPPort=25555)
        self.save()
        self.assertEqual(load_demo(self.root).a2l_path, self.a2l)

    def archive_payload(self):
        header = bytearray(self.elf.read_bytes().ljust(64, b'\0'))
        header[6] = 1
        header[20] = 1
        self.elf.write_bytes(header)
        self.manifest.update(SchemaVersion=2, ModelName='model',
                             ELFSHA256=hashlib.sha256(self.elf.read_bytes()).hexdigest())
        (self.payload / 'manifest.json').unlink()
        manifest = self.payload / 'model.xcp-manifest.json'
        manifest.write_text(json.dumps(self.manifest), encoding='utf-8')
        archive_path = self.payload.with_suffix('.zip')
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for item in self.payload.iterdir():
                archive.write(item, 'payload/' + item.name)
        shutil.rmtree(self.payload)
        self.config['manifest'] = 'payload/model.xcp-manifest.json'
        (self.root / 'demo.json').write_text(json.dumps(self.config), encoding='utf-8')
        return archive_path

    def test_legacy_preset_resolves_zip_when_expanded_folder_is_absent(self):
        archive = self.archive_payload()
        selected = load_demo(self.root)
        self.assertEqual(selected.payload_archive, archive)
        self.assertIsNone(selected.a2l_path)
        self.assertIsNone(selected.payload_dir)
        self.assertEqual(selected.elf_name, 'model.elf')
        self.assertFalse(self.payload.exists())

    def test_explicit_archive_preset_needs_no_manifest_path(self):
        archive = self.archive_payload()
        self.config.pop('manifest')
        self.config['archive'] = 'payload.zip'
        (self.root / 'demo.json').write_text(json.dumps(self.config), encoding='utf-8')
        selected = load_demo(self.root)
        self.assertEqual(selected.payload_archive, archive)

    def test_missing_manifest_cannot_select_an_unrelated_archive_member(self):
        self.archive_payload()
        self.config['manifest'] = 'payload/other.xcp-manifest.json'
        (self.root / 'demo.json').write_text(json.dumps(self.config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'selected manifest'):
            load_demo(self.root)

    def test_archive_cannot_escape_demo_directory(self):
        self.config['archive'] = '../payload.zip'
        self.save()
        with self.assertRaisesRegex(ValueError, 'inside'):
            load_demo(self.root)

if __name__ == '__main__':
    unittest.main()
