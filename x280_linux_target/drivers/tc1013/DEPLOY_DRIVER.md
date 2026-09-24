# TC1013 Linux SDK preparation

The official vendor **Linux x86_64** SDK is included in `vendor/linux`, pinned
and documented in [vendor/SOURCE.md](vendor/SOURCE.md), with its MIT license.
The current package requires `libTSCANApiOnLinux.so` and `libTSH.so`.
`blf.so` is optional for older packages. Keep any additional `.so` or `.so.*`
dependencies in the same directory. Windows DLLs are not compatible.

## Prepare on Windows

From the workspace root:

```powershell
.\.venv\Scripts\python.exe x280_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir x280_linux_target\drivers\tc1013\vendor\linux --check
.\.venv\Scripts\python.exe x280_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir x280_linux_target\drivers\tc1013\vendor\linux --output C:\DataSave\tc1013-sdk-upload
```

The output must not already exist. The tool validates ELF64, little-endian,
x86_64, shared-library headers; it copies every sibling `.so`/`.so.*` library,
the preparation tool, this guide, available LICENSE/SOURCE.md notices, and a SHA256 manifest. Links are materialized
as regular files for SFTP compatibility. Library symlinks outside the source
directory are rejected; provide the complete vendor library directory.

## Upload and install

Upload the prepared directory with an SFTP client or OpenSSH `scp`:

```powershell
scp -r C:\DataSave\tc1013-sdk-upload zh@192.168.219.86:/home/zh/
```

Then run these commands in a terminal on the Linux target:

```sh
python3 /home/zh/tc1013-sdk-upload/prepare_driver.py --sdk-dir /home/zh/tc1013-sdk-upload --check
python3 /home/zh/tc1013-sdk-upload/prepare_driver.py --sdk-dir /home/zh/tc1013-sdk-upload --output /home/zh/.local/lib/tscan
python3 /home/zh/.local/lib/tscan/prepare_driver.py --sdk-dir /home/zh/.local/lib/tscan --check
```

The model's default CANSetup `DriverDirectory` is `/home/zh/.local/lib/tscan`. An existing
installation is never overwritten. For an upgrade, prepare a new directory
(for example `/home/zh/.local/lib/tscan-v2`) and explicitly select it in CANSetup,
then rebuild the model. The Qt app uploads model ELF/A2L/JSON payloads;
install the vendor SDK separately with the commands above.

The runtime opens the two required libraries and optional `blf.so` from this directory and reports
dynamic-loader or missing-symbol errors in the target log. It does not fall
back to simulated CAN. Linux must also provide the vendor-required `libusb`
runtime and suitable USB device permissions. Use the vendor's device-specific
permission rules rather than granting broad access to all USB devices.

For vendor packages with additional shared-library dependencies, inspect the
installed vendor library on Linux:

```sh
LD_LIBRARY_PATH=/home/zh/.local/lib/tscan${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} ldd /home/zh/.local/lib/tscan/libTSCANApiOnLinux.so
```

Resolve every `not found` entry before starting the model. Additional libraries
must be discoverable by the model process through the vendor library's RPATH,
the system linker configuration, or `LD_LIBRARY_PATH` set before launching the
model. Copying extra libraries alone does not change the Qt launch environment.

The bundled SDK also searches relative to the current working directory during
initialization. The CAN adapter saves the process directory, enters DriverDirectory
for initialization/configuration, and restores the directory before normal model
execution. No directory change occurs in send/receive step calls.

## Verified target installation

The two libraries and their license/source notices are installed at
`/home/zh/.local/lib/tscan` on `192.168.219.86`. SHA256 verification, dependency
checks, enumeration, connect and disconnect passed for serial
`37AFCA2612ADBF35` (USB VID/PID `5453:0001`). Evidence and the repeatable setup
script are in `validation/tc1013_can_20260919/install_vendor.*` at the workspace root.

Only this adapter's verified USB node was assigned to the existing `plugdev`
group, retaining mode `0664`; user `zh` is a member. No broad USB permission rule
was installed. Recheck node permissions after unplugging or rebooting.

## What the check proves

Preparation and `--check` read files only. They do not contact the target,
load vendor code, initialize a CAN adapter, or transmit CAN frames. A prepared
manifest also detects missing, additional, modified, or truncated libraries
after upload.

ELF header compatibility does not prove that transitive dependencies, required
SDK symbols, Linux/glibc versions, USB permissions, firmware, or physical CAN
wiring are correct. Those require validation with the actual Linux SDK and
adapter. Actual model/hardware verification is recorded separately in
`validation/tc1013_can_20260919/README.md`.
