# SimRT Linux Target for MATLAB R2024b

The current workflow generates C code and compiles a Linux x86-64 executable
**locally on Windows**. Ubuntu receives a verified deployment package over SSH
and runs the model independently. It does not compile the model.

Start with the [new-machine deployment guide](../docs/NEW_MACHINE_DEPLOYMENT.md),
[architecture and source guide](../docs/ARCHITECTURE.md), and
[build workflow](../docs/TOOLCHAIN.md).

## Requirements

- MATLAB R2024b, Simulink, Simulink Coder and Embedded Coder.
- Vehicle Network Toolbox for CAN Pack/Unpack, MATLAB XCP access and the full
  `verifyX280Environment(Strict=true)` check.
- The local `portable-linux-toolchain/portable-linux-toolchain` package,
  containing Windows compiler tools and a Linux x86-64 sysroot.
- Ubuntu x86-64 with SSH/SFTP, Python 3 and compatible runtime libraries.
- PREEMPT_RT, FIFO scheduling permissions and locked-memory allowance for
  real-time operation. User linger is also needed for boot-time user services.

The current build does not call the Raspberry Pi remote-build APIs or GCC
on the target. A completely clean R2024b installation without that historical
support package has not been independently tested. Legacy remote-build helpers
remain for historical reproduction, not as standard deployment entry points.

## Register and Build

Run from the complete workspace, adjusting both example paths and the target
address. Registration does not connect to the target.

```matlab
projectRoot = 'C:/work/X280';
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget(Persist=true);
verifyX280Environment(ProbeTarget=false, Strict=true);
modelFile = fullfile(projectRoot, 'Demo_XCP_Qt', 'models', ...
    'x280_rt_single', 'x280_rt_single.slx');
result = buildX280Local(modelFile, Address='192.168.219.86');
disp(result.archive);
```

Alternatively open the saved model, apply `configureX280Model`, and press
Ctrl+B. `SimRT`, `ert.tlc`, `X280 portable-linux-toolchain`, fixed
step 0.001 s and single-task execution are the current production settings.
See [TOOLCHAIN.md](../docs/TOOLCHAIN.md) for the complete configuration.

After updating an existing installation, rerun `setupX280LinuxTarget` from the
current project, then apply `configureX280Model(..., Save=true)` to migrate and
save older model configurations. Confirm that `HardwareBoard` is `SimRT`.
The `x280_linux_target` directory, MATLAB package/function names and the
`X280 portable-linux-toolchain` compiler name remain unchanged.

Successful builds publish only `<model>_local/<timestamp>.zip`. It contains one
timestamp folder with the matching ELF, A2L and JSON manifest. Verified
expanded results and the duplicate outer ELF are removed. Generated C code,
metadata and diagnostic reports remain in `<model>_ert_rtw/`.

The Qt APP internally extracts and verifies the ZIP, uploads it through SSH,
then starts the ELF. On the observation page, Online/Offline buttons use the
protocol and port declared in the loaded files. The default is UDP/17725.

## Read the Implementation

| Entry | Responsibility |
| --- | --- |
| `setupX280LinuxTarget.m`, `registry/` | Target registration and hardware description |
| `configureX280Model.m`, `validateX280RealtimeModel.m` | Model configuration and build preconditions |
| `x280PortableToolchain.m`, `x280ToolchainEnvironment.m` | Windows-hosted Linux compiler registration and environment |
| `+codertarget/+x280linuxssh/+internal/` | Code-generation and completed-build hooks |
| `buildX280Local.m` | Programmatic local build |
| `tools/enable_realtime_bundle.py`, `src/` | Generated-code adaptation and autonomous real-time scheduling |
| `src/xcp_ext_param_x280_udp.c` | UDP parameters for the MathWorks XCP stack |
| `exportX280A2L.m`, `createX280ASAP2Hierarchy.m` | Final-ELF addresses and source-model A2L groups |
| `packageX280Artifacts.m`, `unpackX280Artifacts.m` | Verified ZIP publication and extraction |
| `python/x280_xcp/` | Shared XCP client services used by the Qt APP |
| `drivers/tc1013/` | CAN System objects, native adapter and vendor SDK |

The XCP protocol stack itself is supplied by MathWorks. The registry label
`XCP on TCP/IP` imports the shared stack; the generation hook replaces its
initializer with UDP configuration. Use the Qt APP or a MATLAB UDP XCP channel,
not the Simulink TCP Monitor & Tune connection. Only one XCP master should own
the target session at a time.

## Verification

`runLocalTests` runs the local MATLAB tests. Review their scope before running:
some integration tests perform real code generation and local compilation.
The [current evidence index](../validation/README.md) separates offline,
loopback and actual target validation. The [troubleshooting guide](../docs/TROUBLESHOOTING.md)
maps failures to logs and implementation files.

Keep the generated-code metadata when re-exporting A2L for an existing ELF.
After discarding it, rebuild the saved model and produce a complete new ZIP;
do not mix a new A2L with an unrelated executable.
