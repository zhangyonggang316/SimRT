"""Local receipt/ZIP checks finish before any target connection."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_local_workflow as workflow


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / '20260919_000000_000'
        self.payload.mkdir()
        self.model = 'x280_rt_single'
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', header, 16, 2, 62, 1)
        struct.pack_into('<H', header, 52, 64)
        a2l = b'/begin PROJECT test "fixture" /end PROJECT'
        self.elf_hash = hashlib.sha256(header).hexdigest()
        (self.payload / (self.model + '.elf')).write_bytes(header)
        (self.payload / (self.model + '.a2l')).write_bytes(a2l)
        manifest = dict(SchemaVersion=2, ModelName=self.model, ELFFile=self.model + '.elf', A2LFile=self.model + '.a2l',
                        ELFSHA256=self.elf_hash, A2LSHA256=hashlib.sha256(a2l).hexdigest(),
                        XCPTransport='UDP', XCPPort=17725, RuntimeFiles={})
        (self.payload / (self.model + '.xcp-manifest.json')).write_text(json.dumps(manifest))
        self.archive = self.root / (self.payload.name + '.zip')
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for path in self.payload.iterdir():
                archive.write(path, self.payload.name + '/' + path.name)
        self.build = dict(success=True, build_mode='local', remote_operations_performed=False,
                          model=self.model, period_seconds=.001, payload=str(self.archive),
                          archive=str(self.archive), archive_sha256=workflow.file_hash(self.archive),
                          elf_sha256=self.elf_hash)
        self.receipt = self.root / 'x280_local_build.json'

    def select(self, archives):
        self.receipt.write_text(json.dumps(self.build), encoding='utf-8-sig')
        return workflow.select_builds([self.receipt], archives)

    def test_zip_receipt_extracts_for_deployment_and_cleans_up(self):
        with closing(workflow.PayloadArchive()) as archives:
            record, = self.select(archives)
            extracted = Path(record['payload']['directory'])
            self.assertNotEqual(extracted, self.payload)
            self.assertEqual(len(list(extracted.iterdir())), 3)
            self.assertEqual(workflow.file_hash(record['payload']['elf']), self.elf_hash)
        self.assertFalse(extracted.exists())

    def test_legacy_directory_receipt_remains_supported(self):
        self.build.pop('archive')
        self.build.pop('archive_sha256')
        self.build['payload'] = str(self.payload)
        with closing(workflow.PayloadArchive()) as archives:
            record, = self.select(archives)
            self.assertEqual(Path(record['payload']['directory']), self.payload)
        self.assertTrue(self.payload.exists())

    def test_archive_hash_mismatch_is_rejected(self):
        self.build['archive_sha256'] = '0' * 64
        with closing(workflow.PayloadArchive()) as archives:
            with self.assertRaisesRegex(ValueError, 'payload ZIP do not match'):
                self.select(archives)

    def test_elf_hash_mismatch_is_rejected(self):
        self.build['elf_sha256'] = '0' * 64
        with closing(workflow.PayloadArchive()) as archives:
            with self.assertRaisesRegex(ValueError, 'payload ELF do not match'):
                self.select(archives)

    def test_main_always_closes_archive_cache_on_failure(self):
        with patch.object(workflow, 'PayloadArchive') as loader, patch.object(workflow, '_run', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                workflow.main([])
            loader.return_value.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
