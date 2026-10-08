# COM5 / COM6 RS485 双向测试

测试模型：[simrt_serial_com56.slx](../demos/io/serial/simrt_serial_com56/simrt_serial_com56.slx)。
使用已安装的 `SimRT / Serial` 中的 Setup、Sent、Receive 模块，控制器仍为 1 ms 固定步长，串口两端交替发送。

## 端口与接线

用户已确认 COM3–6 在 BIOS 配置为 RS485，COM5/6 已连接。当前按 ACPI UART 资源顺序使用以下候选映射；**尚未通过有效收发确认实际机壳端口与设备节点对应关系**。

| 模型端口 | Linux 候选设备 | I/O 地址 | ACPI 节点 |
| --- | --- | --- | --- |
| COM5 | `/dev/ttyS6` | `0x210` | `UR13` |
| COM6 | `/dev/ttyS7` | `0x218` | `UR14` |

两端设置为 **115200、8N1、Mode=RS485、RS485Direction=Hardware auto**。Linux 节点编号不等于机壳 COM 编号；确认映射后可修改两个 Setup 的 Device 参数，再按 Ctrl+B 重建。

[标准 ARK-2120F 手册](https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf)的两线 RS485 接法为：DB9 **1 ↔ 1（DATA−）、2 ↔ 2（DATA+）、5 ↔ 5（信号地）**。本轮尚未确认实际针号和转接线映射。手册明确 COM3–5 支持自动方向，COM6 的方向控制仍需实测确认；不能用 RS232 的 2/3 交叉接法替代。

本机两个候选 UART 的 Linux RTS 配置请求均返回 `-25`，当前不能使用 `Linux RTS` 模式。`Hardware auto` 不发送该配置请求，由 BIOS/板卡负责方向控制；该模式能打开串口不等于实际收发已通过。

## 打开和运行

MATLAB R2024b 中运行：

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
setupSimRTLinuxTarget;
open_system('D:/05SimRT/demos/io/serial/simrt_serial_com56/simrt_serial_com56.slx');
```

1. Ctrl+B 在 Windows 本地编译；配套 ELF/A2L/清单位于模型目录的 `simrt_serial_com56_local/*.zip`。使用本轮验证过的 `20261007_122622_445.zip`，或自己重建后生成的整套新 ZIP。
2. APP 连接 SSH，停止当前占用 XCP 端口的模型，把此 ZIP 上传到单独目录并启动；观测页加载同一个 ZIP，连接 UDP 5555。
3. 先查看 `COM5_SetupStatus`、`COM6_SetupStatus`、`COM5_ReadStatus`、`COM6_ReadStatus`，应为 0，`Serial_Ready=1`。若 Setup 为 `-13`，断开后重新连接 SSH，再重启测试模型。本轮已将用户 `zh` 加入 `dialout`，现有旧 SSH 会话需要重连才能获得该权限。
4. 标定 `Serial_Enable=1` 启动互发互收。出厂值为 0，启动模型不会直接发送测试数据。模型里的另外两项反馈初值属于内部参数，保持 0。
5. 停止前先记录计数；`Serial_Enable=0` 会停止发送并清零收发统计。停止模型释放串口。本轮自动测试已恢复原有主模型，未把串口测试模型设为开机自启。

普通桌面仿真不访问 ARK：Setup/Read 返回 `-38`，不会误报硬件成功。模型生成脚本为 [createSimRTSerialDuplexModel.m](../toolchain/simrt_linux_target/createSimRTSerialDuplexModel.m)，已打开的模型须先关闭，再显式使用 `Overwrite=true` 才能重新生成结构。

## 发送内容与判断

每 100 ms 发送一轮：COM5 在第 0 ms 发送，COM6 在第 50 ms 发送，每端每秒 10 帧。每帧 12 字节，包含 `A5 5A` 帧头、源端口号、版本、从 0 开始的小端序号、两字节校验负载及 CRC16-CCITT。部分写入只重发尚未接受的尾部，最多使用 10 ms 写入窗口，避免两端同时发送。

接收器处理帧被拆开、多帧连续到达和帧头前噪声，并分别记录校验、序号及格式问题。

| 观测量 | 含义 |
| --- | --- |
| `COM5_TxFrames` / `COM6_TxFrames` | 驱动已接受的完整发送帧数，不代表对端已收到 |
| `COM5_RxFrames` / `COM6_RxFrames` | 本端收到且通过源、CRC、负载和序号检查的对端帧数 |
| `COM5_LastSequence` / `COM6_LastSequence` | 最近收到的有效序号 |
| `COM5_RxAgeMs` / `COM6_RxAgeMs` | 距离上次有效帧的模型计时；从未收到时自启用起累计 |
| `*_TxFailures`、`*_CrcErrors`、`*_SequenceGaps` | 发送失败、CRC 错误、缺失序号的累计值 |
| `*_Duplicates`、`*_ForeignFrames`、`*_FormatErrors` | 重复或乱序、非对端来源、格式或负载错误 |
| `*_SetupStatus`、`*_ReadStatus`、`*_WriteStatus` | 驱动状态，0 成功，负数为 Linux 错误码 |
| `Serial_Ready` | 驱动可用；暂忙 `-11` 允许后续重试 |
| `Serial_Healthy` | 双向近期有有效接收（间隔小于 250 ms），且各项错误计数为 0 |

通过时 `COM5_TxFrames` 应与 `COM6_RxFrames` 同步增长，反方向同样成立；考虑帧正在传输，瞬时相差 1 帧可接受。**只有 TxFrames 增长、RxFrames 为 0 不能判定成功；错误计数全零也可能只是完全没有接收到数据。**

## 本轮结果与复现

本地逻辑测试、R2024b 桌面仿真、Linux ELF 构建和 APP 解析均已通过。补齐普通用户串口权限后，模型实测约 10 秒，COM5 发送 102 帧、COM6 发送 101 帧，两端接收均为 0，物理互发互收尚未通过。实机数据和权限处理见 [2026-10-07 验收记录](../tests/validation/rs485_com56_20261007/README.md)。

在 MATLAB 中复验模型逻辑、桌面行为及本地构建：

```matlab
addpath('D:/05SimRT/tests/validation/rs485_com56_20261007');
validateSerialDuplex(Recreate=false);
```

该命令不连接实时机。实机脚本在同一验证目录中，按预检记录校验设备占用和原模型身份，短时部署、启用、采样，结束后恢复串口配置与原模型。原模型或实际接线改变后，需先核对并生成新的预检基线，不能直接把本轮报告作为新的硬件成功结论。
