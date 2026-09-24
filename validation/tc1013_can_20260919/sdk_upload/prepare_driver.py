"""Validate and stage the vendor Linux x86_64 SDK without contacting hardware.

The generated directory can be uploaded using an SFTP client or scp.
Running this same tool on Linux with a new --output directory installs the files
without replacing an existing installation. No non-standard Python packages.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile


REQUIRED_LIBRARIES = ("libTSCANApiOnLinux.so", "libTSH.so")
MANIFEST_NAME = "tc1013-sdk-manifest.json"
LIBRARY_NAME = re.compile(r"[A-Za-z0-9_+.-]+\.so(?:\.[A-Za-z0-9_+.-]+)*\Z")


class DriverPreparationError(ValueError):
    """A vendor SDK directory is incomplete or incompatible with the target."""


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_elf(path):
    """Read the ELF64 header using its specified little-endian layout."""
    with path.open("rb") as stream:
        header = stream.read(64)
    label = path.name
    if len(header) < 64 or header[:4] != b"\x7fELF":
        raise DriverPreparationError("{}: expected a Linux ELF library, not a DLL or truncated file".format(label))
    if header[4] != 2:
        raise DriverPreparationError("{}: ELF64 is required (ELF class {})".format(label, header[4]))
    if header[5] != 1:
        raise DriverPreparationError("{}: little-endian ELF is required".format(label))
    fields = struct.unpack("<16sHHIQQQIHHHHHH", header)
    _, kind, machine, version, _, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = fields
    if header[6] != 1 or version != 1 or ehsize != 64:
        raise DriverPreparationError("{}: invalid ELF header version or size".format(label))
    if machine != 62:
        raise DriverPreparationError("{}: x86_64 EM_X86_64=62 is required (machine {})".format(label, machine))
    if kind != 3:
        raise DriverPreparationError("{}: a shared library ET_DYN=3 is required (type {})".format(label, kind))
    size = path.stat().st_size
    if phnum == 0xFFFF:
        raise DriverPreparationError("{}: extended ELF program-header counts are unsupported".format(label))
    if phnum and (phoff < 64 or phsize != 56 or phoff + phsize * phnum > size):
        raise DriverPreparationError("{}: invalid or truncated ELF program-header table".format(label))
    if shnum and (shoff < 64 or shsize != 64 or shoff + shsize * shnum > size):
        raise DriverPreparationError("{}: invalid or truncated ELF section-header table".format(label))
    return {"size": size, "sha256": sha256_file(path), "format": "ELF64 little-endian x86_64 ET_DYN"}


def inspect_sdk(directory):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir():
        raise DriverPreparationError("SDK path must be a directory: {}".format(directory))
    missing = [name for name in REQUIRED_LIBRARIES if not (directory / name).is_file()]
    if missing:
        raise DriverPreparationError("missing required Linux libraries: {}".format(", ".join(missing)))
    records = {}
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not LIBRARY_NAME.fullmatch(entry.name):
            continue
        try:
            resolved = entry.resolve(strict=True)
            resolved.relative_to(directory)
        except (OSError, ValueError) as error:
            raise DriverPreparationError("{}: library link must resolve inside the SDK directory".format(entry.name)) from error
        if not resolved.is_file():
            raise DriverPreparationError("{}: library must be a regular file".format(entry.name))
        records[entry.name] = inspect_elf(entry)
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise DriverPreparationError("{} is not a readable JSON manifest".format(MANIFEST_NAME)) from error
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("libraries") != records:
            raise DriverPreparationError("SDK files do not match {}; upload may be incomplete or modified".format(MANIFEST_NAME))
    return directory, records


def prepare_sdk(directory, output):
    source, records = inspect_sdk(directory)
    requested_output = Path(output)
    output = requested_output.parent.resolve() / requested_output.name
    if os.path.lexists(str(output)):
        raise DriverPreparationError("output already exists; choose a new directory: {}".format(output))
    try:
        output.relative_to(source)
    except ValueError:
        pass
    else:
        raise DriverPreparationError("output must be outside the SDK source directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "required_libraries": list(REQUIRED_LIBRARIES),
        "libraries": records,
        "verification": "ELF headers and SHA256 only; no SDK loading, USB access or hardware test",
    }
    with tempfile.TemporaryDirectory(prefix=".tc1013-stage-", dir=str(output.parent)) as temporary:
        staging = Path(temporary)
        for name, record in records.items():
            # Materialize versioned symlinks as files so ordinary SFTP uploads work.
            shutil.copyfile(source / name, staging / name)
            if inspect_elf(staging / name) != record:
                raise DriverPreparationError("{} changed while preparing the SDK".format(name))
            (staging / name).chmod(0o644)
        shutil.copyfile(Path(__file__).resolve(), staging / "prepare_driver.py")
        shutil.copyfile(Path(__file__).resolve().with_name("DEPLOY_DRIVER.md"), staging / "DEPLOY_DRIVER.md")
        (staging / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        created = []
        try:
            # mkdir is exclusive on Windows and Linux, including an existing empty directory.
            output.mkdir()
        except FileExistsError as error:
            raise DriverPreparationError("output already exists; choose a new directory: {}".format(output)) from error
        try:
            for item in staging.iterdir():
                destination = output / item.name
                with item.open("rb") as incoming, destination.open("xb") as outgoing:
                    created.append(destination)
                    shutil.copyfileobj(incoming, outgoing)
                destination.chmod(0o644)
        except BaseException:
            for item in reversed(created):
                item.unlink()
            try:
                output.rmdir()
            except OSError:
                pass
            raise
    return output, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", required=True, type=Path, help="Directory containing the vendor Linux shared libraries")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="New directory to prepare or install; existing paths are never replaced")
    mode.add_argument("--check", action="store_true", help="Read-only ELF validation and manifest verification when present")
    args = parser.parse_args(argv)
    try:
        if args.check:
            directory, libraries = inspect_sdk(args.sdk_dir)
        else:
            directory, libraries = prepare_sdk(args.sdk_dir, args.output)
    except (DriverPreparationError, OSError) as error:
        print("TC1013 SDK error: {}".format(error), file=sys.stderr)
        return 2
    print(json.dumps({"directory": str(directory), "library_count": len(libraries),
                      "libraries": sorted(libraries), "passed": True,
                      "hardware_tested": False}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
