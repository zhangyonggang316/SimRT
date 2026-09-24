# 分阶段故障排查

本指南按“生成 → 编译 → 配套文件 → 部署 → 启动 → XCP → CAN → APP”顺序定位。技术原理和源码阅读顺序见 [技术路线](ARCHITECTURE.md)，新机器准备见 [新机部署指南](NEW_MACHINE_DEPLOYMENT.md)。除明确标注会运行测试或生成文件的命令外，下面的检查命令只读取状态。

## 1. 先记录本次问题

记录实际使用的 SLX、ZIP、APP 路径与修改时间；保存 APP 诊断页日志、Linux 模型运行日志及本地构建回执。不要只发“连不上”的截图：失败发生在上传、启动、上线、DAQ 还是写标定，定位方向完全不同。

| 证据 | 位置/取得方式 |
| --- | --- |
| APP 诊断及通信状态 | APP“诊断日志”页，保存日志；包括当前端点与待恢复标定量 |
| APP 启动异常 | Windows `%TEMP%/QtXCPHost-startup.log`；检查修改时间，避免使用上次失败记录 |
| 最新构建回执 | `<model>_ert_rtw/x280_local_build.json` |
| 当轮构建详情 | `<model>_ert_rtw/x280_build_evidence/<时间戳>/build_report.json`、`elf_inspection.txt` |
| Linux 模型标准输出/错误 | `<远程模型完整路径>.pyxcp-host.log`，也可用 APP“读取运行日志” |
| Linux 部署状态 | 模型目录 `.pyxcp-payload.pending`、`.pyxcp-payload.json` |
| Linux 进程记录 | `<远程模型完整路径>.pyxcp-host.json`，需结合 `/proc` 判断，不能只相信旧 PID |
| 用户自启状态 | `systemctl --user status pyxcp-host-model.service --no-pager` |
| 测试结果 | 指定测试输出目录中的 `test_report.json`、`qt_tests.log`、`baseline_tests.log` |

不要将 SSH 密码、保存的凭据密文或完整本机私有配置放进问题报告。哈希和错误堆栈通常足够识别版本与失败点。

## 2. MATLAB 注册与本地代码生成

### 2.1 找不到硬件、重复硬件或错误版本

在用户主动打开的 MATLAB 中，将工作目录设为工程根目录：

```matlab
addpath(fullfile(pwd, 'x280_linux_target'));
which setupX280LinuxTarget -all
setupX280LinuxTarget;
report = verifyX280Environment(ProbeTarget=false, Strict=false);
disp(report);
```

该检查会在当前 MATLAB 会话注册目标并更新本地注册文件，不连接 Linux。`UnsupportedRelease` 表示当前实现要求 R2024b；不能只改版本检查就假定运行器和 Coder API 已兼容新版。

当前硬件名称应为 `SimRT`。升级后名称未更新时，重新运行当前工程的 `setupX280LinuxTarget`，重新打开模型配置窗口，必要时重启 MATLAB。对旧模型按[迁移步骤](NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)运行 `configureX280Model(..., Save=true)`，并读取 `get_param('实际模型名', 'HardwareBoard')` 核对；只更新注册文件不会自动重写用户保存的全部 SLX。工具链仍名为 `X280 portable-linux-toolchain`，这是正常配置。

`MissingProduct` 或 `LocalValidationFailed` 时看 `report.RequiredProducts`、`A2LExportAvailable`、`XCPAvailable`、`LocalBuildAvailable`。当前环境检查包含 `xcpA2L` 和 `xcpChannel`；CAN Pack/Unpack 及官方 CAN bus 还需要 Vehicle Network Toolbox。安装或许可存在问题时先解决产品可用性。

迁移工程后若 `which -all` 指向旧目录，清理当前 MATLAB path 中旧工程入口并重新运行当前工程的注册脚本。不要用另一目录下同名 SLX 和本目录的构建回执混合验证。

### 2.2 模型未保存或配置被改动

