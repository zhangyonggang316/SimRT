# SimRT 统一库浏览器验收

日期：2026-10-06。环境：Windows、MATLAB/Simulink R2024b Update 10，现有共享桌面会话 `SimRTDesktop`。

## 实施结果

- 项目只注册一个顶层 `SimRT`，内部为 `Serial`、`Digital IO`、`EtherCAT`、`CAN`、`TCP UDP` 五个功能子库。
- `buildSimRTLibrary` 已在 R2024b 生成 `toolchain/simrt_linux_target/drivers/ark/simrt_library.slx`；各模块链接原驱动库。
- `installSimRTARKLibrary` 已执行成功，使用当前用户 `Documents/MATLAB/startup.m` 保存路径注册。
- 原 `simrt_ark_library.slx` 及五个驱动 SLX、内部模块标识保留，旧模型链接无需迁移。独立的 ARK 和 SimRT 浏览器注册入口已移除。

## 真实目录检查

执行命令：

```matlab
addpath('D:/05SimRT/tests/tools/scripts');
check_ark_installation( ...
    ReportFolder='D:/05SimRT/tests/validation/simrt_library_20261006/desktop', ...
    ShowBrowser=true);
```

[完整检查结果](desktop/installation_check.json)中 `passed=true`。检查初始化并刷新真实 Library Browser，通过 R2024b 浏览器组件接口读取目录和模块清单，结果如下：

| 检查项 | 结果 |
| --- | --- |
| 浏览器组件 | 2 个，均通过 |
| 项目顶层目录 | 仅 1 个 SimRT，无独立 ARK 或 SimRT 根目录 |
| Serial | Serial Setup、Serial Sent、Serial Receive |
| Digital IO | DIO Setup、DIO Read、DIO Write |
| EtherCAT | EtherCAT Exchange |
| CAN | CANSetup、CanSent、CanReceive |
| TCP UDP | TCP Setup、TCP Sent、TCP Receive |
| 新入口模块链接 | 13 个，均解析到原驱动库 |
| 原 ARK 库链接 | 6 个，均可解析 |
| 浏览器注册解析错误 | 无 |

本轮验证库结构、安装和当前会话的实际浏览器目录；没有重启 MATLAB，也未对用户模型执行构建、保存或运行。串口电气收发、DIO 硬件能力及实时性不属于本轮库目录验收。
