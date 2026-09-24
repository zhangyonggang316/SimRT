# 新上位机与 Linux 下位机部署指南

本指南对应 2026-09-19 工程源码。目标是从新机器完成本地模型构建、ZIP 加载、SSH 部署、XCP 观测和标定，并能够定位安装与迁移问题。本轮只核对源码、现有验收记录和官方文档，没有在另一台全新机器实际安装系统。

从 GitHub 克隆时，先阅读[源码获取与依赖准备](SOURCE_CHECKOUT.md)：下文完整工作区中的预编译 APP、编译器、Python 环境与生成元数据并未全部随 Git 分发，需要在新机器准备。

工程标准路线为：**Windows 上的 MATLAB/Simulink 生成 C 代码，Windows 上的 Linux 交叉编译器生成 ELF，Embedded Coder 根据同一个 ELF 导出 A2L，打包 ELF/A2L/JSON 为 ZIP；Qt APP 解包后通过 SSH/SFTP 部署到 Linux，Linux 自主运行模型。** Linux 不编译模型，不安装 Windows 交叉编译工具链，也不需要 MATLAB。

技术实现和源码阅读另见 [技术路线](ARCHITECTURE.md)；运行期故障分析见 [故障排查](TROUBLESHOOTING.md)。本文中的 `D:/X280Project`、`192.168.219.86`、`zh` 是路径、地址、用户名示例，必须替换为实际值。Windows 命令在 PowerShell 中执行，Linux 命令在目标机终端中执行，MATLAB 命令在 MATLAB 命令窗口执行。

## 1. 先确定机器用途

| 用途 | 必须准备 | 不需要安装 |
| --- | --- | --- |
| 仅运行已交付 APP、部署已有模型 | Windows x64，整个 `Demo_XCP_Qt` 目录，可访问目标机的网络 | MATLAB、Python、Qt 开发包、任何编译器 |
| 开发模型并生成新 ZIP | Windows x64，MATLAB R2024b 及下表工具箱，`x280_linux_target`，SLX，完整 Linux 交叉工具链 | Linux 原生 GCC、目标机在线连接 |
| 修改或重新打包 Qt APP | 完整工程，Python 3.9.10 x64，固定 Python 依赖，原生 DLL；修改 DLL 时另需 LLVM-MinGW | MATLAB Engine；普通 APP 测试不需要 MATLAB |
| Linux 运行模型 | x86-64 Linux、兼容 glibc、OpenSSH/SFTP、Python 3、PREEMPT_RT、实时权限 | MATLAB、Simulink、模型代码生成工具、Windows GCC |
| Linux 运行 CAN 模型 | 上述运行环境，加 TC1013 Linux SDK、libusb、USB 权限、正确接线 | Windows CAN DLL |

APP 的 C++ 数据核心和 Linux 模型使用两套不同的工具链，不能混用：

| 工具链 | 主机 | 输出 | 默认位置 |
| --- | --- | --- | --- |
| GCC 7.5.0 / `linux-gcc.exe` | Windows | Linux x86-64 `.elf` | `portable-linux-toolchain/portable-linux-toolchain/` |
| LLVM-MinGW 20250709 / Clang 20.1.8 | Windows | Windows x64 `xcp_core.dll` | `tools/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/` |

## 2. 已验证基线和新机边界

| 项目 | 工程已有验证基线 | 新机处理 |
| --- | --- | --- |
| MATLAB | R2024b Update 6，`24.2.0.2923080` | 优先同版本；注册函数明确拒绝非 R2024b |
| 模型工具箱 | Simulink、Simulink Coder、Embedded Coder、Vehicle Network Toolbox | 安装并激活许可证；安装器要求的依赖一并安装 |
| 其他 MATLAB 产品 | 原开发机还装有 MATLAB Coder；CAN 模型测试使用 Simulink Test | 以实际模型/测试所用产品为准，不能把本机已安装清单当成全部最小依赖 |
| Windows APP 开发 | Python 3.9.10 x64、PySide6-Essentials 6.8.3、shiboken6 6.8.3 | `build.ps1` 检查固定版本；升级应另做兼容性验收 |
| XCP、SSH、绘图 | pyxcp 0.22.32、Paramiko 4.0.0、NumPy 2.0.2、Matplotlib 3.9.4 | 由 `requirements.txt` 和 `constraints-archive.txt` 安装 |
| APP 打包 | PyInstaller 6.22.2 | 交付的是 onedir 目录，不是单个 EXE |
| Linux | X280、Ubuntu 22.04.5、`5.15.129-rt67-intel-ese-standard-lts-rt` | 其他内核/发行版必须重新验证 ABI、实时权限、延迟与设备驱动 |
| ELF | 小端 ELF64、x86-64、固定地址非 PIE；sysroot 的 glibc 基线为 2.27 | 最终 ELF 的加载器、依赖和符号版本仍需检查 |
| CAN | TC1013，经典 CAN 500 kbit/s；CAN FD 500/2000 kbit/s | 设备、固件、SDK、USB 权限与物理总线需要新机验收 |