| 错误/现象 | 处理 |
| --- | --- |
| `x280linux:UnsavedModel` | 保存本轮改动再生成；构建需要可追溯的 SLX 快照 |
| `x280linux:ModelNameConflict` | 同名模型已从另一目录打开；先确认并保存该模型，再关闭冲突副本 |
| `x280linux:RealtimeConfiguration` | 看错误列出的配置差异，核对固定步长、单任务、ERT、C、Linux x86-64、ExtMode |
| `x280linux:UnsupportedTasking` | 生成器当前只支持单任务 C；检查 multitasking、concurrent、异步任务 |
| `x280linux:RuntimeContract` | 本轮生成入口不符合已验证 R2024b 单任务形态；保留生成源码检查，不绕过断言 |
| Ctrl+B 只有 C 没有 ZIP | 检查 `GenCodeOnly` 是否为 `on`，以及链接/after_make 是否成功 |

已加载模型的只读检查：

```matlab
validateX280RealtimeModel('x280_rt_single');
get_param('x280_rt_single', 'FixedStep')
get_param('x280_rt_single', 'GenCodeOnly')
get_param('x280_rt_single', 'Toolchain')
```

需要重配时参考部署文档调用 `configureX280Model`。该函数会改变模型配置，先保存或建立工作副本；不要在没有确认模型用途时反复运行配置函数。

## 3. 交叉编译、ELF 和 A2L

### 3.1 找不到编译器或 sysroot

从工程根目录执行：

```powershell
Get-Item Env:X280_TOOLCHAIN_ROOT -ErrorAction SilentlyContinue
& './portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe' --version
& './portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-readelf.exe' --version
```

`X280_TOOLCHAIN_ROOT` 应指向含 `toolchain/` 的包根目录，不是 `bin/`；本包 sysroot 位于 `toolchain/x86_64-linux/`。更换机器或移动路径后重新注册工具链。不要将 `tools/qt_toolchain` 的 Windows clang 当作 Linux 交叉 GCC。

链接报找不到系统头文件/库，先看 `x280PortableToolchain.m` 和当轮 Makefile 的 sysroot 参数；报找不到厂商 CAN 头文件时看 `+x280linux/+can/Native.m::updateBuildInfo` 的源文件路径。当前 CAN SDK 使用动态加载，两个厂商 `.so` 的缺失主要是目标运行期问题，不应通过任意复制 Windows DLL 修复。

### 3.2 最终 ELF 与 A2L 不匹配

常见错误包括 `LocalELFMissing`、`ELFNotFound`、`WrongELFArchitecture`、`LocalBuildInvalid`、`LocalArchiveInvalid`、`A2LNotCreated`。

先确认链接已成功，再看 `x280_local_build.json` 的 `archive` 和 `evidence_directory`。正常情况下最外层 `<model>.elf` 已被清理，这是预期行为；`record.local_elf` 指向内部证据缓存。可以从 ZIP 的副本解压检查，或在 MATLAB 使用 `locateX280ELF` 查找配套产物。

```powershell
$elfPath = 'C:/实际检查目录/x280_rt_single.elf'
& './portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-readelf.exe' -h -l -d -V $elfPath
Get-FileHash -LiteralPath $elfPath -Algorithm SHA256
```

期望 ELF64、little-endian、x86-64、`Type: EXEC`。`DYN`/PIE 会被 APP 的固定地址校验拒绝。动态解释器及依赖版本必须与目标 Linux 相容；`GLIBC_x.y not found` 应通过兼容 sysroot/运行平台解决，不能随意替换目标系统 libc。

A2L 来自 `coder.asap2`，地址来自最终 ELF。重新链接、修改信号存储或重新生成 C 后，需要重新导出 A2L/JSON 并生成 ZIP。`FixedXCPConfigurationRequired` 表示导出端口与编译配置不一致；本工程默认是 UDP 17725，单独修改导出参数会被拒绝。

### 3.3 模型层级或变量缺失

先解开 ZIP 的检查副本，在 A2L 中确认 `GROUP`、`SUB_GROUP`、`REF_MEASUREMENT`、`REF_CHARACTERISTIC`。旧 A2L 没有实际分组时，APP 无法从 C 变量名恢复原始子系统结构，需要重新构建导出。

