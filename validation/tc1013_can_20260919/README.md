# TC1013 模型实机验证

验证日期：2026-09-19（北京时间；产物目录采用 UTC 时间）。

已完成：Vehicle Network Toolbox 官方 Pack/Unpack 与自建 CANSetup、CanSent、CanReceive 连接，Windows 本地生成代码、本地交叉编译，经 SSH 上传三件套，在 Linux 实时机运行，并通过 XCP DAQ 核对 CAN1/CAN2 物理双向回环。

## 模型与产物

- [正式 1 ms 测试模型](../../x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback.slx)
- [模型库](../../x280_linux_target/drivers/tc1013/x280_can_library.slx)及[使用说明](../../x280_linux_target/drivers/tc1013/README.md)
- [最终经典 CAN 三件套](../../x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback_local/20260918_172542_635/)
- [CAN FD 64 字节验收模型快照](x280_canfd_loopback.slx)及[配套三件套](x280_canfd_loopback_local/20260918_171728_241/)
- [正式模型截图](model_can.png)、[零端口 CANSetup 模型库截图](library.png)

每个三件套目录仅包含 `.elf`、`.a2l`、`.xcp-manifest.json`。ELF 由工程自带 GCC 7.5 交叉工具链在 Windows 构建，A2L 来自 MathWorks `coder.asap2.export` 流程；JSON 记录 ELF/A2L 的 SHA256。目标机未参与代码生成或编译。正式模型已清除旧 Device 端口留下的悬空连线，model_check 为 healthy。

## 实测结果

目标：`192.168.219.86`，Ubuntu 22.04.5、x86_64、PREEMPT_RT。设备：TC1013 / TOSUN HS CANFD2，USB `5453:0001`，序列号 `37AFCA2612ADBF35`。

| 项目 | 经典 CAN 最终模型 | CAN FD 验收快照 |
| --- | --- | --- |
| 波特率 | 500 kbit/s | 仲裁 500、数据 2000 kbit/s，BRS 开启 |
| 每帧长度 | 8 字节 | 64 字节 |
| 模型固定步长 | 1 ms | 1 ms |
| DAQ 采样跨度 | 6.052 s | 6.026 s |
| 收到 DAQ 样本 | 6053 | 6014 |
| CAN1 接收有效帧 | 6052 | 6013 |
| CAN2 接收有效帧 | 6053 | 6012 |
| ID / 全部字节不匹配 | 0 / 0 | 0 / 0 |
| SDK 收发错误、队列溢出 | 0 | 0 |
| 队列暂忙 Status=-6 | CAN1 TX 2 次、RX 1 次；CAN2 TX 1 次 | CAN1 TX 3 次、RX 1 次 |
| UDP DAQ 时间戳间隙 | 0 | 13 个采样周期 |
| XCP 断开后仍运行 | 是 | 是 |
| 到设定 StopTime 后退出 | 是 | 是 |

CAN1 发送标准 ID `0x101`，数据为 `1..N`；CAN2 发送 `0x202`，数据为 `N..1`。验收使用模型事件同步 DAQ，只有 Valid=true 的帧参与接收数据匹配，逐字节检查官方 Unpack 输出。

两次运行都核对了 `/proc`：模型线程为 SCHED_FIFO、优先级 40、绑定 CPU 7；主线程及 SDK/USB 工作线程为 SCHED_OTHER。初始化后的工作目录恢复为模型部署目录。以上证明调度配置生效，不代表最坏抖动达标。

完整报告：[经典 CAN](hardware_can_clean.json)、[CAN FD](hardware_canfd.json)。原始 DAQ 样本保存在同名 `.samples.jsonl.gz` 中。较早的 `hardware_can*.json` 为调试轮次，最终经典 CAN 结果以 `hardware_can_clean.json` 为准。

局限：存在队列忙，发送返回 -6 的该步不会入队；FD 测试存在 DAQ 间隙，因此这些计数不能当作总线零丢帧证明。尚未执行长期耐久、过载和最坏调度延迟验收。SDK 生命周期期间没有获得可用的模型 stdout 时序汇总，未据此报告执行耗时或抖动数值。

## 驱动与离线检查

两个官方 `.so` 已按 SHA256 安装到 `/home/zh/.local/lib/tscan`，许可证和来源一并保留，见 [安装记录](install_vendor.json)、[安装说明](install_vendor.md)。厂商 SDK 依赖初始化工作目录，运行库已处理进入与恢复；`blf.so` 和旧通道数量查询符号为可选。

当前 USB 节点仅改为 `root:plugdev`、保留 `0664`，zh 已有该组成员资格。重插或重启后需复查权限；未配置全局 USB 规则，模型以 zh 运行。

- 49 项 MATLAB System 对象测试通过，包含 CAN FD 全部合法长度和 DLC。
- 7 项正式经典 CAN 模型测试通过，检查零端口 Setup、执行优先级、官方 Pack/Unpack 引用及 1 ms 双向软件回环。结果保存在 `matlab_tests.mat`。
- CAN FD 64 字节官方 Pack/Unpack 模型完成 21 个软件回环采样点的 ID、数据、Valid、Status 检查，并通过本地代码生成。
- 13 项 SDK 准备工具测试通过；许可证经过准备、安装两阶段仍保留。
- [C 驱动离线测试及 Linux 交叉链接](../tc1013_canfd_20260919/runtime_offline_tests.json)通过，覆盖 ABI、错误清理、队列、所有权和工作目录恢复。

## 复验

在工程根目录执行下列命令，会上传并启动模型、发送 CAN 报文、采集后停止。硬件须保持 CAN1/CAN2 正确相连，两个通道使用匹配的波特率与终端配置。

`target_probe.py`、`install_vendor.py` 和 `verify_model_hardware.py` 从 `SIMRT_SSH_PASSWORD` 环境变量读取密码；变量缺失或为空时直接报错，不连接目标机。默认主机为 `192.168.219.86`，用户名为 `zh`，可用 `SIMRT_SSH_HOST` 和 `SIMRT_SSH_USERNAME` 覆盖。不再从需求文档读取密码，也不要把实际密码写入命令、脚本或版本库。以下 PowerShell 命令交互输入密码，仅为本次运行设置环境变量，结束后清除：

```powershell
$credential = Get-Credential -UserName 'zh' -Message 'SimRT SSH'
$env:SIMRT_SSH_USERNAME = $credential.UserName
$env:SIMRT_SSH_PASSWORD = $credential.GetNetworkCredential().Password
try {
    .\.venv\Scripts\python.exe validation/tc1013_can_20260919/verify_model_hardware.py x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback_local/20260918_172542_635 --output validation/tc1013_can_20260919/hardware_can_repeat.json
} finally {
    Remove-Item Env:SIMRT_SSH_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:SIMRT_SSH_USERNAME -ErrorAction SilentlyContinue
    $credential = $null
}
```

也可通过 `Demo_XCP_Qt/START_DEMO.cmd` 启动现有 Python + Qt APP，选择经典 CAN 三件套目录上传、启动，并连接 UDP 17725。没有新增第二套上位机 APP。测试脚本复用同一套 SSHDeployment、A2LCatalogService、XcpSession；完整数组按 A2L 地址展开为字节供 DAQ 校验。

最新经典 CAN 远程部署目录为 `/home/zh/MATLAB_ws/x280_can_loopback_20260918_172735/`，本次测试完成后进程已停止，未设置开机自启。
