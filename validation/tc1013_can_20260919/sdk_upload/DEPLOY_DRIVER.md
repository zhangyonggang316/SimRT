# TC1013 Linux SDK preparation

Obtain the vendor **Linux x86_64** SDK. The directory supplied so far contains
Windows DLLs only; renaming a DLL to `.so` does not make it compatible.
The library directory must contain `libTSCANApiOnLinux.so`, `libTSH.so`, and
`blf.so`. Keep any additional `.so` or `.so.*` dependencies in the same directory.

## Prepare on Windows

From the workspace root, substitute the actual vendor Linux library directory:

```powershell
.\.venv\Scripts\python.exe x280_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir C:\Vendor\TSCAN_Linux\lib --check
.\.venv\Scripts\python.exe x280_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir C:\Vendor\TSCAN_Linux\lib --output C:\DataSave\tc1013-sdk-upload
```

The output must not already exist. The tool validates ELF64, little-endian,
x86_64, shared-library headers; it copies every sibling `.so`/`.so.*` library,
the preparation tool, this guide, and a SHA256 manifest. Links are materialized
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

The runtime opens the three named libraries from this directory and reports
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

## What the check proves

Preparation and `--check` read files only. They do not contact the target,
load vendor code, initialize a CAN adapter, or transmit CAN frames. A prepared
manifest also detects missing, additional, modified, or truncated libraries
after upload.

ELF header compatibility does not prove that transitive dependencies, required
SDK symbols, Linux/glibc versions, USB permissions, firmware, or physical CAN
wiring are correct. Those require validation with the actual Linux SDK and
adapter. No vendor libraries are bundled in this project.