若层级存在但对象缺少，检查生成报告中该信号/参数是否有可访问存储，是否被优化、是否为当前 UI 不支持的数组或复杂对象。工作区参数、共享参数及没有更深 SID 来源的对象可能合法地放在模型根级。不要把所有根级对象都判断为层级解析错误。

对应源码：`createX280ASAP2Hierarchy.m`、`services/a2l_metadata.py`、`services/a2l_catalog.py`、`qt_host/catalog_tree.py`。

## 4. ZIP 载入与部署校验

| 错误信息 | 说明与修复 |
| --- | --- |
| `ZIP 必须只包含一个结果文件夹及 ELF、A2L、JSON 三个文件。` | 包含额外报告、README 或多层目录；使用构建流程发布的 ZIP |
| `ZIP 中的三个文件必须位于同一个结果文件夹。` | 直接压缩散文件或套了两层文件夹；应保留一层时间戳目录 |
| `ZIP 含有不安全的路径。` | 含绝对路径、父级跳转或非法名称；重新从可信产物构建 |
| `Duplicate file or payload SHA256 mismatch` | ELF/A2L 被替换或损坏；重新取得同轮配套 ZIP |
| `Payload requires a fixed-address x86-64 Linux ELF64` | 错误架构、Windows EXE 或 PIE；回到本地 Linux 交叉链接检查 |
| `Payload contains files not covered by its manifest` | 解压目录混入额外文件；恢复原始产物，不把源码目录作为 payload |
| ZIP 超过 512 MiB / 解压超过 1 GiB | 触发当前 APP 大小上限；检查是否误装入源码、SDK 或其它输出 |

ZIP 的最终结构只允许三件套。厂商 SDK 应单独部署到 `DriverDirectory`。不要修改 `%TEMP%/qt-xcp-payload-*` 下正在被 APP 使用的文件；重新加载新的 ZIP，让 APP 建立新的校验状态。

上传中断后，目标保留 `.pyxcp-payload.pending`，启动会报 `Payload upload did not complete verification; redeploy before starting`。重新完整上传并等待远端哈希验证，不能仅删除 pending 标记绕过检查。`Local payload changed during upload` 表示上传过程中本地产物变化，应停止修改并重新部署。

## 5. SSH 与远程模型操作

### 5.1 连接不上

```powershell
Test-NetConnection -ComputerName '目标IP' -Port 22
```

先核对 IP、路由、SSH 服务及端口，再检查用户名/密码。当前 APP SSH 实现使用密码登录，源码中明确拒绝私钥参数。不要把命令行 SSH 使用某个密钥成功当作 APP 密码认证也已配置。

首次主机密钥会记录在应用日志并保存；服务器重装导致密钥变化时先核对新指纹，再按本机 SSH 主机记录处理，不应直接关闭主机身份校验。保存的凭据使用当前 Windows 用户 DPAPI，不能把另一用户或另一台机器的密文当作可迁移密码。

### 5.2 上传、停止或删除被拒绝

`Deployment must use a dedicated directory below the SSH home` 表示远程目录必须位于 SSH 用户主目录下的专用子目录。`Stop executables in the destination before upload or build` 表示目录仍有运行模型，先在 APP 正常停止，再上传。

删除会一并删除所选模型对应目录，要求目录内没有其他 ELF、符号链接或仍运行的程序。`Model directory contains another ELF; refusing to delete shared files` 应通过拆分部署目录解决，不要强行删除共享目录。停止前的标定恢复失败也会阻止后续停止或删除，先处理第 8 节。

模型列表不会按资源刷新周期反复扫描；外部手动新增目录后使用刷新图标或右键“刷新”。若命令正在执行，按钮暂不可用应等待完成；当前部署页没有取消任务按钮，可从诊断日志判断操作是否提交及远端是否返回。

## 6. ELF 启动后立即退出或实时条件不满足

在目标 Linux 的同一登录用户下，替换真实模型路径后执行：

```bash
model_elf="$HOME/MATLAB_ws/实际模型目录/x280_rt_single.elf"
tail -n 100 "${model_elf}.pyxcp-host.log"
uname -a
uname -m
cat /sys/kernel/realtime
ulimit -r
ulimit -l
ldd "$model_elf"
ss -lunp | grep ':17725'
```

