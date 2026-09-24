# TC1013 Simulink CAN 模型库

本目录提供 `CANSetup`、`CanSent`、`CanReceive` 三个 MATLAB System 模块，以及固定步长 **1 ms** 的 CAN1/CAN2 互发互收示例。模型在 Windows 本地生成 C 代码，调用工程自带的交叉编译工具生成 Linux x86-64 ELF，通过现有 Python + Qt APP 的 SSH 部署功能上传运行。

已完成本地代码生成、交叉编译、SSH 部署，以及 TC1013 的 CAN1/CAN2 真实双向回环。经典 CAN 使用 Vehicle Network Toolbox 的 CAN Pack / CAN Unpack；CAN FD 使用同工具箱的 CAN FD Pack / CAN FD Unpack，已验证 64 字节报文。实测记录见工程根目录 `validation/tc1013_can_20260919/`。

## 打开模型库

在工程根目录执行：

```matlab
addpath(fullfile(pwd, 'x280_linux_target'));
setupX280LinuxTarget;
locations = setupX280CANLibrary;
sl_refresh_customizations;
open_system(locations.Library);
open_system(locations.TestModel);
```

环境：MATLAB/Simulink R2024b、Simulink Coder、Embedded Coder；CAN Pack/Unpack 和 `CAN_MESSAGE_BUS` 需要 Vehicle Network Toolbox。自动化模型测试另需 Simulink Test。打开工程或启动 Codex 不会自动执行上述命令。模型硬件选择 `SimRT`；旧环境更新后重新执行 `setupX280LinuxTarget`，再更新并保存模型配置。

- 模型库：`x280_can_library.slx`，Library Browser 名称为 `X280 Linux TC1013 CAN`，这是模块库名称，与实时机硬件名称 `SimRT` 分开。
- 示例：`models/x280_can_loopback/x280_can_loopback.slx`。
- System 对象源码：`../../+x280linux/+can/`。
- Linux 运行时：`src/x280_tc1013_can.c` 和 `.h`。

## 模块接口与参数

| 模块 | 输入 | 输出 | 主要参数 |
| --- | --- | --- | --- |
| CANSetup | 无 | 无 | Channel、CANType、BaudRate、DataBitRate、Termination、SerialNumber、DriverDirectory、SampleTime、HostTransport |
| CanSent | Message、Enable（logical） | Status：int32 | Channel：1 或 2；CANType |
| CanReceive | 无 | Message、Valid（logical）、Status（int32） | Channel：1 或 2；CANType；SampleTime |

每个通道放置一个零端口 `CANSetup`，两个 Setup 在进程内共享同一设备；Channel 分别为 1、2，SerialNumber 和 DriverDirectory 必须一致。默认仲裁波特率 **500 kbit/s**，CAN FD 数据波特率 **2000 kbit/s**，步长 `0.001` 秒，内部终端电阻开启。CANType 选择 `CAN` 或 `CAN FD`；DataBitRate 仅在 CAN FD 下显示。序列号为空时选择第一台设备。参数为编译期配置，修改后重新构建。

经典 CAN 的 Message 使用官方 `CAN_MESSAGE_BUS`：Extended、Length、Remote、Error、ID、Timestamp、Data，Data 为 `uint8[8]`。CAN Pack 勾选总线输出（`BusOutput='on'`）后连接 CanSent；CanReceive 的 Message 连接 CAN Unpack。支持标准帧、扩展帧、远程帧。

CAN FD 使用官方 `CAN_FD_MESSAGE_BUS`，包含 ProtocolMode、Extended、Length、Remote、Error、BRS、ESI、DLC、ID、Reserved、Timestamp、Data，Data 为 `uint8[64]`。支持 ISO CAN FD 的全部合法长度及 BRS/ESI，ProtocolMode=1、Remote=0。两种总线时间戳单位均为秒；同通道的配置和收发模块必须选择相同协议。

