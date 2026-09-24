"""Credential tests use temporary paths and synthetic secrets only."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qt_host.credential_store import CredentialStore, _dpapi


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'user' / 'ssh.dpapi'
        self.record = dict(host='192.0.2.5', username='tester', password='synthetic-secret', port=2222)

    def fixture_store(self):
        payload = json.dumps(dict(schema=1, **self.record)).encode('utf-8')
        return CredentialStore(self.path, protect=lambda _: b'opaque fixture ciphertext', unprotect=lambda _: payload)

    def test_ciphertext_only_is_written_and_clear_removes_record(self):
        store = self.fixture_store()
        self.assertIsNone(store.load())
        store.save(**self.record)
        self.assertEqual(self.path.read_bytes(), b'opaque fixture ciphertext')
        self.assertNotIn(b'synthetic-secret', self.path.read_bytes())
        self.assertEqual(store.load(), self.record)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        store.clear()
        self.assertFalse(self.path.exists())
        self.assertIsNone(store.load())

    def test_failed_encryption_preserves_existing_record_without_plaintext_temp(self):
        store = self.fixture_store()
        store.save(**self.record)
        with patch.object(store, '_protect', side_effect=OSError('DPAPI unavailable')):
            with self.assertRaises(OSError):
                store.save(**self.record)
        self.assertEqual(self.path.read_bytes(), b'opaque fixture ciphertext')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_record_is_rejected_without_exposing_contents(self):
        store = self.fixture_store()
        store.save(**self.record)
        for payload in (b'not json: synthetic-secret', b'{"schema":1,"password":"synthetic-secret"}',
                        json.dumps(dict(schema=1, **dict(self.record, port=True))).encode()):
            with patch.object(store, '_unprotect', return_value=payload):
                with self.assertRaisesRegex(ValueError, '^Saved SSH credentials could not be restored$'):
                    store.load()

    def test_failed_atomic_replace_preserves_previous_ciphertext(self):
        store = self.fixture_store()
        store.save(**self.record)
        with patch('qt_host.credential_store.os.replace', side_effect=OSError('fixture filesystem failure')):
            with self.assertRaises(OSError):
                store.save(**self.record)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), b'opaque fixture ciphertext')

    def test_invalid_endpoint_is_rejected_before_creating_storage(self):
        store = self.fixture_store()
        for record in (dict(self.record, host='bad\nhost'), dict(self.record, username=''),
                       dict(self.record, port=65536), dict(self.record, password='contains\0null')):
            with self.assertRaises(ValueError):
                store.save(**record)
        self.assertFalse(self.path.parent.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI integration')
    def test_windows_dpapi_roundtrip_with_temporary_synthetic_credentials(self):
        store = CredentialStore(self.path)
        store.save(**self.record)
        self.assertNotIn(self.record['password'].encode(), self.path.read_bytes())
        self.assertEqual(store.load(), self.record)
        with self.assertRaises(OSError):
            _dpapi(b'invalid encrypted fixture', decrypt=True)
        store.clear()


if __name__ == '__main__':
    unittest.main()
