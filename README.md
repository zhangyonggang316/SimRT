# SimRT Linux 实时模型与 XCP 上位机

当前唯一 APP：**PySide6 / Qt Widgets + C++ 核心库**，含 UI-05 日志整合。默认模型在 Ubuntu PREEMPT_RT 上以 1 ms 基本周期自主执行，Windows APP 用于部署、观测和标定。

Simulink 注册的实时机名称为 **SimRT**，在模型配置的 `Hardware board` 中选择。已有环境更新后先重新运行 `setupX280LinuxTarget`，再通过 `configureX280Model` 更新并保存模型配置，详见[注册与迁移步骤](docs/NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)。源码包名、函数、模型文件名和 `X280 portable-linux-toolchain` 工具链名称保持兼容。

## 从这里开始

- 学习与部署：[工程手册目录](docs/README.md)、[技术路线与源码导读](docs/ARCHITECTURE.md)、[新 Windows/MATLAB 与 Linux 部署](docs/NEW_MACHINE_DEPLOYMENT.md)、[故障排查](docs/TROUBLESHOOTING.md)。
- 工程整理：[目录与清理规则](docs/PROJECT_LAYOUT.md)、[本轮清理记录](validation/project_cleanup_20260919/README.md)。
- 运行 APP：[START_DEMO.cmd](Demo_XCP_Qt/START_DEMO.cmd)。整个交付目录必须一起保留，不自动连接或启停模型。
- 完整工具链：[Ctrl+B 本地生成与交叉编译、SSH 部署、XCP on UDP](docs/TOOLCHAIN.md)。
- 开发与打包：[Qt 源码与构建](qt_xcp_host/README.md)、[复现入口](docs/REPRODUCE.md)。
- 最新整理和验证：[ZIP 唯一输出、模型层级与自动上线](validation/app12_app13_20260919/README.md)；[右键菜单与列表稳定性](validation/zip_app_20260919/README.md)。
- 需求：[需求说明](需求说明.md)；实时机制与历史边界：[1 ms 方案](docs/1ms_solution.md)。

## 目录

| 路径 | 用途 |
| --- | --- |
| `Demo_XCP_Qt/` | 唯一 Qt APP 交付包、`x280_rt_single` 的 SLX 和配套三文件 ZIP；当前工程中的生成代码供调试学习 |
| `qt_xcp_host/` | 唯一 APP 源码目录，包含 Qt 前端、`pyxcp_host` 通信服务、C++ 核心、测试和构建入口 |
| `x280_linux_target/` | R2024b 硬件注册、生成前检查、打包、RT 运行器、UDP 适配与 A2L |
| `tools/` | 本地交叉编译、SSH 联调验收脚本和本机已注册开发工具 |
| `docs/` | 当前工具链、环境及方案文档；`history/` 为必要历史记录，不是 APP 入口 |
| `validation/` | 本轮及历史证据、复现所需的模型生成元数据，不作为旧 APP 分发目录 |
| `.python/`、`.venv/`、`.vscode/` | 本机开发环境与工具配置；不能当作跨机器可移植运行包 |

其它三套模型、旧 Tk 界面与启动器、历史非 Qt APP 源码归档均已移除。原 `python_xcp_host` 共享服务已并入 `qt_xcp_host/pyxcp_host`，根目录不再保留两套 APP 文件夹。
PyInstaller 的 `build/`、`dist/` 和 `.spec` 是可再生输出；完成正式交付后不保留重复 APP 副本。

Ctrl+B 完成后，`x280_rt_single_local/` 仅保留 `<时间戳>.zip`，包内时间戳文件夹仅含 `.elf`、`.a2l`、`.xcp-manifest.json` 三个文件。ZIP 校验成功后删除展开目录和模型目录最外层重复 ELF。APP 内部解压并自动识别，在观测页点击“上线”；协议和端口从文件读取。观测、标定按模型层级显示，单/双游标只测量已勾选并显示的曲线。源码与构建诊断位于 `x280_rt_single_ert_rtw/x280_build_evidence/<时间戳>/`。

## 验证边界

1 ms 模型执行、XCP DAQ 上传和界面刷新是不同周期。采用实时内核与 FIFO 调度不等于任意负载下每步都严格相隔 1 ms。
每信号默认缓存 1,000,000 个原始点；显示抽样不改变缓存，CSV 导出完整缓存。网络稳定性、丢样、实际 model_step 间隔应分别验收。
历史模型报告不能自动证明后来修改的 SLX、新链接 ELF 或新版 APP 已完成真机联调。当前 SLX 与既有 payload 的来源以交付清单及本轮说明为准。