已有结果见 [APP 与本地编译验证](../validation/app12_app13_20260919/README.md) 和 [CAN 真机验证](../validation/tc1013_can_20260919/README.md)。这些结果证明对应环境和文件已经测试，不表示任意新硬件、任意负载均满足 1 ms 最坏时延。

## 3. 新 Windows 机器：文件布局与迁移

建议放在可写、较短的 ASCII 路径，例如 `D:/X280Project`。普通含空格路径在交叉工具链中已有测试，复杂非 ASCII 路径未作为完整工具链验收基线。

```text
D:/X280Project/
  Demo_XCP_Qt/                 正式 APP、主模型 SLX、默认 ZIP
  x280_linux_target/           MATLAB 硬件注册、构建钩子、运行时、CAN 库
  qt_xcp_host/                 Qt APP 和共享服务源码
  portable-linux-toolchain/
    portable-linux-toolchain/
      toolchain/bin/linux-gcc.exe
      toolchain/x86_64-linux/  sysroot，必须完整保留
  tools/                      验证脚本、可选开发工具
  docs/
  requirements.txt
  .python/3.9.10/              源码开发时安装的 Python
  .venv/                      在新机器、新路径重新创建
```

迁移时逐项处理：

1. 拷贝源码、SLX、交付 ZIP、两套必要工具链及第三方许可证。只使用 APP 的机器只需拷贝完整 `Demo_XCP_Qt`。
2. 不把旧 `.venv` 当成便携环境。其 `pyvenv.cfg` 和启动脚本可能保存旧解释器的绝对路径。工程原环境曾指向 `01AI ToolLinux`，新机器应在当前路径重新创建。Python 官方也将虚拟环境定位为可重建的项目环境，见 [venv 文档](https://docs.python.org/3.9/library/venv.html)。
3. 重新注册 MATLAB 硬件和工具链。`registry/x280_portable_toolchain.mat` 会记录当前工具链位置，不能只复制旧注册缓存。
4. 更新 `Demo_XCP_Qt/demo.json` 的 SSH 地址、用户名和相对 ZIP 路径；模型包内还有 XCP 地址，见第 5 节。
5. CAN 模型中的 `DriverDirectory` 是 Linux 绝对路径，换用户或目录后必须修改模型并重新编译。
6. `.vscode/mcp.json`、用户级 MATLAB path 和辅助工具配置中的旧绝对路径应单独更新。MCP/技能工具不是模型构建或 APP 运行的必要组件；保留 `--initialize-matlab-on-startup=false`，不要把打开工程变成启动 MATLAB 的动作。
7. SSH 记忆密码保存在 `%LOCALAPPDATA%/X280XcpHost/ssh_credentials.dpapi`，绑定原 Windows 用户。新机器重新输入凭据，不复制该密文文件作为部署步骤。

工具链来源及逐文件 SHA-256 见 [portable 工具链说明](../portable-linux-toolchain/portable-linux-toolchain/README.md) 与同目录 `manifest.json`。该包从既有安装提取，不提供对应全部上游源码；跨组织分发前应保留并核对随包许可证，不能把它描述为从 MATLAB 自动下载的标准支持包。

## 4. 新 Windows 机器：MATLAB 和本地工具链

### 4.1 安装与产品检查

安装 MATLAB R2024b 和 Simulink、Simulink Coder、Embedded Coder、Vehicle Network Toolbox。Vehicle Network Toolbox 提供 CAN Pack/Unpack、CAN FD Pack/Unpack 及 MATLAB XCP 接口；当前 `verifyX280Environment(Strict=true)` 同时检查 `xcpA2L` 和 `xcpChannel`，因此按本工程完整验收路径安装该工具箱。

当前标准注册/构建代码使用 MATLAB 的 `codertarget`、Linux RTOS 公共文件和 `coder.asap2`，没有调用树莓派远程编译接口。历史开发机曾安装 Raspberry Pi 支持包，但尚未在完全未安装该支持包的独立 R2024b 环境做隔离验收。遇到 `codertarget` 或 Linux RTOS 注册文件缺失时，应根据错误核对 R2024b/Embedded Coder 安装，不能切换回目标机 GCC 编译来绕过错误。

在 MATLAB 中检查：

```matlab
version
version('-release')
ver
which slbuild -all
which coder.asap2.export -all
which xcpA2L -all
which xcpChannel -all
```

`which` 找到函数说明文件已安装，不代表调用时一定能签出许可证。以首次真实构建和许可证错误信息为准。

### 4.2 检查交叉编译器

在 PowerShell 中切到实际工程根目录：

```powershell
Set-Location 'D:/X280Project'
$toolchain = Join-Path $PWD 'portable-linux-toolchain/portable-linux-toolchain'
& "$toolchain/scripts/invoke-tool.ps1" -Tool gcc -ToolArguments @('--version')
& "$toolchain/scripts/invoke-tool.ps1" -Tool gcc -ToolArguments @('-dumpmachine')
```

应能运行 GCC 7.5.0，目标为 `x86_64-linux`。必须保留整个工具链目录；只复制 `linux-gcc.exe` 会缺少编译器内部程序、头文件和链接库。不需要把交叉编译器或 LLVM-MinGW 加到全局 PATH。

### 4.3 注册硬件与工具链

```matlab
projectRoot = 'D:/X280Project';
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget(Persist=true);
report = verifyX280Environment(ProbeTarget=false, Strict=true);
disp(report)
```

期望硬件为 `SimRT`，工具链为 `X280 portable-linux-toolchain`，硬件类型为 `Intel->x86-64 (Linux 64)`。Ctrl+B 在 Windows 本地完成代码生成与交叉编译；SSH 由 APP 在部署和运行管理阶段使用。

**已有工程升级名称时也需要重新注册。** 先保存正在编辑的模型，然后在当前工程路径执行上面的注册命令。对自己的旧模型，使用第 5 节的 `configureX280Model(..., Save=true)` 更新并保存配置，再检查 `get_param('实际模型名', 'HardwareBoard')` 的结果为 `SimRT`。配置函数还会应用工程的构建与实时运行参数，修改前保留自己的模型副本。若下拉框仍显示旧注册项，先核对 `which setupX280LinuxTarget -all`，移除旧工程路径后重新注册并重新打开配置窗口；必要时重启 MATLAB。

此次变更只统一注册显示名称。`x280_linux_target` 目录、MATLAB 函数和包名、模型文件名、环境变量及 `X280 portable-linux-toolchain` 工具链名称继续沿用，因此不要根据显示名称手工重命名这些路径或接口。历史 ZIP、构建回执和测试日志保留生成时的记录；新模型构建会记录当前配置。

若工具链不在默认位置，在**同一 MATLAB 会话**注册前指定包根目录：

```matlab
setenv('X280_TOOLCHAIN_ROOT', 'E:/Toolchains/portable-linux-toolchain');
setupX280LinuxTarget(Persist=true);
```

此目录下必须直接存在 `toolchain/bin/linux-gcc.exe`。`setenv` 只影响当前 MATLAB 及子进程；每次使用外部工具链前都要设置，或由工作站管理员配置同名用户环境变量。迁移后用 `which setupX280LinuxTarget -all` 核对优先路径。`Persist=true` 若因 `savepath` 权限失败，本会话仍已注册；可每次显式 `addpath` 和注册，无需因此用管理员身份长期运行 MATLAB。

### 4.4 可选 CAN 模型库

```matlab
locations = setupX280CANLibrary;
sl_refresh_customizations;
open_system(locations.Library);
open_system(locations.TestModel);
```

`setupX280CANLibrary` 创建官方 CAN/CAN FD bus 类型并添加库路径，不会连接 USB 或 Linux。Library Browser 中的模块库名称为 `X280 Linux TC1013 CAN`，模型硬件名称为 `SimRT`。只有需要 CAN 模型时才执行本节。

## 5. 首次本地模型构建

先以主模型验证编译链，再部署 CAN 模型。模型配置会保存 SLX，实验修改宜使用自己的工作副本。

```matlab
projectRoot = 'D:/X280Project';
modelFile = fullfile(projectRoot, 'Demo_XCP_Qt', 'models', ...
    'x280_rt_single', 'x280_rt_single.slx');
open_system(modelFile);
configureX280Model('x280_rt_single', Address='192.168.219.86', Save=true);
validateX280RealtimeModel('x280_rt_single');
slbuild('x280_rt_single');
build = RTW.getBuildDir('x280_rt_single');
record = jsondecode(fileread(fullfile(build.BuildDirectory, 'x280_local_build.json')));
disp(record.archive)
disp(record.archive_sha256)
```

在 Simulink 中按 Ctrl+B 与上述 `slbuild` 走同一构建入口；也可使用 `result = buildX280Local(modelFile, Address='192.168.219.86')`。无须输入 SSH 密码，目标机可以关机。

主模型保持固定步长 `0.001 s`、单任务、C、`ert.tlc`、`ExtMode=on`、参数 Tunable。不要仅改 Linux 环境变量来把其他周期代码当作 1 ms 模型运行。

构建成功后：

```text
x280_rt_single_local/
  <时间戳>.zip
      <时间戳>/
          x280_rt_single.elf
          x280_rt_single.a2l
          x280_rt_single.xcp-manifest.json
```

时间戳展开目录和模型外层重复 ELF 会被删除。生成 C、Makefile、SLX 快照和检查报告位于 `_ert_rtw/x280_build_evidence/`；它们用于调试，不是给 APP 上传的内容。若已删除对应代码生成元数据，需要重新导出 A2L 或定位同轮代码时应重新构建，不用旧报告中的绝对路径猜测当前产物。本次整理保留了这些生成元数据。

A2L 由 Embedded Coder 的 `coder.asap2` 生成，`MapFile` 使用刚链接的最终 ELF。工具支持用 ELF 中的符号补全 ECU 地址，见 [MathWorks ASAP2 导出说明](https://www.mathworks.com/help/ecoder/ref/coder.asap2.export.html)。工程另从本轮代码描述符的 SID 父链建立模型层级，写入标准 A2L GROUP/SUB_GROUP。不能把其他轮次 ELF 与旧 A2L 拼成一包。

**目标 IP 迁移要同时处理 SSH 与 XCP。** APP 按包内 JSON/A2L 自动识别协议、端口和主机地址；只有文件没有主机地址时才回退到 SSH 主机。只修改 `demo.json` 的 `host` 不会覆盖包中已有的旧 XCP 地址。标准方法是用新 `Address` 重新构建并选中新 ZIP，再更新 `demo.json` 的 `archive` 相对路径。不要手改 A2L 后保留原 SHA-256。

## 6. 新 Windows 机器：APP 使用与源码环境

### 6.1 只运行交付 APP

运行 `Demo_XCP_Qt/START_DEMO.cmd`。保留完整 `app/_internal/`、Qt 平台插件、原生 `xcp_core.dll` 和随包第三方资料。启动 APP 不会自动连接 SSH，也不会自动打开 MATLAB。打开 MATLAB SDI 属于用户显式触发的另一项操作。

### 6.2 从源码开发

已有 Python 安装介质位于 `tools/python-3.9.10-amd64.exe`；安装 64 位完整版本到工程 `.python/3.9.10`，或使用受控的同版本解释器创建工程 `.venv`。不要选择不含完整标准库/venv 的嵌入式发行包。已有 `.venv` 的同机工程不需要为阅读源码重建；这里只针对新机器或路径迁移。

在新工程根目录执行：

```powershell
& ./.python/3.9.10/python.exe --version
& ./.python/3.9.10/python.exe -m venv .venv
& ./.venv/Scripts/python.exe -m pip install 'pip==25.2'
& ./.venv/Scripts/python.exe -m pip install -r ./requirements.txt
& ./.venv/Scripts/python.exe -m pip check
```

工程包含版本约束，未包含完整离线 wheel 仓库。需要联网安装；离线部署时先在**相同 Windows x64、Python 3.9 环境**下载所需包，再转移到新机：

```powershell
& ./.venv/Scripts/python.exe -m pip download -r ./requirements.txt --dest ./wheelhouse
# 将已验证的 wheelhouse 转移到离线机器后执行：
& ./.venv/Scripts/python.exe -m pip install --no-index --find-links ./wheelhouse -r ./requirements.txt
```

检查下载结果是否包含需要的源码包及构建依赖；本工程没有承诺无网络的首次 pip 安装。离线新机若还需升级 pip，也应另行准备对应 pip wheel。Python 3.9 是复现旧基线，官方已将该分支标为不再支持；长期版本升级需同时修改锁定依赖和构建检查，并重新做回归，不能单独替换解释器。

PySide6-Essentials 提供本项目使用的 Qt Core/GUI/Widgets，不必安装 PySide6-Addons，见 [Qt 分包说明](https://doc.qt.io/qtforpython-6/package_details.html)。

### 6.3 原生 DLL、测试和 EXE 打包

工程已有 `qt_host/native_bin/xcp_core.dll` 可用于源码运行。修改 C++ 或需要从源码重建时，准备 [LLVM-MinGW 20250709 官方发布包](https://github.com/mstorsjo/llvm-mingw/releases/tag/20250709)：`llvm-mingw-20250709-ucrt-x86_64.zip`。项目记录的 SHA-256 为 `82babcd6aae4dc3606e8e0471d816989c384b4bf86a139f184a8b4a1b2c2758d`，解压后布局应符合第 1 节。

```powershell
& ./qt_xcp_host/build_native.ps1
& ./qt_xcp_host/run.ps1
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_tests.py --output ./validation/new_machine/tests
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_visual.py --output ./validation/new_machine/visual
```

非默认工具链位置可用 `build_native.ps1 -Compiler 'E:/LLVM/bin/clang++.exe'`，但编译器必须能生成 Windows x64 C++17 DLL；Linux GCC 不适用。源码 APP 由 `run.ps1` 注入本项目 Python 模块路径，不依赖全局安装同名包。

发布前关闭旧 APP，再构建并生成新的交付目录：

```powershell
& ./qt_xcp_host/build.ps1
& ./qt_xcp_host/package_demo.ps1 -OutputDirectory ./Demo_XCP_Qt_next `
    -QtValidationDirectory ./validation/new_machine/tests
```

已确认原生 DLL 与源码一致时，`build.ps1 -SkipNativeBuild` 可跳过 DLL 重编译。打包器使用已安装依赖，不自动运行 pip。`package_demo.ps1` 拒绝覆盖正式交付目录，仅读取正式基线的 SLX 和所选 ZIP；验证暂存 EXE 启动、ZIP 加载、网络回环和目标验收后，再发布新目录。不要把构建成功等同于真机验收完成。

## 7. 新 Linux 下位机：运行环境

### 7.1 操作系统、用户和 SSH

准备 x86-64、glibc Linux。与基线最接近的是 Ubuntu 22.04 系列；ARM、Alpine/musl 不能直接运行本工程 ELF。创建一个具有自己主目录的普通模型用户，确保能通过 SSH 登录，例为 `zh`。APP 当前界面以用户名/密码登录为主，系统的 SSH 认证策略需允许该用户采用实际使用的方法。

Ubuntu 安装示例：

```bash
sudo apt update
sudo apt install openssh-server python3 libstdc++6 libgcc-s1
sudo systemctl enable --now ssh
uname -m
python3 --version
systemctl status ssh --no-pager
```

安装方法依据 [Ubuntu OpenSSH 指南](https://ubuntu.com/server/docs/how-to/security/openssh-server/)。目标机不需要安装 Qt、pyxcp 或 Paramiko，远端管理代码使用系统 Python 标准库。

Windows 可先做 SSH 端口检查：

```powershell
Test-NetConnection 192.168.219.86 -Port 22
```

在目标用户主目录中建立专用工作根目录，例如 `mkdir -p "$HOME/MATLAB_ws"`。APP 的相对路径 `MATLAB_ws/project_run` 会相对于 SSH 用户主目录解析。APP 禁止向主目录本身、主目录外、含 `..` 或符号链接的路径部署；不要使用 `/tmp` 或 `/opt` 作为 APP 的默认模型目录。

### 7.2 实时内核

模型运行时默认要求 `/sys/kernel/realtime` 为 `1`。安装了普通低延迟内核、仅提高进程优先级或能打开 UDP 端口，都不等于通过该要求。

```bash
uname -r
cat /sys/kernel/realtime
grep -E 'CONFIG_PREEMPT_RT=|CONFIG_HIGH_RES_TIMERS=' "/boot/config-$(uname -r)"
```

新机应由系统管理员选择与实际 CPU/发行版匹配的 PREEMPT_RT 内核，保留可回退启动项，重启后再检查。对于 Ubuntu 22.04，官方 Ubuntu Pro 路线提供 `sudo pro attach`、`sudo pro enable realtime-kernel`，适用前提与兼容服务见 [Ubuntu 官方安装说明](https://ubuntu.com/pro-client/docs/en/v35/howtoguides/enable_realtime_kernel/)。本文不把现有 X280 的 Intel 内核包名当作所有新机器通用安装命令，也不要求新机器复制旧 GRUB 配置。

运行时虽有 `X280_RT_REQUIRE_KERNEL=0` 诊断开关，但关闭检查不满足实时验收。不要把它作为正式部署修复方法。

### 7.3 分别配置 SSH 会话和 systemd 用户服务的实时额度

运行时创建 FIFO 优先级 40 的模型线程，并调用 `mlockall(MCL_CURRENT | MCL_FUTURE)`。需要允许该用户设置实时优先级并锁定足够内存。当前运行时可配置优先级为 1..49，默认 CPU 是进程可用亲和掩码中的最后一个 CPU；旧机器的 CPU 7 不是新机器固定要求。

管理员可以为实际模型用户使用以下配置范例。先检查既有文件；将示例用户名换成实际用户，保留原系统的其它策略。额度 1 GiB 是已有环境配置值，并非所有模型的最低/最高需求。

文件 `/etc/security/limits.d/90-pyxcp-realtime.conf`：

```text
zh - rtprio 80
zh - memlock 1048576
```

`memlock` 在 PAM limits 中以 KiB 表示，配置作用于新登录会话；见 [Linux-PAM limits.conf 原始手册](https://github.com/linux-pam/linux-pam/blob/master/modules/pam_limits/limits.conf.5.xml)。核对 SSH 的 PAM 会话实际加载 `pam_limits.so`，重新登录后执行 `ulimit -r` 和 `ulimit -l`，不要只检查文本文件存在。

自启走 systemd 用户管理器，不一定继承交互 SSH 的额度。先查 `id -u zh`；假设返回 `1000`，管理员为 `/etc/systemd/system/user@1000.service.d/90-pyxcp-realtime.conf` 配置：

```ini
[Service]
LimitRTPRIO=80
LimitMEMLOCK=1073741824
```

此处锁内存单位为字节。执行 `sudo systemctl daemon-reload` 后，在维护窗口重启机器，或按系统管理流程重启该用户管理器；后者会影响该用户其它服务。仅改模型用户服务里的 `LimitRTPRIO` 不能突破用户管理器已继承的硬上限，见 [systemd.exec 原始手册](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)。

核对实际生效状态：

```bash
ulimit -r
ulimit -l
systemctl show "user@$(id -u).service" -p LimitRTPRIO -p LimitMEMLOCK
python3 -c 'import os,resource; print("cpu", sorted(os.sched_getaffinity(0))); print("rtprio", resource.getrlimit(resource.RLIMIT_RTPRIO)); print("memlock", resource.getrlimit(resource.RLIMIT_MEMLOCK))'
```

不要为解决权限问题长期以 root 运行模型，或对所有用户授予无限实时额度。工程的 `tools/prepare_realtime_target.py` 是历史专用配置脚本，**硬编码 `zh`，并要求该用户具有非交互 sudo**；它不是任意新用户的一键安装器。新机按上述实际用户名配置，不直接运行该脚本套用旧环境。

### 7.4 开机自启

只有需要开机自动运行时，管理员才为实际用户启用 linger：

```bash
sudo loginctl enable-linger zh
loginctl show-user zh -p Linger
```

linger 使用户管理器在开机后和退出登录后仍可运行，见 [loginctl 原始手册](https://github.com/systemd/systemd/blob/main/man/loginctl.xml)。它不授予 FIFO 或内存锁定权限，所以第 7.3 节仍须完成。

随后在 APP 模型列表中选定唯一自启模型。APP 管理：

```text
~/.config/systemd/user/pyxcp-host-model.service
~/.local/share/pyxcp-host/autostart.json
~/.local/share/pyxcp-host/model_runner.py
```

服务使用 `/usr/bin/python3`，因此必须存在这个解释器路径。APP 不会隐式修改管理员级实时配置或启用 linger。诊断时在**同一个模型用户**下执行：

```bash
systemctl --user status pyxcp-host-model.service --no-pager
systemctl --user is-enabled pyxcp-host-model.service
journalctl --user -u pyxcp-host-model.service -b --no-pager
```

实际模型标准输出写入 ELF 同目录的 `<模型>.elf.pyxcp-host.log`。服务 `Restart=no`，模型退出不会无限重启。更换自启模型前先停止原运行实例，再核对新 ELF 和端口；一个用户当前只管理一个选定自启模型。

### 7.5 库依赖、网络和只读审计

上传后可在目标机对**工程可信 ELF**检查：

```bash
ldd /home/zh/MATLAB_ws/project_run/x280_rt_single.elf
ss -lunp
```

`ldd` 不应有 `not found`。若文件存在却提示 `No such file or directory`，检查 ELF 指定的加载器 `/lib64/ld-linux-x86-64.so.2`、架构和运行库，不要立即把它当作上传丢文件。

SSH 默认 TCP 22；当前模型使用 XCP UDP 17725。仅当现有防火墙策略需要时允许上位机访问对应端口，例如使用 UFW 的目标可以添加针对实际上位机 IP 的 UDP 17725 放行规则。TCP/22 连通不能证明 UDP/XCP 连通；不要把 TCP 17725 放行当成当前 UDP 模型的修复。APP 支持 TCP，但文件里声明的协议才是本轮依据。

在 Windows 工程根目录运行只读审计：

```powershell
& ./.venv/Scripts/python.exe ./tools/audit_realtime_target.py `
    --host 192.168.219.86 --user zh --output ./validation/new_machine/target_audit.json
```

脚本隐藏提示 SSH 密码，不安装软件、不修改内核、不重启。可选探测如 `mokutil`、`pro` 或只读 sudo 无权限时会在报告中记录失败；分别判断它是否影响当前验收，不要求为了消除探测警告给用户开放全局免密 sudo。

## 8. 可选：TC1013 Linux 驱动部署

仅运行普通主模型可以跳过本节。使用 CAN 库时，模型 ZIP 仍只有 ELF/A2L/JSON；厂商 SDK 独立安装，不能塞入当前三文件 ZIP。

Windows 准备一个尚不存在的 SDK 输出目录：

```powershell
& ./.venv/Scripts/python.exe ./x280_linux_target/drivers/tc1013/prepare_driver.py `
    --sdk-dir ./x280_linux_target/drivers/tc1013/vendor/linux --check
& ./.venv/Scripts/python.exe ./x280_linux_target/drivers/tc1013/prepare_driver.py `
    --sdk-dir ./x280_linux_target/drivers/tc1013/vendor/linux --output D:/tc1013-sdk-upload
scp -r D:/tc1013-sdk-upload zh@192.168.219.86:/home/zh/
```

如 Windows 未安装 OpenSSH 客户端，可使用支持 SFTP 的客户端上传同一目录。在 Linux 目标机执行：

```bash
sudo apt install libusb-1.0-0
python3 /home/zh/tc1013-sdk-upload/prepare_driver.py --sdk-dir /home/zh/tc1013-sdk-upload --check
python3 /home/zh/tc1013-sdk-upload/prepare_driver.py --sdk-dir /home/zh/tc1013-sdk-upload --output /home/zh/.local/lib/tscan
python3 /home/zh/.local/lib/tscan/prepare_driver.py --sdk-dir /home/zh/.local/lib/tscan --check
LD_LIBRARY_PATH=/home/zh/.local/lib/tscan${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} ldd /home/zh/.local/lib/tscan/libTSCANApiOnLinux.so
```

准备工具拒绝覆盖已有安装目录。升级时先停相关模型，部署到版本化新目录，修改两个 CANSetup 的 `DriverDirectory` 并重新构建。该参数必须和新用户的真实路径一致。

SDK 的核心文件为 `libTSCANApiOnLinux.so`、`libTSH.so`；Windows `libTSCAN.dll` 不能替换它们。SDK 的固定来源、提交、哈希和许可证见 [vendor/SOURCE.md](../x280_linux_target/drivers/tc1013/vendor/SOURCE.md)。库头兼容不等于 USB、固件和符号均兼容，必须运行真实设备验收。

USB 权限按厂商说明为实际设备设置。旧机只对已核对设备节点授予 plugdev 组权限，没有安装可跨重启复用的全局 udev 规则；**新机、重启或重新插拔后必须重新核对权限**。不要照抄旧设备的总线号/节点号，不要把全部 USB 设备设为全用户可写。

两个通道的 CAN 类型、串号、SDK 目录必须一致，CAN1/CAN2 的 CAN_H、CAN_L 及信号地按手册连接；终端电阻按实际总线配置。经典 CAN 默认 500 kbit/s，FD 默认仲裁 500 kbit/s、数据 2000 kbit/s。`HostTransport='Loopback'` 只用于 MATLAB 软件仿真，Linux 代码始终调用真实 SDK；模拟通过不等于硬件通过。

完整步骤、Status 错误码和回环预期见 [CAN 模型库](../x280_linux_target/drivers/tc1013/README.md) 与 [驱动部署](../x280_linux_target/drivers/tc1013/DEPLOY_DRIVER.md)。

## 9. 新机首次验收顺序

建议每步保留日志/JSON、所用 SLX 与 ZIP 的 SHA-256、工具版本和目标审计，形成该机器自己的验收目录。

| 顺序 | 操作 | 通过判据 |
| --- | --- | --- |
| 1 | 不连接目标，运行 `verifyX280Environment(ProbeTarget=false)` | 注册、编译器、导出接口和产品检查通过 |
| 2 | Ctrl+B 构建主模型 | 生成本轮 ZIP，包内三文件；ELF/A2L 配套，结果目录没有展开副本 |
| 3 | APP 加载 ZIP | 自动显示观测/标定目录，协议和端口正确，不手动填端口 |
| 4 | SSH 登录新 Linux | 用户、目录、Python、PREEMPT_RT 和额度审计正确 |
| 5 | 上传到新的专用目录 | APP 提示远端哈希校验成功，无 `.pyxcp-payload.pending` 遗留 |
| 6 | 启动模型、读取日志 | 模型进程持续运行，实时初始化无错误，UDP 端口由所选模型占用 |
| 7 | 观测页“上线”，勾选变量、启动 DAQ | 曲线/值变化；单/双游标只测已勾选并显示的曲线 |
| 8 | 小范围标定、回读、恢复 | 回读与写入一致；恢复值成功后再下线 |
| 9 | 停止 DAQ/下线并短时断开 SSH | 模型继续自主步进；重新连接后同一模型仍运行 |
| 10 | 正常停止模型并读日志 | 检查 `x280_rt_summary` 的周期、step 完成次数、超期、跳期、执行时间 |
| 11 | 需要时验证自启和重启 | 在计划重启后，不登录也能启动所选模型，服务和模型日志均正常 |
| 12 | 需要时验证 CAN | 两通道有效帧 ID/数据匹配，同时检查 Status、队列忙、USB 错误和 DAQ 间隙 |

正常“下线”不会停止模型，SSH 断开也不停止已部署的自主运行实例。停止模型用实时机页操作。不要同时让 MATLAB XCP、另一个 APP 或验收脚本占用同一 XCP 服务。

`tools/validate_local_workflow.py` 已使用 APP 的 ZIP 加载器，先核对 ZIP/ELF 哈希及模型身份，再连接目标；退出时清理解压缓存。需要自动化真机验收时可使用下列命令，它会上传到新目录、启动模型、验证 SSH 断开后自主运行及 XCP 观测标定，最后停止本轮模型。开始前应确保 UDP 17725 没有其他模型占用，且已完成实时环境准备：

```powershell
& ./.venv/Scripts/python.exe ./tools/validate_local_workflow.py `
    --receipts ./Demo_XCP_Qt/models/x280_rt_single/x280_rt_single_ert_rtw/x280_local_build.json `
    --host 192.168.219.86 --user zh --seconds 30 `
    --output ./validation/new_machine/local_workflow.json
```

`--receipts` 必须指向新机器本轮真实构建回执，输出 JSON 必须是新文件。`tools/realtime_boot_validation.py` 仍包含原机器特定 UID/重启操作，不能作为新机无检查的通用命令。

## 10. 安装和迁移故障定位

| 现象 | 先看证据 | 处理方向 |
| --- | --- | --- |
| `UnsupportedRelease` | `version('-release')` | 使用 R2024b；其它版本需移植和重新验收 |
| 工具箱函数不存在或许可证错误 | `ver`、`which ... -all`、完整 MATLAB 报错 | 补装相应产品/修复许可；路径可见不代表许可可用 |
| 找不到硬件或显示旧工具链 | `which setupX280LinuxTarget -all`、模型 Toolchain | 在当前路径注册并重新 `configureX280Model`；清除指向旧副本的 path 项 |
| `ToolchainMissing` | `x280ToolchainRoot`、`X280_TOOLCHAIN_ROOT` | 指向含 `toolchain/bin` 的包根；检查目录多一层/少一层 |
| GCC 找不到头文件、`cc1` 或库 | 完整编译命令、工具链 manifest | 恢复完整工具链/sysroot，不只复制 bin；不要使用另一套 GCC 的环境变量 |
| ELF 有了但 A2L/ZIP 未发布 | MATLAB 构建日志、`_ert_rtw/x280_build_evidence` | 排查导出和符号匹配错误；保留失败证据，重新完成整轮构建 |
| 新机 `.venv` 无法启动 | `.venv/pyvenv.cfg`、解释器版本/位数 | 在新目录用正确的 Python 重建，勿只改某个绝对路径 |
| DLL/Qt 插件缺失，EXE 闪退 | `app/_internal`、`qwindows.dll`、启动错误日志 | 整体恢复交付目录；源码环境核对 `xcp_core.dll` 及 ABI |
| SSH 成功但上传目录被拒绝 | 完整远端路径、符号链接、目录所属用户 | 选择 SSH 用户主目录下的新专用子目录 |
| 文件存在却不能执行 | ELF 架构、加载器、`ldd` | 检查 x86-64/glibc 及文件系统挂载权限，不在 Linux 重编译掩盖依赖问题 |
| `PREEMPT_RT kernel required` | `uname -r`、`/sys/kernel/realtime` | 启动正确 RT 内核；不要关闭检查作为验收 |
| `mlockall` 或 FIFO 线程创建失败 | 新 SSH 的 `ulimit`、用户管理器额度、模型日志 | 分别修复 PAM 与 user@ 服务额度；锁内存不足也可能表现为线程创建失败 |
| 手动启动正常、自启失败 | `loginctl`、用户服务状态、user@ 限额 | 核对 linger、解释器绝对路径、用户服务继承的额度及 DriverDirectory |
| UDP 上线超时 | 包中地址、模型日志、`ss -lunp`、防火墙 | 核对 IP/协议/端口及其它主站；更新 SSH 地址不能覆盖包里的旧 XCP 地址 |
| A2L 协议缺失/歧义/冲突 | A2L IF_DATA 与 JSON `XCPTransport/XCPPort` | 使用工程生成的同轮完整 ZIP，禁止随意拼包 |
| 变量树为空或层级过旧 | 所加载 A2L 的测量项/GROUP、本轮构建版本 | 确认变量未被优化掉且重新生成当前 A2L；旧包不会自动拥有新层级元数据 |
| CAN Status -3/-4 | 模型日志、SDK `--check`、`ldd`、USB 权限 | 区分库/符号加载失败与设备/通道配置失败，核对 DriverDirectory |
| CAN 队列忙或有 DAQ 间隙 | Status、有效帧、实时汇总、XCP 接收统计 | 分别分析总线/USB、模型调度、网络和绘图；曲线刷新不是模型步长 |

保存故障材料时应包括：新机器版本清单、对应 ZIP、SHA-256、构建完整日志、目标只读审计、APP 诊断日志、模型运行日志、可重现操作顺序。不要把 SSH 密码、DPAPI 凭据或订阅令牌放入报告。
