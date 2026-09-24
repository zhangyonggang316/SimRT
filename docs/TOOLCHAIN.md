# Simulink 本地交叉编译、SSH 部署与 XCP 工具链

适用：MATLAB/Simulink R2024b、Windows x64、Ubuntu x86-64、PySide6 Qt APP。

## 1. 完整流程

```text
Windows：SLX -> Ctrl+B / slbuild -> 生成 C 代码及实时/XCP 入口
        -> portable-linux-toolchain 本地编译、链接
        -> Linux ELF + 基于最终 ELF 导出的 A2L + SHA-256 manifest
        -> APP 选择并校验 payload -> SSH / SFTP 上传
Ubuntu ：校验产物 -> 启动模型 -> 1 ms 自主运行
Qt APP ：XCP on UDP 观测、标定、回读、恢复；SSH 管理日志和启停
```

**代码生成、编译、链接和 A2L 配套均在 Windows 本地完成，不依赖目标机在线。**
目标机不参与编译。APP 的 C++ DLL 负责本机缓存、统计、游标和绘图抽样；模型实时调度由 Ubuntu 上的运行器负责。
正式 APP 入口是 `Demo_XCP_Qt/START_DEMO.cmd`，分发需复制整个目录并保留 `app/_internal`。

## 2. 环境准备

| 位置 | 必要组件 |
| --- | --- |
| 本地代码生成 | MATLAB R2024b、Simulink、Simulink Coder、Embedded Coder 及许可 |
| 本地编译 | `portable-linux-toolchain/portable-linux-toolchain`，内含 Windows GCC 7.5.0、binutils、Linux sysroot |
| 源码打包与测试 | 工程 `.venv/Scripts/python.exe`，Python 3.9.10；依赖见根 `requirements.txt` |
| Qt 源码开发 | PySide6 6.8.3、pyxcp 0.22.32、Paramiko 4.0.0、Matplotlib 3.9.4、C++ 核心 DLL |
| 目标机 | x86-64 Linux、OpenSSH/SFTP、Python 3、兼容的 glibc 及 ELF 所需运行库 |
| 实时运行 | PREEMPT_RT、FIFO 权限、锁内存额度、可用 CPU；自启另需用户 linger |

目标机无需 MATLAB、GCC 或 Make。Python 3 用于部署校验和进程管理。使用已构建交付包的测试电脑无需安装 Python、MATLAB 或交叉编译器。
工具链默认从工程目录发现；也可通过 `X280_TOOLCHAIN_ROOT` 指定包根目录。迁移或升级注册名称后重新执行 `setupX280LinuxTarget`，再用 `configureX280Model(..., Save=true)` 更新旧模型，使 `Hardware board` 为 `SimRT`。工具链名称继续为 `X280 portable-linux-toolchain`。
工具链包内 README 说明 sysroot 和运行库兼容边界。

```powershell
& ./.venv/Scripts/python.exe -m pip check
& ./.venv/Scripts/python.exe tools/audit_realtime_target.py `
    --host 192.168.219.86 --user zh --output validation/target_audit_new.json
```

审计脚本只读取环境。内核、权限和 linger 由管理员预先配置，APP 不隐式修改系统设置。
密码经隐藏提示或 APP 输入，不写入模型、构建参数或报告。

## 3. 配置模型与 Ctrl+B

在 MATLAB 中将 projectRoot 设置为当前工程根目录：

```matlab
projectRoot = 'C:/DataSave/03matlabUbuntu/02AIToolLinux';
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget;
verifyX280Environment(ProbeTarget=false, Strict=true);
modelFile = fullfile(projectRoot, 'Demo_XCP_Qt', 'models', ...
    'x280_rt_single', 'x280_rt_single.slx');
