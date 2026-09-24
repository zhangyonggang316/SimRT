# Qt XCP Host

双击 `START_DEMO.cmd` 启动新版 APP。整个目录可以移动到其他位置，不能只复制 EXE。
操作与验收步骤见 [Qt 手工验收](MANUAL_TEST.md)，本次交付记录见 `validation/model_baseline` 和 `validation/qt_ui`。

界面采用 PySide6 / Qt 6，原始数据缓存、统计、游标插值和曲线保峰值抽样由 C++ DLL 实现。
界面信息分区沿用原版：顶部连接设置、测量与标定、曲线、部署及目标机状态。
当前只交付 Python/PySide6 Qt APP 和 `x280_rt_single` 一套 1 ms 模型。模型由 Windows 本地 Ctrl+B 生成代码、交叉编译和导出匹配 A2L，再通过 SSH 部署到 Ubuntu 运行。

Simulink 中的实时机注册名称为 `SimRT`。旧开发环境更新后重新执行 `setupX280LinuxTarget`，通过 `configureX280Model(..., Save=true)` 更新模型配置；构建工具链继续名为 `X280 portable-linux-toolchain`。操作步骤见 [工具链说明](TOOLCHAIN.md)。

UI-05：部署与运行日志已统一到“实时机 / 诊断日志”；日志读取、复制、清空显示、保存都在该页。
模型部署页已移除启动参数、刷新状态、读取日志和取消任务控件，ELF 状态由后台自动刷新。

默认预设为 `x280_rt_single`：UDP 17725、Ubuntu `192.168.219.86`、账户 `zh`。
密码运行时输入；可选使用当前 Windows 用户 DPAPI 加密记忆，取消勾选即删除。交付包不含密码。启动 APP 不会自动连接、上传或运行目标模型。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/QtXCPHost.exe` | Qt 版 Windows APP |
| `app/_internal/` | Qt、Python 运行依赖和 C++ 数据核心，必须完整保留 |
| `models/x280_rt_single/x280_rt_single.slx` | 唯一 1 ms 单任务单速率模型 |
| `models/x280_rt_single/x280_rt_single_local/<时间戳>.zip` | 唯一构建结果；内部时间戳目录仅含 ELF、A2L、manifest 三个文件，APP 自动解压校验并加载 |
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

APP 源码统一位于 `qt_xcp_host`，包括 `qt_host` 界面和 `pyxcp_host` 服务。完整工程的 Simulink 中间源码、SLX 快照及构建诊断位于 `_ert_rtw/x280_build_evidence/`，不放入三文件结果目录。