只对工程可信 ELF 执行 `ldd`。`cat /sys/kernel/realtime` 不存在或不为 1 说明当前运行内核不满足默认实时要求。不要用 `X280_RT_REQUIRE_KERNEL=0` 的实验结果代替生产实时验收。

| 运行日志 | 定位 |
| --- | --- |
| `ELF exited immediately; inspect the runtime log` | APP 发现进程立即退出；具体原因在对应 `.pyxcp-host.log` |
| `PREEMPT_RT kernel required (/sys/kernel/realtime != 1)` | 当前启动的内核不符；按部署文档安装并启动已验证内核 |
| `mlockall: grant sufficient locked-memory limit/CAP_IPC_LOCK` | 实际模型进程锁内存额度或权限不足 |
| `pthread_create SCHED_FIFO: grant rtprio/CAP_SYS_NICE...` | 实时优先级权限或锁内存额度不足，检查启动该进程的会话/服务限制 |
| `X280_RT_CPU is not in the allowed affinity mask` | 指定 CPU 不在允许集合；检查 cpuset、容器或服务亲和性 |
| `X280 RT autonomous execution does not support -w` | 移除等主站启动的参数，当前模型自主运行 |
| `X280 RT extmode... failed` | 检查端口占用、协议栈初始化、A2L/运行配置，再保留完整错误编号 |
| `error while loading shared libraries` / `not found` | 目标运行库或 SDK 依赖缺失，按 ELF 依赖逐项解决 |

实际运行状态可用以下命令检查。`model_pid` 请填 APP 显示的当前 PID，不能直接使用历史报告中的数字：

```bash
model_pid=12345
ps -L -p "$model_pid" -o pid,tid,cls,rtprio,psr,comm
cat "/proc/$model_pid/limits"
grep -E 'Cpus_allowed_list|VmLck' "/proc/$model_pid/status"
readlink "/proc/$model_pid/exe"
```

实时权限需检查实际进程，不能只看一个新开的 SSH 终端。用户自启服务可能继承不同限制。正常目标应至少看到模型线程 FIFO；主线程和 CAN SDK 后台线程保留普通调度是设计行为。

自启问题另外检查：

```bash
systemctl --user status pyxcp-host-model.service --no-pager
journalctl --user -u pyxcp-host-model.service -n 100 --no-pager
loginctl show-user "$(id -un)" -p Linger
```

`Linger=no`、用户服务管理器不可达、服务限制不足、目标文件哈希变化都可能使开机自启失败。APP 自启设置不替代管理员的系统准备。

## 7. XCP 上线与 DAQ

### 7.1 上线按钮不可用或连接到旧地址

| 提示 | 处理 |
| --- | --- |
| `文件未声明 XCP 通信协议和端口...` | 加载本轮完整 A2L 或配套 ZIP |
| `A2L 声明了多个通信协议，请加载配套模型 ZIP。` | 通过清单明确协议，避免猜测 |
| `A2L 与模型包的通信协议或端口不一致。` | 重新导出一致的三文件，检查是否混包 |
| `文件未声明目标地址，请在实时机页面填写 SSH 主机。` | 文件确实无地址时填写 SSH 主机作为回退 |
| 已填新 SSH 地址但 XCP 仍连接旧地址 | ZIP/A2L 声明优先于 SSH 回退；按新地址重新导出部署包 |

端口来自文件，观察顶部端点和按钮提示。默认 UDP 17725；`Test-NetConnection -Port 17725` 只测试 TCP，不能证明 UDP XCP 是否可用。

### 7.2 SSH 正常，但 XCP 超时

依次检查：模型进程仍存在；模型运行日志没有启动失败；`ss -lunp` 可见预期 UDP 端口；Windows/Linux 网络策略允许该 UDP 通信；没有另一个 XCP 主站占用会话；当前 APP 的端点与该模型一致。

连接字节序不匹配会被 `XcpSession.connection_info` 拒绝。变量读值异常时核对当前运行 ELF 的 SHA-256 和 ZIP 的 `ELFSHA256`，再核对 A2L。普通 XCP 上线握手及字节序检查并不等于完整证明模型源码版本相同。