普通 MATLAB/Simulink 仿真使用显式 `HostTransport='Loopback'`，CAN1 发送的报文进入 CAN2 软件队列，反之亦然；`Disabled` 模式报告通信禁用。生成的 Linux 代码始终调用 TC1013 驱动，缺驱动或设备时返回错误状态。

## Linux 驱动文件

工程已保存同星官方仓库的 **Linux x86-64 SDK**，来源、固定提交、SHA256 和许可证见 [vendor/SOURCE.md](vendor/SOURCE.md)。当前包的两个核心动态库已安装到：

```text
/home/zh/.local/lib/tscan/
    libTSCANApiOnLinux.so
    libTSH.so
```

`CANSetup.DriverDirectory` 必须与目标机上的绝对目录一致。Windows 的 `libTSCAN.dll`/`libTSH.dll` 不能替代这些文件。目标系统还需具备 SDK 要求的 libusb 运行库和设备访问权限；按同星 SDK 安装说明配置 USB 权限，不要用常驻 root 模型进程代替权限配置。

`prepare_driver.py` 检查两个核心库、ELF 架构和 SHA256，并保留许可证；旧 SDK 若附带 `blf.so`，会一并准备，但当前官方包不要求此库。现有安装目录不会被覆盖。具体命令见 [驱动准备与安装](DEPLOY_DRIVER.md)。驱动通过 SFTP/scp 单独上传；Qt APP 的“上传产物”用于模型三件套。

目标机需要 `libusb-1.0.so.0` 等系统依赖，`ldd` 不能出现 `not found`。当前 SDK 内部依赖工作目录查找库，适配层仅在初始化期间进入 DriverDirectory，配置后恢复模型目录，再启动后台收发。模型无需从驱动目录启动。修改驱动文件前先停止使用该驱动的模型。

当前 ABI 按随库保存的 `vendor/linux/TSCANDef.hpp` 核对，并完成真实设备运行；旧 PDF 中的通道数量查询函数在当前库中不存在，运行时将其作为可选接口。安装与枚举记录见 `validation/tc1013_can_20260919/install_vendor.json`。

## 本地构建与 SSH 部署

```matlab
locations = setupX280CANLibrary;
cd(fileparts(locations.TestModel));
result = buildX280Local(locations.TestModel);
disp(result.payload);
```

该构建只在本地运行，不会连接目标机。`models/x280_can_loopback/x280_can_loopback_local/<构建时间>/` 中仅保留：

```text
x280_can_loopback.elf
x280_can_loopback.a2l
x280_can_loopback.xcp-manifest.json
```

ELF 包含模型代码、CAN 适配层和 XCP 协议栈；厂商 `.so` 独立安装在 DriverDirectory。生成源码和构建证据放在 `_ert_rtw/x280_build_evidence/` 中。A2L 由现有工程的 MathWorks ASAP2 导出流程生成，包含双通道数据、ID、Valid 和 Status 测量变量；System 对象内部状态不会作为 A2L 测量项导出。

本地编译还会生成同级 `<时间戳>.zip`，其中包含时间戳文件夹及上述三个文件；验证打包成功后删除模型目录最外层的重复 ELF。在 `Demo_XCP_Qt/START_DEMO.cmd` 启动的 Qt APP 中选择 ZIP，APP 内部解压校验并读取配套 A2L/JSON，通过 SSH 上传并启动，通过 UDP 17725 采集变量；目标机不需要 MATLAB 或编译器。观察 `CAN1_TxStatus`、`CAN2_TxStatus`、两路 RxStatus、Valid 和 ID；Setup 失败通过该通道收发 Status 持续报告。Qt 当前目录视图只列基础标量，完整数据数组在验收脚本中按 A2L 地址拆成字节并同步 DAQ 采集。

## 接线与预期结果

