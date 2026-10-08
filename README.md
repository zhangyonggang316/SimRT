# SimRT Linux 实时模型与 XCP 上位机

从 GitHub 克隆后，按 [源码与发布附件说明](docs/GITHUB_DELIVERY.md) 恢复所需 APP、编译器和可选开发工具。

工程按现有组件的职责组织：[上位机 APP](app/README.md)、[Simulink 与编译器](toolchain/README.md)、[Linux 实时系统](linux/README.md)、[共享 Python 服务](shared/README.md)、[测试验证](tests/README.md)、[Demo 工程](demos/README.md)。公共学习说明在 [docs](docs/README.md)，模块边界与目录规则见 [PROJECT_LAYOUT](docs/PROJECT_LAYOUT.md)。

当前唯一 APP：**PySide6 / Qt Widgets + C++ 核心库**，含 UI-05 日志整合。默认模型在 Ubuntu PREEMPT_RT 上以 1 ms 基本周期自主执行，Windows APP 用于部署、观测和标定。

本项目 XCP 标准默认端口统一为 **UDP 5555、TCP 17725**，当前模型使用 UDP。APP 的实际协议和端口仍从匹配的 ZIP/A2L 读取；旧端口模型需重新构建 ELF/A2L/manifest 并选择新 ZIP，不能只改旧清单。目标 IP 优先使用实时机页面非空的“Ubuntu 主机”输入，仅更换 IP 无需重新构建。

“Ubuntu 主机”支持在线编辑目标 IPv4，回车或离开输入框提交后自动保存，重启 APP 会恢复；目标地址与 SSH 密码分别保存，不依赖“记住 SSH 凭据”。在线切换地址时先停止采集、恢复标定并断开旧 XCP 会话，再连接新地址；切换前正在采集时，重连成功后恢复 DAQ。连接切换期间输入只读，失败时查看诊断日志。

"实时机 → 模型部署 → 网络接口 / IPv4"可为目标网口应用并保存静态 IPv4、掩码和可选网关，使用 Netplan + systemd-networkd 持久配置，重启后继续使用；配置失败或 45 秒内未确认时自动回滚运行状态及配置文件。当前支持具有独立 Netplan 定义的网口，DHCP 切换尚未提供。APP 已取消 MATLAB SDI 入口，保留观测、标定、CSV 和图表 PNG 导出。

保存有线静态 IP 时同时启用 `ignore-carrier`，未插网线也会在开机时加载地址。每次 APP 成功连接 SSH 后排队校时，待模型停止、CPU 及各核心连续低负载后使用上位机当前时间和时区；保留 NTP，运行中的模型不会被校时任务停止。实时机屏幕隐藏回环地址和无线网卡的链路本地 IPv6，IP 后显示 MAC。

实时机模型累计运行时间使用小时加剩余秒，例如 `16 h 1430.831 s`，周期及任务耗时仍显示 ms。ARK2120 按 **1 ms ±50 us** 验收：隔离 CPU2/3 物理核心，模型使用 CPU3，后台使用 CPU0/1；默认提前 500 us 唤醒，配合运行期低延迟请求和中断分配。屏幕增加累计越界次数；实测结果、长测进度及回退方法见 [50 us 优化记录](tests/validation/realtime_50us_20261006/README.md)，原始异常和旧版测试继续保留。

硬件、源码、函数、模型和内部标识统一使用 **SimRT**。R2024b 运行 `setupSimRTLinuxTarget` 注册，主模型为 `simrt_rt_single`，工具链为 `SimRT portable-linux-toolchain`。名称迁移后需要更新库链接并重新构建配套产物，详见[迁移步骤](docs/NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)。

## 从这里开始