### 7.3 上线成功但没有曲线

先勾选实际测量变量，确认开始采集，检查曲线可见开关和当前时间窗口。取消勾选会隐藏曲线并退出游标结果，但保留历史。重新加载 A2L 会建立新的变量集。

DAQ 需要周期性、支持 DAQ 的模型事件；出现 `DAQ requires a periodic, DAQ-capable model event` 时查事件定义。目标不支持 `GET_DAQ_EVENT_INFO` 时，服务仅在特定“不支持”响应下使用 A2L 的唯一匹配 EVENT，缺失或歧义会明确报错，不会编造 1 ms 事件。

| DAQ 诊断计数增加 | 说明 |
| --- | --- |
| `transport_counter_gaps` | XCP Ethernet 帧计数存在缺口 |
| `timestamp_gap_samples` | 完整事件时间戳间隔大于预期 |
| `invalid_frames`、`incomplete_events` | 报文长度、ID 或同次事件的 ODT 组合异常 |
| `queue_dropped_samples` | APP 有界 DAQ 待处理队列满，采集数据被丢弃 |
| `overload_events` | Slave 报告 DAQ 过载 |
| `timestamp_wraps` | 已处理的时间戳回绕，本身不等于丢样 |

减小变量集合后复测可帮助区分带宽/队列压力。原始历史缓存容量和 DAQ 待处理队列是两个不同缓冲，单纯增大曲线历史容量不能解决网络丢帧。

检查模型实时性时，正常停止后读取 `x280_rt_summary`。`model_step_interval_*` 衡量实际执行间隔；`deadline_misses`、`skipped_releases` 与 DAQ 丢样计数分开分析。不要根据 APP 刷新率判断模型实际步长。

## 8. 标定失败、下线失败与恢复

“待恢复标定量”表示当前会话已保存原始字节且存在修改。正常下线会先恢复、回读确认，再断开。恢复回读不一致、连接失效或目标退出都会使操作报错，不应继续点击停止模型来掩盖失败。

处理顺序：保留 APP 和日志，确认目标进程及 ELF 没有变化，恢复同一目标的网络，尝试“恢复”或“下线”。若服务仍保留连接对象，失败后允许重试下线；这不保证已经断开的网络会话能无条件自动重连恢复。

若目标已经重启、换了 ELF，或 APP 被强制关闭，原始字节的会话语境可能丢失。记录仍待处理的变量，依据同轮模型初始参数和实际回读重新核对；不要把旧地址表中的字节写进新模型。需要重新上线时先确认新会话对应的新产物。

`标定量 ... 地址范围重叠` 是对别名或重叠变量的保护，选用一个明确对象修改。`写入后的回读值不匹配` 应检查对象是否可写、原始类型和输入数值范围是否匹配，以及是否由模型每步重新赋值。当前 APP 不执行完整 `COMPU_METHOD` 物理量换算，不要把工程单位数值当作任意 A2L 都可直接写入的原始值。

对应源码：`services/xcp_session.py::write_calibrations/restore_calibrations/disconnect`、`qt_host/controller.py` 的恢复与远程停止保护。

## 9. CAN 与 CAN FD

先把问题分成模型 bus 接口、生成 C 接口、SDK 加载、USB 设备访问和总线收发五层。软件 `HostTransport='Loopback'` 通过，只证明前两层的一部分。

| 状态 | 主要排查方向 |
| --- | --- |
| -1 / -2 | 报文参数、通道参数、重复 CANSetup |
| -3 | `DriverDirectory`、两个 Linux `.so`、架构、依赖与接口符号 |
| -4 | USB 访问权限、设备/序列号、通道配置、厂商返回错误 |
| -5 / -12 / -13 | 通道初始化、两 Setup 的目录/序列号一致性、CAN/FD 模式一致性 |
| -6 / -7 / -9 | 短暂锁忙、发送队列满、接收队列溢出；统计频度及总线负载 |
| -8 / -10 / -11 | 后台线程创建、SDK 异步发送或接收失败；读取 SDK/模型日志 |
| -14 / -15 | 初始化切换工作目录失败 / MATLAB 软件通信禁用 |