接硬件后，将 CAN1 与 CAN2 的 CAN_H 相连、CAN_L 相连，并按厂商说明连接信号地。接口针脚以 TC1013 手册为准。该两节点示例默认两个通道各开启一个内部终端电阻；已有外部终端电阻时按实际总线调整，避免重复终端。

| 通道 | 每步发送 | 接收预期 |
| --- | --- | --- |
| CAN1 | 标准 ID `0x101`（257），数据 `[1 2 3 4 5 6 7 8]` | ID `0x202`（514），数据 `[8 7 6 5 4 3 2 1]` |
| CAN2 | 标准 ID `0x202`（514），数据 `[8 7 6 5 4 3 2 1]` | ID `0x101`（257），数据 `[1 2 3 4 5 6 7 8]` |

仅在 `CAN1_Valid`/`CAN2_Valid` 为 true 且对应接收 Status 为 0 时，将解包数据视为本步的新报文。CanReceive 每步最多取一帧，不按 ID 过滤；CAN Unpack 的配置也不能替代应用层 ID 检查。实际 USB 接收有异步延迟，无帧时 Valid 为 false、消息清零；软件回环中的每步成功不代表硬件具有相同到达时序。

模型步进线程仅进行固定容量队列操作并使用 trylock，厂商 SDK 在 SCHED_OTHER 后台线程中执行。发送队列容量 256 帧，每路接收队列容量 256 帧。`CanSent.Status=0` 表示已入队，后续 SDK 发送失败会通过该通道下一次收发调用的 Status 及日志报告；不表示对端已接收。收发拥塞和锁忙均可导致当前帧未入队，应用应按 Status 决定重试或丢弃。

| Status | 含义 |
| --- | --- |
| 0 | 成功；接收是否有新帧还需看 Valid |
| -1 / -2 | 参数无效 / 重复 CANSetup |
| -3 / -4 | 动态库或接口加载失败 / 设备连接或通道配置失败 |
| -5 / -6 | 通道尚未配置 / 队列暂忙，本次发送未入队或本次接收未读取 |
| -7 / -8 | 发送队列已满 / 后台线程启动失败 |
| -9 / -10 / -11 | 接收队列溢出 / SDK 异步发送失败 / SDK 接收失败 |
| -12 / -13 | 两通道设备目录或序列号冲突 / CAN 与 CAN FD 模式不匹配 |
| -14 / -15 | 初始化工作目录操作失败 / MATLAB 软件通信已禁用 |

## 离线验证

从工程根目录运行：

```matlab
addpath(fullfile(pwd, 'x280_linux_target'));
results = runtests({'x280_linux_target/tests/tX280CANObjects.m', ...
    'x280_linux_target/tests/tX280CANLoopback.m'});
assertSuccess(results);
```

底层 C mock 测试使用 `tests/run_offline_tests.ps1`，覆盖两种帧的 ABI、全部 FD DLC、SDK 错误、FIFO、队列溢出、旧令牌、初始化目录恢复和 USB 阻塞隔离，并验证 Linux 交叉编译与链接。

本次通过 49 项 System 对象测试、7 项经典 CAN 模型测试、13 项 SDK 准备测试，以及 C 离线测试。CAN FD 64 字节模型也通过软件回环和本地代码生成。最新三件套路径和实测统计见工程根目录 `validation/tc1013_can_20260919/README.md`。

真实 TC1013 已完成经典 CAN（500 kbit/s、8 字节）及 CAN FD（500/2000 kbit/s、64 字节）双向回环。采集到的有效帧 ID 和全部数据均匹配；已核对模型线程为 SCHED_FIFO、优先级 40、CPU 7，SDK 线程为 SCHED_OTHER，XCP 断开后模型继续运行。运行记录含少量队列忙及部分轮次的 UDP DAQ 间隙，不能据此声称零丢帧或 1 ms 最坏调度抖动达标。测试完成后已停止模型。

USB 权限本次仅对已核对序列号的设备节点授予 plugdev 组读写权限，没有设置全局 USB 规则；重插或重启后需重新检查。
