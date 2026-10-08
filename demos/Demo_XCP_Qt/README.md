# SimRT

双击 `START_DEMO.cmd` 启动 SimRT。整个目录可以移动到其他位置，不能只复制 EXE。
操作与验收步骤见 [SimRT 手工验收](MANUAL_TEST.md)，最新验证见 [IP 重启保留、校时与启动优化](validation/startup_network_time_20261005/README.md)，前次修复见 [IP 保存后自动刷新](validation/network_refresh_20261005/README.md)，模型与端口记录见 [UDP 5555、界面与 IP 配置验证](validation/xcp_5555_ui_20261005/README.md)。

界面采用 PySide6 / Qt 6，原始数据缓存、统计、游标插值和曲线保峰值抽样由 C++ DLL 实现。
界面信息分区沿用原版：顶部连接设置、测量与标定、曲线、部署及目标机状态。
当前只交付 Python/PySide6 Qt APP 和 `simrt_rt_single` 一套 1 ms 模型。模型由 Windows 本地 Ctrl+B 生成代码、交叉编译和导出匹配 A2L，再通过 SSH 部署到 Ubuntu 运行。

Simulink 中的实时机注册名称为 `SimRT`。旧开发环境更新后重新执行 `setupSimRTLinuxTarget`，通过 `configureSimRTModel(..., Save=true)` 更新模型配置；构建工具链继续名为 `SimRT portable-linux-toolchain`。操作步骤见 [工具链说明](TOOLCHAIN.md)。

UI-05：部署与运行日志已统一到“实时机 / 诊断日志”；日志读取、复制、清空显示、保存都在该页。
模型部署页已移除启动参数、刷新状态、读取日志和取消任务控件，模型状态由后台自动刷新。APP 已取消 MATLAB SDI 入口，保留 CSV 与图表 PNG 导出。

默认预设为 `simrt_rt_single`：UDP 5555、Ubuntu `192.168.193.195`、账户 `zh`；本项目 XCP 标准默认端口为 UDP 5555、TCP 17725。APP 的实际协议和端口从匹配的 ZIP/A2L 读取，旧端口模型需重新构建并选择新 ZIP，不能只改旧清单或 A2L。
实时机页面非空的“Ubuntu 主机”输入优先作为 SSH 与 XCP 的目标地址，输入为空时 XCP 依次回退到 ZIP、A2L 地址；仅更换 IP 无需重建模型。目标 IPv4 支持在线编辑，回车或离开输入框提交后自动保存，重启 APP 会恢复。切换时先停止采集、恢复标定并断开旧 XCP 会话，再连接新地址；切换前正在采集时，重连成功后恢复 DAQ。连接切换期间输入只读，失败时查看诊断日志。
目标 IP 的保存独立于 SSH 密码，不依赖“记住 SSH 凭据”。密码运行时输入；可选使用当前 Windows 用户 DPAPI 加密记忆，取消勾选仅删除凭据记忆。交付包不含密码。启动 APP 不会自动连接、上传或运行目标模型。

连接 SSH 后，可在“实时机 → 模型部署 → 网络接口 / IPv4”为选定网口应用并保存静态 IPv4、掩码和可选网关。配置经 Netplan + systemd-networkd 持久保存，重启后继续使用；配置失败或 45 秒内未确认时自动回滚运行状态和配置文件。当前支持具有独立 Netplan 定义的网口，保留 Wi-Fi 凭据、IPv6 和其他网口设置；DHCP 切换尚未提供。

有线静态 IP 在未插网线时也会在开机后加载。APP 每次 SSH 连接后会等待模型停止和系统持续低负载，再同步上位机当前时间与时区；保留原有 NTP 配置，不自动停止模型。

2026-10-07 默认模型已更新为 **20261006_180720_528.zip**，模型及内部标识统一为 SimRT。本地代码生成、交叉编译、ELF/A2L 配套哈希及 APP 加载通过。网络恢复后完成 120 秒真机联调：周期 0.999095～1.001059 ms，标定、自主运行和屏幕显示通过，但 UDP DAQ 有 40 个采样缺口，整体未通过，目标机已恢复原模型。当前交付 ZIP 是已测试候选，未作为完整验收通过的运行版本。汇总见 `validation/target_20261007/README.md`；长期观察继续按用户要求暂缓。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/SimRT.exe` | SimRT Windows 上位机 |
| `app/_internal/` | Qt、Python 运行依赖和 C++ 数据核心，必须完整保留 |
| `models/simrt_rt_single/simrt_rt_single.slx` | 唯一 1 ms 单任务单速率模型 |
| `models/simrt_rt_single/simrt_rt_single_local/<时间戳>.zip` | 唯一构建结果；内部时间戳目录仅含 ELF、A2L、manifest 三个文件，APP 自动解压校验并加载 |
| `demo.json` | 默认预设，不含密码 |
| `package_report.json` | 当前交付模型文件 SHA256 清单，历史清单另存验证目录 |
| `validation/model_baseline/` | 原始模型构建和真机记录；以其中 ELF 哈希区分构建轮次 |
| `validation/current_selection.json` | 当前预设对应的三文件目录及哈希；目录整理不代表重新做过真机验收 |
| `validation/qt_ui/` | 目录合并后的 Qt/共享服务回归及 APP 启动记录 |
| `BUILD_TEST_1MS.md`、`SOLUTION_1MS.md` | 唯一 1 ms 模型的构建步骤、运行方案和实测结果 |
| `TOOLCHAIN.md` | Ctrl+B 本地生成与交叉编译、ELF/A2L 配套、SSH 部署和 XCP 验证 |

## 验证边界

Ubuntu 模型的 1 ms 执行周期与 APP 绘图刷新周期分离。界面重构不会改变已归档模型的调度实现。
每信号默认保留 1,000,000 个原始点；显示抽样不改变缓存，CSV 导出完整缓存。模型真机结果与 Qt 回归分别记录，有限短测不代表长期或任意负载验收。

源码、构建依赖与复现入口见完整工程中的 `qt_xcp_host/README.md`。

APP 源码统一位于 `qt_xcp_host`，包括 `qt_host` 界面和 `pyxcp_host` 服务。完整工程的 Simulink 中间源码、SLX 快照及构建诊断位于 `_ert_rtw/simrt_build_evidence/`，不放入三文件结果目录。