- 学习与部署：[工程手册目录](docs/README.md)、[技术路线与源码导读](docs/ARCHITECTURE.md)、[新 Windows/MATLAB 与 Linux 部署](docs/NEW_MACHINE_DEPLOYMENT.md)、[故障排查](docs/TROUBLESHOOTING.md)。
- Simulink 功能库：[安装与使用](docs/ARK_IO.md)、[统一目录验收](tests/validation/simrt_library_20261006/README.md)、[ARK 构建验证](tests/validation/ark_io_20261005/README.md)。R2024b 运行 `installSimRTARKLibrary`，库浏览器只有一个 `SimRT` 入口，内含 `Serial`、`Digital IO`、`EtherCAT`、`CAN`、`TCP UDP`；工程内模型和库链接已同步迁移，自有模型需更新库链接并重新构建。ARK 板载 GPIO/DIO 已停止适配，相关模块和模型仅保留作参考，详见使用说明。
- 当前版本：[SimRT 2026.10.07](docs/VERSION_20261007.md)，包含命名迁移、本地构建验证、同步存档位置与恢复说明。
- 串口测试：[COM5/6 RS485 双向模型](docs/RS485_COM56_TEST.md)，115200 8N1、交替发送及 CRC/序号校验；当前物理收发尚未通过，详见实测记录。
- 工程整理：[目录与清理规则](docs/PROJECT_LAYOUT.md)、[本轮清理记录](tests/validation/project_cleanup_20261006/README.md)。
- 运行 APP：[START_APP.cmd](app/START_APP.cmd)；示例入口：[START_DEMO.cmd](demos/Demo_XCP_Qt/START_DEMO.cmd)。工程内 APP 和 Demo 分开存放，启动时不自动连接或启停模型。
- 完整工具链：[Ctrl+B 本地生成与交叉编译、SSH 部署、XCP on UDP](docs/TOOLCHAIN.md)。
- 构建优化：[PolarDriver 对照及已落实改进](docs/POLAR_COMPARISON.md)，包括保留模型 IP、构建前检查、注册去重及 DAQ 配置统一。
- 开发与打包：[Qt 源码与构建](app/qt_xcp_host/README.md)、[复现入口](docs/REPRODUCE.md)。
- 最新验证：[IP 重启保留、校时与启动优化](tests/validation/startup_network_time_20261005/README.md)；前次修复：[IP 保存后自动刷新](tests/validation/network_refresh_20261005/README.md)、[无 IPv4 网口配置](tests/validation/network_unaddressed_20261005/README.md)；模型与端口验证：[UDP 5555、界面与 IP 配置](tests/validation/xcp_5555_ui_20261005/README.md)。
- 需求：[需求说明](需求说明.md)；实时机制与历史边界：[1 ms 方案](docs/1ms_solution.md)。

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/` | 上位机界面及 C++ 核心源码 `qt_xcp_host/`、正式 EXE `distribution/`、启动和发布入口 |
| `shared/` | 无界面的 Python 服务与 XCP 后端，供 APP 和 Linux 维护脚本共用 |
| `toolchain/` | MATLAB 目标与功能库、Linux 交叉编译器、Windows DLL 编译器、开发辅助工具 |
| `linux/` | 实时机控制台、系统调优运行脚本、CPU 隔离及系统配置维护工具 |
| `tests/` | 各模块单元测试、驱动验证、联调脚本、历史证据和工程维护脚本 |
| `demos/` | 主模型、标定示例、串口/CAN 等驱动示例及其生成代码和部署 ZIP |
| `docs/` | 跨模块架构、安装、学习、排障及版本说明 |
| `.python/`、`.venv/`、`.vscode/` | 本机开发环境与工具配置；不能当作跨机器可移植运行包 |

其它三套模型、旧 Tk 界面与启动器、历史非 Qt APP 源码归档均已移除。`shared/python/pyxcp_host` 保留现有服务包名，`shared/python/simrt_xcp` 提供协议后端；共享层不导入 Qt 界面或 MATLAB 工具链。
PyInstaller 的 `build/`、`dist/` 是可再生输出；`SimRT.spec` 是保留的打包入口。正式 APP 仅在交付目录，额外保留最近一次回退副本，其余重复暂存交付可按清理规则移除。

Ctrl+B 完成后，`simrt_rt_single_local/` 仅保留 `<时间戳>.zip`，包内时间戳文件夹仅含 `.elf`、`.a2l`、`.xcp-manifest.json` 三个文件。ZIP 校验成功后删除展开目录和模型目录最外层重复 ELF。APP 内部解压并自动识别，在观测页点击“上线”；协议和端口从文件读取。观测、标定按模型层级显示，单/双游标只测量已勾选并显示的曲线。源码与构建诊断位于 `simrt_rt_single_ert_rtw/simrt_build_evidence/<时间戳>/`。

## 验证边界

1 ms 模型执行、XCP DAQ 上传和界面刷新是不同周期。采用实时内核与 FIFO 调度不等于任意负载下每步都严格相隔 1 ms。
每信号默认缓存 1,000,000 个原始点；显示抽样不改变缓存，CSV 导出完整缓存。网络稳定性、丢样、实际 model_step 间隔应分别验收。
历史模型报告不能自动证明后来修改的 SLX、新链接 ELF 或新版 APP 已完成真机联调。当前 SLX 与既有 payload 的来源以交付清单及本轮说明为准。
