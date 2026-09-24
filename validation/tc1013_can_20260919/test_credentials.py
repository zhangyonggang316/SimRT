"""Offline checks for hardware validation credential handling."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_vendor
import target_probe
import verify_model_hardware


class CredentialTests(unittest.TestCase):
    def test_missing_or_empty_password_is_rejected(self):
        for values in ({}, {"SIMRT_SSH_PASSWORD": ""}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                with self.assertRaisesRegex(ValueError, "SIMRT_SSH_PASSWORD"):
                    target_probe.credentials_from_environment()

    def test_default_endpoint_and_password_preserved(self):
        password = " fixture password with spaces "
        with patch.dict(os.environ, {"SIMRT_SSH_PASSWORD": password}, clear=True):
            with patch.object(Path, "read_text", side_effect=AssertionError("No document reads")):
                self.assertEqual(target_probe.credentials_from_environment(),
                                 ("192.168.219.86", "zh", password))

    def test_endpoint_overrides(self):
        values = {"SIMRT_SSH_PASSWORD": "fixture-password",
                  "SIMRT_SSH_HOST": " 192.0.2.10 ", "SIMRT_SSH_USERNAME": " operator "}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(target_probe.credentials_from_environment(),
                             ("192.0.2.10", "operator", "fixture-password"))

    def test_empty_endpoint_is_rejected_without_echoing_password(self):
        for name in ("SIMRT_SSH_HOST", "SIMRT_SSH_USERNAME"):
            values = {"SIMRT_SSH_PASSWORD": "fixture-password", name: " "}
            with self.subTest(name=name), patch.dict(os.environ, values, clear=True):
                with self.assertRaises(ValueError) as caught:
                    target_probe.credentials_from_environment()
                self.assertNotIn("fixture-password", str(caught.exception))

    def test_all_callers_share_environment_helper(self):
        for module in (install_vendor, verify_model_hardware):
            self.assertIs(module.credentials_from_environment,
                          target_probe.credentials_from_environment)

    def test_probe_missing_password_never_connects(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(target_probe, "SSHDeployment") as deployment, \
                    patch.object(target_probe, "local_sdk_inventory", return_value={}), \
                    patch("sys.argv", ["target_probe.py", "--output", str(output)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                deployment.return_value.connected = False
                self.assertEqual(target_probe.main(), 1)
                deployment.return_value.connect.assert_not_called()
                deployment.return_value.close.assert_called_once()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["ssh_connected"])
            self.assertIn("SIMRT_SSH_PASSWORD", report["error"]["message"])

    def test_installer_missing_password_never_connects_or_installs(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(install_vendor, "SSHDeployment") as deployment, \
                patch.object(install_vendor, "install") as install, \
                patch.object(Path, "write_text") as write, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install_vendor.main(), 1)
            deployment.return_value.connect.assert_not_called()
            deployment.return_value.close.assert_called_once()
            install.assert_not_called()
            report = json.loads(write.call_args.args[0])
            self.assertFalse(report["passed"])
            self.assertIn("SIMRT_SSH_PASSWORD", report["error"]["message"])


if __name__ == "__main__":
    unittest.main()
