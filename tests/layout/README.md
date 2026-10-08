# 2026-10-07 目录整理与模块解耦

按现有组件职责整理，保留 `qt_xcp_host`、`simrt_linux_target`、驱动和 Demo 的内部结构。原来的五类作为主要导航，额外提取 `shared` 表达 APP 与 Linux 维护工具的共同依赖。依赖图和学习说明见 [PROJECT_LAYOUT](../../docs/PROJECT_LAYOUT.md)。

## 最终边界

| 目录 | 内容与依赖 |
| --- | --- |
| `app` | Qt 界面、C++ 核心、发布包；源码依赖 `shared/python`，运行发布包无需 MATLAB |
| `shared` | 原 `pyxcp_host` 和 `simrt_xcp` 包；不导入 Qt、APP、MATLAB 或测试代码 |
| `toolchain` | MATLAB 注册、功能库、代码生成和编译器；通过 ELF/A2L/manifest ZIP 向 APP 交付 |
| `linux` | 系统配置、调优、控制台；维护脚本使用共享 SSH 服务，目标脚本使用 Python 标准库 |
| `demos` | 原有 SLX、配套 ZIP、生成代码与证据；工程内启动器引用正式 APP |
| `tests` | 单元测试、驱动夹具、联调、历史证据与工程维护工具 |

控制台的 `validate_tmux.py` 随控制台部署，归属 `linux/console`；其单元测试仍在 `tests/linux`。没有为了分类把运行或部署依赖强行拆到测试目录。

## 路径与复现

- 初次移动计划：[move_map.json](move_map.json)；实际执行：[moves_completed.json](moves_completed.json)。
- 共享层及部署资源归位：[followup_moves.json](followup_moves.json)。查旧路径时先按初次映射中最长前缀匹配，再应用后续映射。
- 当前入口：`app/START_APP.cmd`、`app/qt_xcp_host/run.ps1`、`toolchain/simrt_linux_target/setupSimRTLinuxTarget.m`。
- MATLAB 已持久注册新路径，恢复原先打开的三个模型及工作目录，见 [恢复记录](matlab_restored.json)。
- `migrate_project.ps1`、`rewrite_support_paths.ps1`、`relocate_docs.mjs`、`finalize_paths.mjs`、`complete_console_move.ps1` 是本次一次性迁移记录，不要作为日常入口重复执行。

历史 JSON、日志、SLX、ELF 和部署 ZIP 保留原始内容，旧绝对路径是当时构建证据。历史验证目录中的一次性脚本也需核对其当时路径和环境；日常复验使用各模块 README 的维护入口。迁移后第一次模型构建重新生成 Makefile、回执与配套 ZIP。

## 本地验证

| 范围 | 结果 |
| --- | --- |
| MATLAB R2024b | 87 项通过；新路径注册、严格环境检查通过 |
| 完整模型构建 | `simrt_layout_probe` 代码生成、Linux 交叉编译、A2L 与三文件 ZIP 发布通过；构建按钮可用 |
| Qt 与原生核心 | 172 项通过 |
| 共享服务 | 191 项通过 |
| 协议与共享层隔离 | 32 项通过；禁止 GUI/APP/MATLAB 导入时共享模块可加载 |
| Python 工具链 | 42 项通过 |
| CAN SDK 准备测试 | 12 项通过，1 项 Linux 专用测试跳过 |
| 验证工具单元测试 | 81 项通过 |
| Linux 控制台 | 30 项通过 |
| 模块边界回归 | 3 项通过，包括 9 个 Linux 维护入口的 `--help` 检查 |
| Network/CAN/Serial C 夹具 | 离线执行与 Linux 交叉编译通过 |
| APP/Demo | 正式 EXE、新便携包 EXE 启动成功；源码加载主 Demo 和便携 Demo，均识别 6 个观测量、12 个标定量 |
| 维护与文档 | Python 语法检查、PowerShell 解析、当前手册链接检查通过；清理仅运行预览 |

主要证据：[MATLAB 结果](matlab_validation.json)、[APP 与共享服务](../app/shared_results/README.md)、[EXE 与 Demo](../app/layout_results/README.md)、[Python 语法](source_syntax.json)、[文档链接](doc_links.json)。

正式 EXE 未重新编译，SHA-256 保持 `5c8c20fb296672b882d39bb6c1b2d6d283bfdac93b3013e1104cc62d42df2e02`。本次未连接或修改实时机，未启动长期观察；这些结果不新增硬件、RS485 或实时抖动验收结论。

`cleanup_preview/cleanup_result.json` 中 `apply=false`，没有执行清理，`passed=false` 表示该脚本未执行删除校验。自动审批审查拒绝清理便携验证包，原因是 `blocked by policy`，因此 `tests/app/layout_results/portable_package` 保留为验证产物。
