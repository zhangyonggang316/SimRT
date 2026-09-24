"""Deployment ZIP validation and process-owned extraction lifecycle."""

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from pyxcp_host.services import payload_archive
from pyxcp_host.services.payload_archive import PayloadArchive


def payload_files(value='A'):
    elf = bytearray(64)
    elf[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', elf, 16, 2, 62, 1)
    a2l = ('/begin PROJECT fixture "%s" /end PROJECT' % value).encode('ascii')
    manifest = dict(
        SchemaVersion=2, ModelName='fixture', ELFFile='fixture.elf',
        A2LFile='fixture.a2l', ELFSHA256=hashlib.sha256(elf).hexdigest(),
        A2LSHA256=hashlib.sha256(a2l).hexdigest(), RuntimeFiles={},
        XCPTransport='UDP', XCPPort=17725, TargetAddress='192.0.2.5',
    )
    return {
        'fixture.elf': bytes(elf),
        'fixture.a2l': a2l,
        'fixture.xcp-manifest.json': json.dumps(manifest).encode('ascii'),
    }


class PayloadArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.loader = PayloadArchive()
        self.folder = '20260919_102030_456'

    def tearDown(self):
        self.loader.close()
        self.temporary.cleanup()

    def entries(self, value='A'):
        return [(self.folder + '/' + name, content)
                for name, content in payload_files(value).items()]

    def archive(self, entries=None, filename='model.zip'):
        destination = self.root / filename
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name, content in self.entries() if entries is None else entries:
                    info = zipfile.ZipInfo(name) if isinstance(name, str) else name
                    archive.writestr(info, content)
        return destination

    def test_loads_three_files_with_optional_enclosing_directory_entry(self):
        for directory_entry in (False, True):
            with self.subTest(directory_entry=directory_entry):
                entries = self.entries()
                if directory_entry:
                    entries.insert(0, (self.folder + '/', b''))
                source = self.archive(entries, 'model-%s.ZIP' % directory_entry)
                result = self.loader.load(source)
                self.assertEqual(result['source'], str(source))
                self.assertEqual(result['model'], 'fixture')
                self.assertEqual((result['host'], result['protocol'], result['port']),
                                 ('192.0.2.5', 'UDP', 17725))
                self.assertEqual(set(result['files']), set(payload_files()))
                self.assertNotEqual(Path(result['directory']).parent, source.parent)
                for name, content in payload_files().items():
                    self.assertEqual((Path(result['directory']) / name).read_bytes(), content)
                self.assertFalse((source.parent / self.folder).exists())

    def test_directory_selection_is_validated_but_not_owned_or_deleted(self):
        directory = self.root / 'existing'
        directory.mkdir()
        for name, content in payload_files().items():
            (directory / name).write_bytes(content)
        result = self.loader.load(directory)
        self.assertEqual(result['directory'], str(directory))
        self.assertEqual(result['source'], str(directory))
        self.loader.close()
        self.assertTrue(directory.is_dir())

    def test_cache_reuses_validated_extraction_and_close_removes_it(self):
        source = self.archive()
        first = self.loader.load(source)
        second = self.loader.load(source)
        self.assertEqual(first['directory'], second['directory'])
        extracted = Path(first['directory'])
        self.loader.close()
        self.assertFalse(extracted.parent.exists())
        self.assertTrue(source.is_file())
        self.loader.close()

    def test_cache_detects_same_size_same_timestamp_archive_replacement(self):
        source = self.archive()
        original_stat = source.stat()
        first = self.loader.load(source)
        self.archive(self.entries('B'))
        self.assertEqual(source.stat().st_size, original_stat.st_size)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        second = self.loader.load(source)
        self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual(Path(first['a2l']).read_bytes(), payload_files('A')['fixture.a2l'])
        self.assertEqual(Path(second['a2l']).read_bytes(), payload_files('B')['fixture.a2l'])
        self.loader.close()
        self.assertFalse(Path(first['directory']).exists())
        self.assertFalse(Path(second['directory']).exists())

    def test_cached_extracted_files_are_revalidated(self):
        source = self.archive()
        first = self.loader.load(source)
        Path(first['a2l']).write_bytes(b'changed after extraction')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.loader.load(source)

    def test_failed_selection_cleans_new_extraction_and_preserves_active_payload(self):
        source = self.archive(filename='good.zip')
        active = self.loader.load(source)
        invalid = self.entries()
        invalid[1] = (invalid[1][0], b'A2L from a different build')
        candidate = self.archive(invalid, 'invalid.zip')
        created = []
        factory = tempfile.TemporaryDirectory

        def temporary_directory(*args, **kwargs):
            temporary = factory(*args, **kwargs)
            created.append(Path(temporary.name))
            return temporary

        with patch.object(payload_archive.tempfile, 'TemporaryDirectory', temporary_directory):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                self.loader.load(candidate)
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())
        self.assertTrue(Path(active['elf']).is_file())
        self.assertEqual(self.loader.load(source)['directory'], active['directory'])

    def test_rejects_traversal_ambiguous_and_windows_special_paths(self):
        bad_names = [
            '../fixture.elf', '/outside/fixture.elf', 'C:/fixture.elf',
            self.folder + '/../fixture.elf', self.folder + '/..\\fixture.elf',
            self.folder + '\\fixture.elf', './' + self.folder + '/fixture.elf',
            self.folder + '//fixture.elf', self.folder + '/nested/fixture.elf',
            self.folder + '/fixture.elf.', self.folder + '/fixture.elf ',
            self.folder + '/bad\nname.elf', self.folder + '/fixture.elf:stream',
            self.folder + '/CON.elf', self.folder + '/lpt9.elf',
            self.folder + '/bad?name.elf', self.folder + '/bad|name.elf',
        ]
        for name in bad_names:
            with self.subTest(name=name):
                entries = self.entries()
                entries[0] = (name, entries[0][1])
                source = self.archive(entries)
                if '\\' in name:
                    # ZipInfo normalizes Windows separators when writing.
                    source.write_bytes(source.read_bytes().replace(
                        name.replace('\\', '/').encode('ascii'), name.encode('ascii')))
                with self.assertRaises(ValueError):
                    self.loader.load(source)
        self.assertFalse((self.root / 'fixture.elf').exists())

    def test_rejects_null_truncated_filename(self):
        entries = self.entries()
        entries[0] = (self.folder + '/fixtureX.elf', entries[0][1])
        source = self.archive(entries)
        source.write_bytes(source.read_bytes().replace(b'fixtureX.elf', b'fixture\x00.elf'))
        with self.assertRaises(ValueError):
            self.loader.load(source)

    def test_rejects_duplicate_filenames_including_case_variants(self):
        for name in ('fixture.elf', 'FIXTURE.ELF'):
            with self.subTest(name=name):
                entries = self.entries()
                entries[1] = (self.folder + '/' + name, entries[1][1])
                with self.assertRaises(ValueError):
                    self.loader.load(self.archive(entries))

    def test_rejects_symlinks_special_files_and_inconsistent_directory_mode(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFDIR):
            with self.subTest(mode=mode):
                entries = self.entries()
                info = zipfile.ZipInfo(entries[0][0])
                info.create_system = 3
                info.external_attr = (mode | 0o644) << 16
                entries[0] = (info, entries[0][1])
                with self.assertRaises(ValueError):
                    self.loader.load(self.archive(entries))

    def test_rejects_wrong_layout_extra_files_and_multiple_result_folders(self):
        layouts = [
            [(name, content) for name, content in payload_files().items()],
            self.entries() + [(self.folder + '/notes.txt', b'not deployable')],
            self.entries() + [('other/', b'')],
            [(('other/' + name.split('/')[-1]) if index == 1 else name, content)
             for index, (name, content) in enumerate(self.entries())],
            self.entries()[:-1],
            self.entries() + [(self.folder + '//', b'')],
        ]
        for entries in layouts:
            with self.subTest(names=[name for name, _ in entries]):
                with self.assertRaises(ValueError):
                    self.loader.load(self.archive(entries))

    def test_rejects_oversized_archive_and_expanded_payload(self):
        source = self.archive()
        with patch.object(payload_archive, 'MAX_ARCHIVE_BYTES', source.stat().st_size - 1):
            with self.assertRaises(ValueError):
                self.loader.load(source)
        with patch.object(payload_archive, 'MAX_PAYLOAD_BYTES', 63):
            with self.assertRaises(ValueError):
                self.loader.load(source)

    def test_rejects_encrypted_entries_before_extraction(self):
        source = self.archive()
        content = bytearray(source.read_bytes())
        central = content.index(b'PK\x01\x02')
        struct.pack_into('<H', content, central + 8, 1)
        source.write_bytes(content)
        with self.assertRaises(ValueError):
            self.loader.load(source)

    def test_rejects_bad_crc_and_truncated_archives(self):
        source = self.archive()
        with zipfile.ZipFile(source) as archive:
            entry = archive.infolist()[0]
            offset = entry.header_offset + 30 + len(entry.filename.encode('utf-8')) + len(entry.extra)
        content = bytearray(source.read_bytes())
        content[offset + 20] ^= 1
        source.write_bytes(content)
        with self.assertRaises(zipfile.BadZipFile):
            self.loader.load(source)
        source.write_bytes(source.read_bytes()[:40])
        with self.assertRaises(zipfile.BadZipFile):
            self.loader.load(source)

    def test_rejects_non_zip_files_and_missing_sources(self):
        text = self.root / 'notes.txt'
        text.write_text('not a deployment archive', encoding='ascii')
        for source in (text, self.root / 'missing.zip'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    self.loader.load(source)


if __name__ == '__main__':
    unittest.main()
