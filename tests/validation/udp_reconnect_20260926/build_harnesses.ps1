$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot/../..").Path
$matlabRoot = 'C:/Program Files/MATLAB/R2024b'
$nativeCompiler = "$projectRoot/tools/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang.exe"
$includePaths = @(
    "$matlabRoot/extern/include",
    "$matlabRoot/simulink/include",
    "$matlabRoot/toolbox/rtw/accel/accelTemplateFolder",
    "$matlabRoot/toolbox/coder/rtiostream/src",
    "$matlabRoot/toolbox/coder/rtiostream/src/rtiostreamtcpip",
    "$matlabRoot/toolbox/coder/xcp/src/target/server/include",
    "$matlabRoot/toolbox/coder/xcp/src/target/server/common",
    "$matlabRoot/toolbox/coder/xcp/src/target/server/platform/include",
    "$matlabRoot/toolbox/coder/xcp/src/target/server/platform/default"
)
$compileOptions = @('-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-DWIN32')
$compileOptions += $includePaths | ForEach-Object { "-I$_" }
$harness = "$projectRoot/simrt_linux_target/tests/udp_reconnect_harness.c"
& $nativeCompiler @compileOptions "$matlabRoot/toolbox/coder/rtiostream/src/rtiostreamtcpip/rtiostream_tcpip.c" $harness '-lws2_32' '-o' "$PSScriptRoot/udp_vendor_baseline.exe"
if ($LASTEXITCODE -ne 0) { throw 'Vendor baseline compile failed.' }
& $nativeCompiler @compileOptions "$projectRoot/simrt_linux_target/src/simrt_rtiostream_udp.c" "$projectRoot/simrt_linux_target/src/simrt_xcp_status.c" $harness '-lws2_32' '-o' "$PSScriptRoot/udp_fixed.exe"
if ($LASTEXITCODE -ne 0) { throw 'Project adapter compile failed.' }
$linuxCompiler = "$projectRoot/portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe"
$linuxOptions = @('-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-pie', '-no-pie', '-pthread')
$linuxOptions += "-I$projectRoot/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single_ert_rtw"
$linuxOptions += $includePaths | Where-Object { $_ -notlike '*accelTemplateFolder' } | ForEach-Object { "-I$_" }
& $linuxCompiler @linuxOptions "$matlabRoot/toolbox/coder/rtiostream/src/rtiostreamtcpip/rtiostream_tcpip.c" $harness '-o' "$PSScriptRoot/udp_vendor_baseline.elf"
if ($LASTEXITCODE -ne 0) { throw 'Linux baseline compile failed.' }
& $linuxCompiler @linuxOptions "$projectRoot/simrt_linux_target/src/simrt_rtiostream_udp.c" "$projectRoot/simrt_linux_target/src/simrt_xcp_status.c" $harness '-o' "$PSScriptRoot/udp_fixed.elf"
if ($LASTEXITCODE -ne 0) { throw 'Linux adapter compile failed.' }
