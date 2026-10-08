"""Prepare an opt-in SDK variant correcting the proven detached-thread reference."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = ROOT / "simrt_linux_target/drivers/tc1013"
sys.path.insert(0, str(DRIVER))
from prepare_driver import prepare_sdk

ORIGINAL_SHA256 = "8308ec91016870da114ba476d496900cdf73fe2aaa038e0aa00cf56a44bd6758"
INSTRUCTION_OFFSET = 0xD185
ORIGINAL_INSTRUCTION = bytes.fromhex("48 8d 45 98")
FIXED_INSTRUCTION = bytes.fromhex("48 8d 45 a0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    vendor = DRIVER / "vendor"
    original = (vendor / "linux/libTSH.so").read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise RuntimeError("This correction is valid only for the reviewed pinned vendor binary")
    if original[INSTRUCTION_OFFSET:INSTRUCTION_OFFSET + 4] != ORIGINAL_INSTRUCTION:
        raise RuntimeError("Unexpected instruction at the reviewed file offset")
    updated = bytearray(original)
    updated[INSTRUCTION_OFFSET:INSTRUCTION_OFFSET + 4] = FIXED_INSTRUCTION
    if sum(a != b for a, b in zip(original, updated)) != 1:
        raise RuntimeError("Correction must change exactly one byte")
    record = dict(original_sha256=ORIGINAL_SHA256,
                  patched_sha256=hashlib.sha256(updated).hexdigest(),
                  file="libTSH.so", file_offset=hex(INSTRUCTION_OFFSET),
                  original_instruction=ORIGINAL_INSTRUCTION.hex(),
                  patched_instruction=FIXED_INSTRUCTION.hex(),
                  effect="Use live write-thread object at rbp-0x60 instead of detached read-thread object at rbp-0x68",
                  evidence="sdk_gdb_backtrace.json; sdk_gdb_skip_invalid_sched.json",
                  vendor_files_modified=False, production_selection_changed=False)
    with tempfile.TemporaryDirectory(prefix="tc1013-compat-") as temporary:
        stage = Path(temporary)
        shutil.copyfile(vendor / "linux/libTSCANApiOnLinux.so", stage / "libTSCANApiOnLinux.so")
        (stage / "libTSH.so").write_bytes(updated)
        shutil.copyfile(vendor / "LICENSE", stage / "LICENSE")
        notice = (vendor / "SOURCE.md").read_text(encoding="utf-8")
        notice += """

## Local compatibility correction, 2026-09-26

This directory is an opt-in derived SDK, not an unmodified vendor release.
GDB identified libTSH AddHIDDevice, HIDControl.cpp:458, calling
pthread_setschedparam with a null native handle after detaching the read thread.
The preceding creation of the write thread is successful. One instruction's
stack-relative operand is corrected from the detached read-thread object
(rbp-0x68) to the live write-thread object (rbp-0x60).

The original MIT license is retained. The project vendor directory and default
target SDK remain unchanged. No CAN protocol, message, bitrate, or firmware
operation is modified. This is a local compatibility fix, not vendor approval.

Correction receipt:

```json
""" + json.dumps(record, indent=2) + "\n```\n"
        (stage / "SOURCE.md").write_text(notice, encoding="utf-8")
        output, libraries = prepare_sdk(stage, args.output)
    record["prepared_directory"] = str(output)
    record["libraries"] = libraries
    args.output.with_suffix(".patch.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
