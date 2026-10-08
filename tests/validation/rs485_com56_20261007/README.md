# COM5 / COM6 RS485 模型与实机测试

日期：2026-10-07。目标：`192.168.193.195` / `ark2120` / `7.0.0-34-realtime`，用户 `zh`。

**软件模型、本地构建和 XCP 观测通过；物理双向通信未通过。** 两端有发送计数，但接收均为 0，不能认为硬件互通正常。操作入口见 [测试说明](../../../docs/RS485_COM56_TEST.md)。

## 交付物

- [测试模型](../../../demos/io/serial/simrt_serial_com56/simrt_serial_com56.slx)，已在 MATLAB R2024b 打开并保存。
- [配套 ZIP](../../../demos/io/serial/simrt_serial_com56/simrt_serial_com56_local/20261007_122622_445.zip)，仅含同轮 ELF、A2L、清单。
- [模型生成脚本](../../../toolchain/simrt_linux_target/createSimRTSerialDuplexModel.m)和 [模型截图](model.png)。
- [本地验证报告](matlab_validation.json)、[APP 导入检查](app_payload.json)、[Hardware 构建按钮检查](hardware_button.json)。

ZIP SHA256：`d5246ae7e0bfc64d0b1f080f0eed361c5c35f9e2a9aadc242214047aefc625f9`。
ELF SHA256：`660c9d4148abd23920a3462b5e80df463017b141ca1bc64e3dbf9e6bb9d89ff5`。

候选 COM5=`/dev/ttyS6`（I/O `0x210`、ACPI `UR13`），COM6=`/dev/ttyS7`（`0x218`、`UR14`）。依据资源排列推断，尚未通过实际数据确认连接器映射。预检确认没有串口占用、串口 getty 或串口控制台；没有发送到 COM1–4，也没有修改 GPIO。

## 验证过程与结果

### 本地软件

[validateSerialDuplex.m](validateSerialDuplex.m) 完成帧 CRC 已知向量、部分写入反馈、有限重试窗口、交替发送、碎片帧、连续帧、CRC 错误、序号丢失及重复/乱序等检查。桌面启用和禁用两种仿真均不伪造硬件成功，Setup/Read 为 `-38`。

本地 `slbuild` 完成真实串口调用的 Linux ELF 构建；APP 的生产 ZIP/A2L 导入服务成功识别 `Serial_Enable` 和 28 个指定观测量。Hardware Build 动作可用。构建阶段没有连接或编译实时机代码。

### 原生驱动预检

使用生产 `simrt_serial.c` 和既有有界物理测试程序，两端 115200 8N1。

| 测试 | 发送字节 | 接收字节 | 结果 |
| --- | --- | --- | --- |
| Hardware auto，ttyS6 → ttyS7 | 256 | 0 | `-110`，接收超时 |
| Hardware auto，ttyS7 → ttyS6 | 256 | 0 | `-110`，接收超时 |
| Linux RTS，先配置 ttyS6 | 0 | 0 | Setup `-25`，方向 ioctl 不支持 |
| Linux RTS，先配置 ttyS7 | 0 | 0 | Setup `-25`，方向 ioctl 不支持 |

每次均验证恢复原 termios 和 Linux RS485 配置。报告为 [正向](physical_test.json)、[反向](physical_reverse.json)、[ttyS6 RTS](physical_test_linux_rts.json)、[ttyS7 RTS](physical_reverse_linux_rts.json)。Linux RS485 标志为 0 不能证明 BIOS 未配置 RS485，两个配置层的含义不同。

### 生成模型与权限处理

第一次普通用户启动，两个 Setup 均返回 `-13`（没有串口访问权限），Read 为 `-9`，在启用发送前终止。保留 [首次失败报告](model_test.json)。

随后将 `zh` **追加**到设备现有的 `dialout` 组，保留其他组；没有修改 `/dev/ttyS*` 的 `0660` 权限。新 SSH 会话已核实对两个设备均有读写权限，详见 [权限变更记录](serial_access.json)。这一组权限变更保留，供后续 APP 启动串口模型使用；旧 SSH 会话需重连。

重新部署最终 ZIP 后，Setup/Read 均为 0，默认 `Serial_Enable=0`。通过 XCP 置 1，采集约 10 秒，再读取计数、置 0、停止模型：

| 项目 | COM5 候选端口 | COM6 候选端口 |
| --- | --- | --- |
| 完整发送帧数 | 102 | 101 |
| 有效接收帧数 | 0 | 0 |
| 发送失败 | 0 | 0 |
| Setup / Read / Write 状态 | 0 / 0 / 0 | 0 / 0 / 0 |
| CRC / 缺序 / 重复 / 非对端 / 格式错误 | 均为 0 | 均为 0 |

`Serial_Ready=1`、`Serial_Healthy=0`。没有收到帧时错误计数为 0 是正常现象，不能作为通过依据。最后一帧计数对应启用后 10.126 秒；两端相隔 50 ms，所以发送计数差 1。

XCP 共收到 10,216 个 DAQ 样本，队列丢样、传输计数缺口和无效帧均为 0。本次模型总运行约 16.519 秒，包含连接和停机阶段；16,520 个周期，无跳周期或 Deadline miss，model_step 间隔为 0.999397–1.000324 ms。仅证明本轮短时、没有实际接收负载的情况，不代替双向负载验收或长期实时性保证。

完整结果见 [权限修复后的实机报告](model_test_after_permissions.json) 和 [目标运行日志](model_test_after_permissions_target.log)。

## 收尾状态与未完成项

已停止测试模型，恢复两个 UART 的原 termios/RS485 状态并逐项比较一致。原 `simrt_rt_single` 已重新启动（本轮恢复 PID 2812），ELF 路径和开机自启配置不变；报告中 `serial_restored`、`previous_model_restored`、`autostart_unchanged` 均为 true，没有清理错误。原模型被重新启动，累计运行时间因此重新计时。

测试包保留在 `/home/zh/MATLAB_ws/com56_test_852f7696/` 供手工复验，没有设为自启。首次失败的独立部署目录 `com56_test_4facc7c0` 保留用于溯源。

还需确认实际 COM5/6 接线为 RS485 的 1↔1、2↔2、5↔5，以及候选 tty 设备与机壳端口对应关系。COM6 自动方向不能仅凭通用手册推定，Linux RTS 配置接口在本机不支持。当前无接收证据，尚不能在接线、映射或硬件方向控制之间确定根因；不把发送返回成功当成收发通过。

复现脚本：[preflight.py](preflight.py)、[run_physical.py](run_physical.py)、[enable_serial_access.py](enable_serial_access.py)、[run_model.py](run_model.py)。这些脚本依赖已保存且与当前 APP 目标一致的凭据，不把密码写入报告。模型测试使用独立部署目录并检查原模型身份，拒绝覆盖已有同名报告。
