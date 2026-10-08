# SimRT Linux Target for MATLAB R2024b

The current workflow generates C code and compiles a Linux x86-64 executable
**locally on Windows**. Ubuntu receives a verified deployment package over SSH
and runs the model independently. It does not compile the model.

Start with the [new-machine deployment guide](../../docs/NEW_MACHINE_DEPLOYMENT.md),
[architecture and source guide](../../docs/ARCHITECTURE.md), and
[build workflow](../../docs/TOOLCHAIN.md).

## Requirements

- MATLAB R2024b, Simulink, Simulink Coder and Embedded Coder.
- Vehicle Network Toolbox for CAN Pack/Unpack, MATLAB XCP access and the full
  `verifySimRTEnvironment(Strict=true)` check.
- The local `toolchain/portable-linux-toolchain` package,
  containing Windows compiler tests/tools/scripts and a Linux x86-64 sysroot.
- Ubuntu x86-64 with SSH/SFTP, Python 3 and compatible runtime libraries.
- PREEMPT_RT, FIFO scheduling permissions and locked-memory allowance for
  real-time operation. User linger is also needed for boot-time user services.

The target uses the shared Embedded Coder Linux RTOS registration and
`coder.asap2`. Compilation requires the Windows portable toolchain.

## Register and Build

Run `installSimRTARKLibrary` and open `simrt_library`. The Library Browser has
one `SimRT` root with `Serial`, `Digital IO`, `EtherCAT`, `CAN`, and `TCP UDP`
sublibraries. Source models and block links use the SimRT identifiers.
The installer persists registration in the current user's
MATLAB environment. See the [ARK I/O guide](../../docs/ARK_IO.md), including the
target's currently missing iManager GPIO driver and hardware tests/validation limits.

Run from the complete workspace, adjusting both example paths and the target
address. Registration does not connect to the target.

```matlab
projectRoot = 'C:/work/SimRT';
addpath(fullfile(projectRoot, 'toolchain/simrt_linux_target'));
setupSimRTLinuxTarget(Persist=true);
verifySimRTEnvironment(ProbeTarget=false, Strict=true);
modelFile = fullfile(projectRoot, 'demos/Demo_XCP_Qt', 'models', ...
    'simrt_rt_single', 'simrt_rt_single.slx');
result = buildSimRTLocal(modelFile, Address='192.168.219.86');
disp(result.archive);
```

Alternatively open the saved model, apply `configureSimRTModel`, and press
Ctrl+B. `SimRT`, `ert.tlc`, `SimRT portable-linux-toolchain`, fixed
step 0.001 s and single-task execution are the current production settings.
See [TOOLCHAIN.md](../../docs/TOOLCHAIN.md) for the complete configuration.

After updating an existing installation, rerun `setupSimRTLinuxTarget` from the
current project, then apply `configureSimRTModel(..., Save=true)` to migrate and
save older model configurations. Confirm that `HardwareBoard` is `SimRT`.
The target directory, MATLAB packages/functions, model names and runtime
identifiers all use SimRT. Rebuild matching ELF/A2L/manifest packages after migration.

Successful builds publish only `<model>_local/<timestamp>.zip`. It contains one
timestamp folder with the matching ELF, A2L and JSON manifest. Verified
expanded results and the duplicate outer ELF are removed. Generated C code,
metadata and diagnostic reports remain in `<model>_ert_rtw/`.

The Qt APP internally extracts and verifies the ZIP, uploads it through SSH,
then starts the ELF. On the observation page, Online/Offline buttons use the
protocol and port declared in the loaded files. The project defaults are
UDP/5555 and TCP/17725; the current model uses UDP. Rebuild older-port models
to produce matching ELF/A2L/manifest ZIPs. Editing an old A2L or manifest alone
does not migrate the executable. The APP uses its nonempty Ubuntu host input
as the XCP destination before the ZIP/A2L address, so changing only the target
IP does not require a rebuild.

## Read the Implementation

| Entry | Responsibility |
| --- | --- |
| `setupSimRTLinuxTarget.m`, `registry/` | Target registration and hardware description |
| `configureSimRTModel.m`, `validateSimRTRealtimeModel.m` | Model configuration and build preconditions |
| `simrtPortableToolchain.m`, `simrtToolchainEnvironment.m` | Windows-hosted Linux compiler registration and environment |
| `+codertarget/+simrtlinuxssh/+internal/` | Code-generation and completed-build hooks |
| `buildSimRTLocal.m` | Programmatic local build |
| `tests/tools/scripts/enable_realtime_bundle.py`, `src/` | Generated-code adaptation and autonomous real-time scheduling |
| `src/xcp_ext_param_simrt_udp.c` | UDP parameters for the MathWorks XCP stack |
| `exportSimRTA2L.m`, `createSimRTASAP2Hierarchy.m` | Final-ELF addresses and source-model A2L groups |
| `packageSimRTArtifacts.m`, `unpackSimRTArtifacts.m` | Verified ZIP publication and extraction |
| `python/simrt_xcp/` | Shared XCP client services used by the Qt APP |
| `drivers/tc1013/` | CAN System objects, native adapter and vendor SDK |

The XCP protocol stack itself is supplied by MathWorks. The registry label
`XCP on TCP/IP` imports the shared stack; the generation hook replaces its
initializer with UDP configuration. Use the Qt APP or a MATLAB UDP XCP channel,
not the Simulink TCP Monitor & Tune connection. Only one XCP master should own
the target session at a time.

## Verification

`runLocalTests` runs the local MATLAB tests. Review their scope before running:
some integration tests perform real code generation and local compilation.
The [current evidence index](../../tests/validation/README.md) separates offline,
loopback and actual target validation. The [troubleshooting guide](../../docs/TROUBLESHOOTING.md)
maps failures to logs and implementation files.

Keep the generated-code metadata when re-exporting A2L for an existing ELF.
After discarding it, rebuild the saved model and produce a complete new ZIP;
do not mix a new A2L with an unrelated executable.