open_system(modelFile);
configureX280Model('x280_rt_single', Address='192.168.219.86', Save=true);
validateX280RealtimeModel('x280_rt_single');
```

配置函数会保存模型配置。先保存用户修改；实验性调整可使用工作副本。
在 Simulink 中按 **Ctrl+B**，或执行：

```matlab
slbuild('x280_rt_single');
build = RTW.getBuildDir('x280_rt_single');
record = jsondecode(fileread(fullfile(build.BuildDirectory, 'x280_local_build.json')));
disp(record.payload);
```

| 参数 | 本地构建设置 |
| --- | --- |
| Hardware board | SimRT |
| Device type | Intel->x86-64 (Linux 64) |
| System target file | ert.tlc |
| Toolchain | X280 portable-linux-toolchain |
| Generate code only | off，使 Ctrl+B 完成编译与配套导出 |
| Language | C |
| Solver | Fixed-step / FixedStepDiscrete |
| 基本步长 | 唯一模型 x280_rt_single，固定为 0.001 s |
| Tasking | EnableMultiTasking=off、ConcurrentTasks=off |
| External mode | ExtMode=on，用于引入 XCP 通信代码 |
| Default parameter behavior | Tunable |

仅交付 1 ms 单任务单速率模型。运行器保留生成算法，使用自主实时入口及后台 XCP 通信。
标定对象采用 Simulink.Parameter 和可定位存储类，例如 ExportedGlobal；观测信号及地址以本轮 A2L 为准。
本地回执给出实际 ELF、payload、RT 源码、工具链和哈希路径。保留回执、构建日志、SLX、cache 和 codegen。
程序化入口也可使用 `buildX280Local(modelFile, Address='192.168.219.86')`。

Ctrl+B 的最终输出目录不再包含嵌套 payload、源码包或构建报告：

```text
x280_rt_single_local/<时间戳>/
  x280_rt_single.elf
  x280_rt_single.a2l
  x280_rt_single.xcp-manifest.json
```

上述结构只保留在 `<时间戳>.zip` 内，ZIP 校验成功后删除展开的时间戳目录，最终 `_local/` 仅保留 ZIP。APP 在私有临时目录内解压，校验清单和哈希，自动识别 ELF 并加载配套 A2L；关闭 APP 时清理解压缓存。仍兼容已有三文件目录。SLX 快照、RT 源码包、Makefile 和诊断报告统一保存在
`x280_rt_single_ert_rtw/x280_build_evidence/<时间戳>/`，构建回执仍是 `x280_rt_single_ert_rtw/x280_local_build.json`。
只有配套导出和检查成功后才发布 ZIP。经解压和逐文件哈希校验后，构建回执记录 `archive` 与 `archive_sha256`，`payload` 也指向 ZIP，然后删除展开目录及模型目录最外层重复 ELF。`buildX280Local(..., ArtifactDirectory=...)` 同样仅保留指定目录的同级 ZIP。`locateX280ELF` 从构建回执定位 ZIP，校验后解压到内部证据缓存并返回与模型哈希匹配的 ELF。

A2L 使用 Embedded Coder 的 `coder.asap2` 导出，层级从本轮代码描述符的 Simulink SID 父链生成标准 `GROUP/SUB_GROUP`，保留模型及子系统原名。APP 读取这些分组用于观测与标定树，不拆分 C 标识符猜测层级。观测页“上线/下线”按钮使用加载文件声明的协议及端口；缺少主机地址时沿用 SSH 主机。

## 4. 分阶段本地构建

需要分别检查生成与编译时，在保存模型后使用新的输出目录：

```matlab
runFolder = fullfile(projectRoot, 'validation', ...
    ['build_' char(datetime('now','Format','yyyyMMdd_HHmmss'))]);
record = generateX280RealtimeBundle('x280_rt_single', runFolder);
```

输出包括 SLX 快照、generation_report.json、cache、codegen、原始源码包和 RT 源码包。

```powershell
$runFolder = 'C:/实际工程/validation/build_本轮时间'
& ./.venv/Scripts/python.exe tools/build_local_bundles.py `
    --folder $runFolder --host 192.168.219.86 --check-only
& ./.venv/Scripts/python.exe tools/build_local_bundles.py `
    --folder $runFolder --host 192.168.219.86 --jobs 2 --timeout 300