在目标机按实际编译进模型的目录检查：

```bash
driver_dir="$HOME/.local/lib/tscan"
file "$driver_dir/libTSCANApiOnLinux.so" "$driver_dir/libTSH.so"
ldd "$driver_dir/libTSCANApiOnLinux.so"
ldd "$driver_dir/libTSH.so"
lsusb
id
```

`CANSetup.DriverDirectory` 是编译期绝对路径，不能因为新用户的 `$HOME` 变化就假定模型自动跟随。两路 Setup 应使用相同目录/序列号，不同 Channel；修改参数后重新构建 ZIP。SDK 通过独立安装准备，不能把 Windows `libTSCAN.dll` 当作 Linux 库。

库可加载后再检查硬件：CAN_H/CAN_L、信号地、终端电阻、两路仲裁波特率一致；FD 还需数据波特率及 BRS 配置一致。接收有效性应同时检查 `Valid`、`Status` 和 ID；CAN Unpack 的信号定义不能替代帧 ID 判断。

本工程每步最多接收一帧，真实 USB 接收异步；有些步 `Valid=false` 不等于驱动坏。`CanSent.Status=0` 只证明排队成功，后续 SDK 发送错误会在状态/日志中出现。故障定位与正式验收应统计有效帧数、错误状态数、ID/全部数据正确性及实时计时。

## 10. APP 启动、绘图与测试

若 EXE 双击无主界面，先看 `%TEMP%/QtXCPHost-startup.log`。必须复制整个 `Demo_XCP_Qt/app`，保留 `_internal`；单个 EXE 不是独立可运行交付物。

`Required C++ core is missing`、`Cannot load the required C++ core` 或 `Unsupported C++ core ABI` 分别指向 DLL 缺失、依赖/架构不符或接口版本不一致。开发环境修复后重建 DLL 和 APP；正式交付应整体重新发布，不混用另一版本的 DLL。

从工程根目录运行下列本地测试。这些命令会创建指定报告目录；Qt/服务测试中的网络交互使用测试端，不等于真实 Linux/TC1013 验收：

```powershell
& './.venv/Scripts/python.exe' -m pip check
& './.venv/Scripts/python.exe' qt_xcp_host/validate_tests.py --output validation/manual_regression
& './.venv/Scripts/python.exe' qt_xcp_host/validate_visual.py --output validation/manual_visual
```

按修改范围增加目标层测试，不需要为每个文档或日志操作启动 MATLAB：

```powershell
& './.venv/Scripts/python.exe' -m unittest discover -s x280_linux_target/tests -p 'test_*.py' -v
& './x280_linux_target/drivers/tc1013/tests/run_offline_tests.ps1' -OutputDirectory validation/manual_can_offline
```

需要验证 MATLAB 代码生成或 System 对象时，在已经打开、配置好工具链的 MATLAB 中运行相关测试；构建测试会实际生成代码和本地编译：

```matlab
addpath(fullfile(pwd, 'x280_linux_target'));
results = runtests({'x280_linux_target/tests/tX280ArtifactArchive.m', ...
    'x280_linux_target/tests/tX280LocalArtifacts.m'});
assertSuccess(results);
```

CAN System 对象与模型的软件测试分别位于 `tX280CANObjects.m`、`tX280CANLoopback.m`。进一步真机验收应在空闲端口和独立模型目录进行，保留本轮 SLX/ZIP/APP 身份及采集日志，不能把离线成功报告当作硬件已通过。

## 11. 提交问题时的最小复现材料

1. 实际启动入口、APP 构建身份、MATLAB 版本、目标内核与架构。
2. 完整操作顺序和首次失败阶段，包括是否重新加载过 A2L、目标是否曾重启。
3. ZIP SHA-256、本轮 `build_report.json` 与相关错误前后的日志；可隐去非必要机器地址。
4. 实时问题提供 `x280_rt_summary` 与 DAQ 诊断，CAN 问题提供协议、波特率、状态码和有效帧统计。
5. 若改过源码，列出相关文件和对应测试结果；保留本轮证据后再清理可再生缓存。
