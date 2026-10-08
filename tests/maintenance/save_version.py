"""Save every workspace file outside the workspace, then verify the ZIP contents."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import zipfile
from datetime import datetime, timezone


def inventory(root):
    files, directories = {}, []
    for current, names, leaves in os.walk(root, followlinks=False):
        names.sort()
        for name in names + sorted(leaves):
            path = Path(current) / name
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RuntimeError(f"Refusing symlink or reparse point: {path}")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
            elif stat.S_ISREG(info.st_mode):
                files[relative] = (info.st_size, info.st_mtime_ns)
            else:
                raise RuntimeError(f"Unsupported filesystem entry: {path}")
    return files, directories


def digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(block)
    return value.hexdigest()


def save_version(root, output, version):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("The version directory must be outside the workspace.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", version):
        raise ValueError("Use a filename-safe version identifier.")
    workspace_path = str(root)
    # Older Windows Python installations still enforce MAX_PATH without this prefix.
    if os.name == "nt" and not workspace_path.startswith("\\\\?\\"):
        root = Path("\\\\?\\UNC\\" + workspace_path[2:] if workspace_path.startswith("\\\\") else "\\\\?\\" + workspace_path)
    files, directories = inventory(root)
    if not files or "snapshot_manifest.json" in files:
        raise ValueError("Workspace is empty or contains reserved snapshot_manifest.json.")
    destination = output / version
    destination.mkdir(parents=True, exist_ok=False)
    partial = destination / (version + ".zip.partial")
    manifest = {
        "format_version": 1,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace_path,
        "scope": "All files on disk; no exclusions. External installations and target machine are not included.",
        "files": [],
    }
    last_progress = time.monotonic()
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for relative in directories:
            archive.write(root / relative, relative + "/")
        for index, relative in enumerate(sorted(files), 1):
            path = root / relative
            archive.write(path, relative)
            with path.open("rb") as source:
                value = digest(source)
            manifest["files"].append({"path": relative, "bytes": files[relative][0], "sha256": value})
            if time.monotonic() - last_progress >= 15:
                print(f"Archived {index}/{len(files)} files", flush=True)
                last_progress = time.monotonic()
        # Detect edits or new/deleted files while the snapshot was being copied.
        if inventory(root) != (files, directories):
            raise RuntimeError("Workspace changed during backup; incomplete .partial retained for inspection.")
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        archive.writestr("snapshot_manifest.json", manifest_text.encode("utf-8"))
    print("Verifying every archived file against SHA-256 manifest", flush=True)
    with zipfile.ZipFile(partial) as archive:
        for entry in manifest["files"]:
            info = archive.getinfo(entry["path"])
            with archive.open(info) as source:
                if info.file_size != entry["bytes"] or digest(source) != entry["sha256"]:
                    raise RuntimeError(f"Archive verification failed: {entry['path']}")
        if json.loads(archive.read("snapshot_manifest.json")) != manifest:
            raise RuntimeError("Embedded manifest verification failed.")
    final = partial.with_suffix("")
    partial.rename(final)
    (destination / "snapshot_manifest.json").write_text(manifest_text, encoding="utf-8")
    with final.open("rb") as source:
        archive_hash = digest(source)
    result = {
        "version": version,
        "archive": str(final),
        "archive_bytes": final.stat().st_size,
        "archive_sha256": archive_hash,
        "files": len(files),
        "source_bytes": sum(entry["bytes"] for entry in manifest["files"]),
        "verified_files": len(files),
        "passed": True,
    }
    (destination / "snapshot_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (destination / (version + ".zip.sha256")).write_text(archive_hash + "  " + final.name + "\n", encoding="ascii")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2]
    save_version(workspace, args.output or workspace.parent / (workspace.name + "_versions"), args.version)