```

`--host` 只记录 A2L 目标地址，不发起连接。可加 `--toolchain-root <包根目录>`。
独立 RT 源码包使用 `--bundle <source目录> --output <新结果目录>`。
构建器复制输入后编译，在 built/<model>.elf 原子发布结果，生成 build_report.json。
在生成本轮模型的 MATLAB 中导出配套文件：

```matlab
addpath(fullfile(projectRoot, 'tools'));
exports = export_period_payloads(runFolder);
% 独立输出：export_period_payloads(runFolder, BuildFolder='构建结果目录');
```

保留 -O2、非 PIE、调试符号和 DWARF 4，记录编译器、sysroot、编译/链接命令及依赖。
对象缓存依据源码、头文件、参数及工具链身份判断复用；--rebuild 全量重建。
旧 deploy_realtime_bundles.py 保留用于历史复现，不属于当前标准构建流程。

## 5. 产物与 SSH 部署

每轮 payload 包含 <model>.elf、<model>.a2l、<model>.xcp-manifest.json。
A2L 使用本轮最终 ELF 地址生成，ELFSHA256 和 A2LSHA256 必须匹配。
额外依赖可通过 manifest 的 RuntimeFiles 字段声明，以相对文件路径映射 SHA-256。
APP 拒绝未列入清单的文件、缺失文件、符号链接、错误架构或 PIE ELF。

1. 启动交付包，进入“实时机 / 模型部署”。
2. 选择本轮 `<时间戳>.zip`。APP 内部解压并校验三文件清单，在 XCP 未连接时加载配套 A2L 和地址。SSH 上传的是解压后的文件。
3. 输入 SSH 主机、用户和密码并连接；需要记忆时勾选“记住 SSH 凭据”。
4. 设置 SSH 用户主目录下的专用远程目录，点击“上传产物”。
5. 诊断日志显示远端哈希校验成功后，点击“启动 ELF”。
6. 在“观测”确认加载文件自动识别的端点，点击“上线”，再勾选变量开始采集或转到标定。协议和端口不再手动填写；迁移目标地址应按 [新机部署指南](NEW_MACHINE_DEPLOYMENT.md) 重新生成匹配 ZIP。

上传写入待校验标记，只有完整哈希校验成功才发布部署回执。
中断、校验失败或部署后文件变化会阻止启动，重新连接后保护仍有效。
运行中的模型目录禁止覆盖。停止前恢复本会话标定值并断开 XCP，失败会明确报告。
APP 不提供远程编译或“下载 ELF 后再生成 A2L”的步骤。

凭据默认不保存；勾选后仅在成功登录后采用当前 Windows 用户的 DPAPI 加密保存。
取消勾选会删除记忆。重启恢复表单但不自动登录；密文不随交付包复制。
具体实现和测试见 qt_host/credential_store.py 及对应测试。

## 6. XCP 与实时验收

目标默认 XCP on UDP / IPv4 / 17725，DTO 上限 508 字节，外加 4 字节 Ethernet 头。
R2024b 硬件注册显示“XCP on TCP/IP”以引入共享栈，生成钩子替换为 UDP 初始化。
APP 另支持 TCP 通信；不要用 Simulink 注册标签推断模型实际协议。

模型使用 CLOCK_MONOTONIC 绝对时间调度、FIFO、锁内存和单任务执行。
SSH 断开、XCP 断开和 DAQ 启停均不驱动模型步进。
诊断日志 x280_rt_summary 直接报告 model_step 调用与完成次数、间隔、执行耗时、唤醒延迟、超期和跳期。

APP 每信号默认保留 1,000,000 个原始点，1 ms 下约 1,000 秒；满容量后仅淘汰最旧点。
曲线和点显示按可见范围抽样，缩放和游标使用原始数据；CSV 导出完整缓存。
完整运行对比、容差和回放使用 MATLAB 原生 SDI，APP 可导出并打开 SDI 会话。

```powershell
& ./.venv/Scripts/python.exe tools/validate_local_workflow.py `
    --receipts <x280_rt_single的x280_local_build.json> `
    --host 192.168.219.86 --user zh --seconds 30 `
    --output validation/新目录/local_workflow.json
```

该验证在独立远程目录部署唯一 1 ms 模型，启动后断开 SSH、重连检查进程、采样、标定回读与恢复、收集实际计时，最后停止本轮模型。
不会调用目标编译器，不改变原有自启选择。UDP 端口需空闲，不抢占已有程序。
有限测试不构成任意负载下的硬实时保证。脚本结果不代替测试人员签字。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| Ctrl+B 显示旧工具链 | 在当前路径重新注册，执行 configureX280Model 并保存 |
| 找不到编译器 | 核对 portable 包、X280_TOOLCHAIN_ROOT 和工具链完整性 |
| 模型未保存 | 保存自己的修改或使用工作副本，再执行可复现构建 |
| 源码目录不能部署 | 选择 ELF/A2L/manifest 所在 payload |
| 上传中断后无法启动 | 重新完整上传并等待哈希校验成功 |
| ELF 启动即退出 | 查看诊断日志，核对运行库、实时内核、权限、CPU 和端口 |
| SSH 正常而 XCP 不通 | 核对模型已运行、UDP 地址/端口、网络策略和其他 XCP 主站 |
| ELF/A2L 不匹配 | 使用同轮模型、ELF 和生成元数据重新导出 |
| 凭据无法恢复 | 在原 Windows 用户下重新登录保存，不迁移密文 |

本轮证据见 validation 中相应报告；历史远程编译记录仅用于追溯。
