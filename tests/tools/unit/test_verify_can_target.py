"""Regression checks for explicit target selection and CAN payload validation."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import struct
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_can_target as verifier


class CANVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simrt_can_fixture_')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        model = 'simrt_can_loopback'
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', header, 16, 2, 62, 1)
        measurements = []
        for channel in (1, 2):
            for offset, suffix in enumerate(('TxStatus', 'RxStatus', 'Valid', 'ID', 'Data')):
                array = 'MATRIX_DIM 8' if suffix == 'Data' else ''
                measurements.append('/begin MEASUREMENT {}_B.CAN{}_{} "fixture" UBYTE NO_COMPU_METHOD 0 0 0 255 ECU_ADDRESS {} {} /end MEASUREMENT'.format(
                    model, channel, suffix, 4096 + channel * 128 + offset * 8, array))
        a2l = ('/begin PROJECT fixture "fixture" /begin MODULE fixture "fixture"\n'
               '/begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON\n' +
               '\n'.join(measurements) + '\n/end MODULE /end PROJECT').encode()
        manifest = dict(SchemaVersion=2, ModelName=model, ELFFile=model + '.elf',
                        A2LFile=model + '.a2l', ELFSHA256=hashlib.sha256(header).hexdigest(),
                        A2LSHA256=hashlib.sha256(a2l).hexdigest(), XCPTransport='UDP',
                        XCPPort=5555, TargetAddress='192.0.2.20')
        self.payload = root / 'fixture.zip'
        with zipfile.ZipFile(self.payload, 'w') as archive:
            archive.writestr('fixture/' + model + '.elf', header)
            archive.writestr('fixture/' + model + '.a2l', a2l)
            archive.writestr('fixture/' + model + '.xcp-manifest.json', json.dumps(manifest))

    def test_zip_loads_all_received_bytes(self):
        with closing(verifier.PayloadArchive()) as archive:
            payload, manifest, catalog, names = verifier.load_payload(archive, self.payload, 8)
            self.assertEqual(len(names), 24)
            self.assertEqual(manifest["ModelName"], "simrt_can_loopback")
            self.assertIn("simrt_can_loopback_B.CAN2_Data[7]", names)
            extracted = Path(payload["directory"])
            self.assertTrue(extracted.is_dir())
        self.assertFalse(extracted.exists())

    def test_wrong_payload_length_is_rejected(self):
        with closing(verifier.PayloadArchive()) as archive:
            with self.assertRaisesRegex(ValueError, "payload type or length"):
                verifier.load_payload(archive, self.payload, 64)

    def test_check_does_not_prompt_or_connect_and_preserves_source_address(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "result.json"
            with patch.object(verifier.getpass, "getpass") as prompt, \
                    patch.object(verifier.SSHDeployment, "connect") as connect:
                code = verifier.main([
                    str(self.payload), "--host", "192.0.2.15", "--user", "example",
                    "--port", "18000", "--check", "--output", str(output)])
            prompt.assert_not_called()
            connect.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(result["xcp_endpoint"]["host"], "192.0.2.15")
            self.assertEqual(result["xcp_endpoint"]["port"], 18000)
            self.assertEqual(result["manifest"]["XCPPort"], 5555)
            self.assertEqual(result["manifest"]["TargetAddress"], "192.0.2.20")
            self.assertFalse(result["hardware_tested"])

    def test_failed_upload_does_not_stop_an_unowned_process(self):
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(payload=self.payload, host="192.0.2.15", user="example",
                                      baseline=False, check=False, length=8, seconds=6,
                                      remote_root=None, output=Path(temp) / "result.json")
            with patch.object(verifier, "SSHDeployment") as factory:
                service = factory.return_value
                service.connected = True
                service.upload.side_effect = RuntimeError("upload rejected")
                result = verifier.verify(args, "temporary-password")
            self.assertFalse(result["passed"])
            self.assertEqual(result["error"]["message"], "upload rejected")
            service.stop.assert_not_called()
            service.connect.assert_called_once_with("192.0.2.15", "example", password="temporary-password")
            self.assertNotIn("temporary-password", args.output.read_text(encoding="utf-8"))

    def test_waveform_matches_delayed_peer_values_and_rejects_corruption(self):
        prefix = "wave_B."
        samples = []
        for index in range(1700):
            values = {}
            for channel in (1, 2):
                name = prefix + "CAN{}".format(channel)
                values.update({name + "set": float(index), name + "_Data": float(max(index - 3, 0)),
                               name + "_ID": 514 if channel == 1 else 257,
                               name + "_Valid": True, name + "_TxStatus": 0, name + "_RxStatus": 0})
            samples.append(SimpleNamespace(timestamp_seconds=index / 1000.0, values=values))
        result = verifier.evaluate_waveform(samples, "wave")
        self.assertTrue(all(channel["passed"] for channel in result.values()))
        samples[-1].values[prefix + "CAN1_Data"] = 99999.0
        result = verifier.evaluate_waveform(samples, "wave")
        self.assertFalse(result["CAN1"]["passed"])
        self.assertEqual(result["CAN1"]["mismatches"], 1)
        self.assertTrue(result["CAN2"]["passed"])

    def test_process_disappearance_with_stale_running_status_is_not_clean_exit(self):
        completed = dict(state="STOPPED", pid=123, model_step_calls=13000,
                         model_step_completed_calls=13000)
        self.assertTrue(verifier.clean_termination(completed, 123))
        self.assertFalse(verifier.clean_termination(dict(completed, state="RUNNING"), 123))
        self.assertFalse(verifier.clean_termination(dict(completed, pid=124), 123))
        self.assertFalse(verifier.clean_termination(dict(completed, model_step_completed_calls=12999), 123))
        self.assertFalse(verifier.clean_termination(None, 123))


if __name__ == "__main__":
    unittest.main()
