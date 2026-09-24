import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "prepare_driver.py"
SPEC = importlib.util.spec_from_file_location("tc1013_prepare_driver", TOOL)
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def elf_bytes(machine=62, kind=3, elf_class=2, endian=1):
    identity = b"\x7fELF" + bytes((elf_class, endian, 1)) + bytes(9)
    return struct.pack("<16sHHIQQQIHHHHHH", identity, kind, machine, 1,
                       0, 0, 0, 0, 64, 56, 0, 64, 0, 0) + b"test-library-content"


class PrepareDriverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        for name in driver.REQUIRED_LIBRARIES:
            (self.sdk / name).write_bytes(elf_bytes())
        (self.sdk / "blf.so").write_bytes(elf_bytes())
        self.output = self.root / "upload"

    def test_complete_bundle_preserves_dependency_and_can_be_installed_again(self):
        (self.sdk / "libusb-1.0.so.0").write_bytes(elf_bytes())
        (self.sdk / "libTSCAN.dll").write_bytes(b"MZ")
        (self.sdk / "LICENSE").write_text("Vendor redistribution notice", encoding="utf-8")
        _, records = driver.prepare_sdk(self.sdk, self.output)
        self.assertEqual(len(records), 4)
        self.assertFalse((self.output / "libTSCAN.dll").exists())
        self.assertTrue((self.output / "prepare_driver.py").is_file())
        self.assertTrue((self.output / "DEPLOY_DRIVER.md").is_file())
        _, checked = driver.inspect_sdk(self.output)
        self.assertEqual(records, checked)
        installed = self.root / "installed"
        driver.prepare_sdk(self.output, installed)
        self.assertEqual(driver.inspect_sdk(installed)[1], records)
        self.assertEqual((installed / "LICENSE").read_text(encoding="utf-8"),
                         "Vendor redistribution notice")

    def test_missing_required_library(self):
        (self.sdk / "libTSH.so").unlink()
        with self.assertRaisesRegex(driver.DriverPreparationError, "missing required Linux libraries: libTSH.so"):
            driver.prepare_sdk(self.sdk, self.output)
        self.assertFalse(self.output.exists())

    def test_dll_renamed_as_shared_library_rejected(self):
        (self.sdk / "libTSH.so").write_bytes(b"MZ" + bytes(100))
        with self.assertRaisesRegex(driver.DriverPreparationError, "not a DLL"):
            driver.inspect_sdk(self.sdk)

    def test_wrong_architecture_class_endian_and_type(self):
        for options, message in [({"machine": 183}, "EM_X86_64"),
                                 ({"elf_class": 1}, "ELF64"),
                                 ({"endian": 2}, "little-endian"),
                                 ({"kind": 2}, "ET_DYN")]:
            with self.subTest(options=options):
                (self.sdk / "blf.so").write_bytes(elf_bytes(**options))
                with self.assertRaisesRegex(driver.DriverPreparationError, message):
                    driver.inspect_sdk(self.sdk)

    def test_truncated_header_and_tables_rejected(self):
        (self.sdk / "blf.so").write_bytes(elf_bytes()[:40])
        with self.assertRaisesRegex(driver.DriverPreparationError, "truncated"):
            driver.inspect_sdk(self.sdk)
        broken = bytearray(elf_bytes())
        struct.pack_into("<Q", broken, 32, 64)
        struct.pack_into("<H", broken, 56, 1)
        (self.sdk / "blf.so").write_bytes(broken)
        with self.assertRaisesRegex(driver.DriverPreparationError, "program-header table"):
            driver.inspect_sdk(self.sdk)

    def test_existing_output_is_never_replaced_even_when_empty(self):
        self.output.mkdir()
        with self.assertRaisesRegex(driver.DriverPreparationError, "output already exists"):
            driver.prepare_sdk(self.sdk, self.output)
        marker = self.output / "user.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(driver.DriverPreparationError, "output already exists"):
            driver.prepare_sdk(self.sdk, self.output)
        self.assertEqual(marker.read_text(), "keep")

    def test_output_inside_source_rejected(self):
        with self.assertRaisesRegex(driver.DriverPreparationError, "outside the SDK"):
            driver.prepare_sdk(self.sdk, self.sdk / "prepared")

    def test_invalid_extra_shared_library_rejected(self):
        (self.sdk / "libextra.so.1").write_bytes(elf_bytes(machine=183))
        with self.assertRaisesRegex(driver.DriverPreparationError, "libextra.so.1"):
            driver.inspect_sdk(self.sdk)

    def test_manifest_detects_modified_and_additional_libraries(self):
        driver.prepare_sdk(self.sdk, self.output)
        (self.output / "blf.so").write_bytes(elf_bytes() + b"modified")
        with self.assertRaisesRegex(driver.DriverPreparationError, "do not match"):
            driver.inspect_sdk(self.output)
        (self.output / "blf.so").write_bytes(elf_bytes())
        (self.output / "libextra.so").write_bytes(elf_bytes())
        with self.assertRaisesRegex(driver.DriverPreparationError, "do not match"):
            driver.inspect_sdk(self.output)

    def test_malformed_manifest_rejected(self):
        (self.sdk / driver.MANIFEST_NAME).write_text("not-json")
        with self.assertRaisesRegex(driver.DriverPreparationError, "readable JSON"):
            driver.inspect_sdk(self.sdk)

    def test_symlinks_materialized_and_external_links_rejected(self):
        external = self.root / "external.so"
        external.write_bytes(elf_bytes())
        link = self.sdk / "libalias.so"
        try:
            link.symlink_to(self.sdk / "blf.so")
        except OSError:
            self.skipTest("creating symbolic links is unavailable")
        driver.prepare_sdk(self.sdk, self.output)
        self.assertFalse((self.output / "libalias.so").is_symlink())
        link.unlink()
        link.symlink_to(external)
        with self.assertRaisesRegex(driver.DriverPreparationError, "inside the SDK directory"):
            driver.inspect_sdk(self.sdk)

    def test_cli_success_and_actionable_failure(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = driver.main(["--sdk-dir", str(self.sdk), "--check"])
        self.assertEqual(status, 0)
        self.assertFalse(json.loads(stdout.getvalue())["hardware_tested"])
        (self.sdk / "libTSH.so").unlink()
        with contextlib.redirect_stderr(stderr):
            status = driver.main(["--sdk-dir", str(self.sdk), "--output", str(self.output)])
        self.assertEqual(status, 2)
        self.assertIn("TC1013 SDK error: missing required Linux libraries: libTSH.so", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_current_vendor_release_without_separate_blf_library(self):
        (self.sdk / "blf.so").unlink()
        _, records = driver.prepare_sdk(self.sdk, self.output)
        self.assertEqual(set(records), set(driver.REQUIRED_LIBRARIES))


if __name__ == "__main__":
    unittest.main()
