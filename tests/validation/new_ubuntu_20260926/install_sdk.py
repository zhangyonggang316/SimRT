"""Install the reviewed SDK on the pinned target without sending CAN frames."""

from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "qt_xcp_host"))
sys.path.insert(0, str(ROOT / "validation/tc1013_can_20260919"))
import target_session
import install_vendor
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__


def run(password):
    service = SSHDeployment()
    result = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                  host=target_session.HOST, user=target_session.USER,
                  host_key_sha256=target_session.FINGERPRINT,
                  can_frames_transmitted=0, passed=False)
    try:
        service._client = target_session.connect(password)
        password = None
        result["usb"] = json.loads(service._execute(
            "python3 -c " + shlex.quote(install_vendor.USB_ACCESS) + " inspect"))
        if not result["usb"]["after"]["writable"]:
            raise RuntimeError("Verified USB device is not writable as zh")
        source = HERE / "sdk_upload"
        files = {path.name: path for path in source.iterdir() if path.is_file()}
        hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
        stage = "/home/zh/tc1013-sdk-upload-" + uuid.uuid4().hex[:12]
        service._execute("mkdir -- " + shlex.quote(stage))
        with service._client.open_sftp() as sftp:
            for name, path in files.items():
                sftp.put(str(path), stage + "/" + name)
                sftp.chmod(stage + "/" + name, 0o644)
        command = """
import hashlib, json, subprocess, sys
from pathlib import Path
stage = Path(%r)
expected = %r
destination = Path('/home/zh/.local/lib/tscan')
actual = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in expected}
if actual != expected:
    raise RuntimeError('SDK upload SHA256 mismatch')
subprocess.run([sys.executable, str(stage / 'prepare_driver.py'), '--sdk-dir', str(stage), '--check'], check=True)
if destination.exists():
    current = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in expected if name != 'tc1013-sdk-manifest.json'}
    if any(current[name] != expected[name] for name in current):
        raise RuntimeError('Existing SDK installation differs; refusing overwrite')
    state = 'already_matches'
else:
    subprocess.run([sys.executable, str(stage / 'prepare_driver.py'), '--sdk-dir', str(stage),
                    '--output', str(destination)], check=True)
    state = 'installed'
subprocess.run([sys.executable, str(destination / 'prepare_driver.py'), '--sdk-dir', str(destination), '--check'], check=True)
installed = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in expected if name != 'tc1013-sdk-manifest.json'}
if any(installed[name] != expected[name] for name in installed):
    raise RuntimeError('Installed SDK SHA256 mismatch')
print('SDK_INSTALL_JSON=' + json.dumps({'destination': str(destination), 'stage': str(stage),
                                      'state': state, 'uploaded_sha256': actual,
                                      'installed_sha256': installed}))
""" % (stage, hashes)
        output = service._execute("python3 -c " + shlex.quote(command), timeout=60)
        result["install_output"] = output
        result["install"] = json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                                             if line.startswith("SDK_INSTALL_JSON=")))
        result["sdk_validation"] = install_vendor.probe_sdk(service)
        api = result["sdk_validation"].get("api_results", {})
        dependencies = all(result["sdk_validation"][name]["exit_code"] == 0 and
                           "not found" not in result["sdk_validation"][name]["stdout"]
                           for name in ("libTSH.so", "libTSCANApiOnLinux.so"))
        result["passed"] = (dependencies and api.get("scan_status") == 0 and
                            api.get("connect_status") == 0 and api.get("disconnect_status") == 0 and
                            api.get("finalized") is True)
    except Exception as exc:
        result["error"] = dict(type=type(exc).__name__, message=str(exc))
    finally:
        service.close()
        (HERE / "sdk_install.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run(getpass.getpass("SSH password: "))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
