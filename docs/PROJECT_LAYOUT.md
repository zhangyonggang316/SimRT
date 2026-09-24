# 目录与清理规则

## 1. 保留内容

| 目录/文件 | 为什么保留 | 新机是否复制 |
| --- | --- | --- |
| `Demo_XCP_Qt/app/`、启动脚本、`demo.json` | 唯一正式 APP；EXE 依赖 `_internal`，不能只留 EXE | 运行 APP 必须整体复制 |
| 正式 SLX、模型 `_local/*.zip` | 用户模型及可部署的配套 ELF/A2L/JSON | 复制所需模型及选定 ZIP；本工程现有 11 个历史构建 ZIP 保留 |
| `qt_xcp_host/qt_host`、`pyxcp_host`、`native` | Qt 界面、服务、C++ 数据核心源码 | 源码开发需要 |
| `qt_xcp_host/qt_host/native_bin/xcp_core.dll` | 源码运行需要的 Windows 原生库 | 源码运行需要，或用固定编译器重建 |
| `x280_linux_target/` | MATLAB 注册、生成钩子、实时入口、A2L 和 CAN 源码 | 模型开发需要 |
| `portable-linux-toolchain/` | Windows 上生成 Linux ELF 所需的 GCC、binutils、sysroot | 模型编译需要，必须完整复制 |
| `tools/qt_toolchain/` | Windows C++ DLL 编译器 | 重建 DLL 时需要 |
| `tests`、`service_tests`、验证脚本 | 复现行为和定位回归 | 开发需要 |
| `validation/` 的 JSON、日志、截图、测试模型 | 本轮及历史结论的依据 | 可选，但排障与审计建议保留 |
| 第三方 SDK、SOURCE、manifest、许可证 | CAN 依赖及工具链来源记录 | 使用对应功能时保留 |
| `docs/`、各组件 README、需求说明 | 技术路线、部署、排障与需求基线 | 建议复制 |

`qt_xcp_host/pyxcp_host` 是当前 Qt APP 的服务层，不是第二套上位机。CAN 模型位于独立驱动目录，是 1 ms 主模型之外的硬件驱动验证示例。

## 2. 构建元数据与缓存不同

`<model>_ert_rtw/` 保存生成 C、Makefile、`tmwinternal` 代码描述符及最新回执。其 `x280_build_evidence/<时间戳>/` 保存 SLX 快照、RT 源码包、ELF 检查和构建报告；内部三文件缓存用于从 ZIP 定位 ELF 和重新导出 A2L。

这些文件可以通过重新生成代码获得，但**不是本次自动清理对象**：它们用于学习生成代码、解释某轮构建和保持旧 ELF 的同轮元数据。只拿旧 ELF 配上另一次代码生成元数据，并不能正确重建 A2L。删除后应完整构建新一轮 ZIP，不能混用旧文件。

时间戳部署目录已只保留 ZIP；内部证据目录出现 ELF 或源码不违反部署产物只留三文件 ZIP 的约定。

## 3. 可以清理的输出

- `qt_xcp_host/build/`、`dist/`、自动生成的 `.spec`：PyInstaller 构建和待发布结果。确认正式交付已更新后可删，再次发布前重新运行 `build.ps1`。
- 已验证并发布的 `staging_delivery/`、`replaced_app_files/`、旧 EXE 备份：重复交付和替换过程文件。原始测试报告、哈希及发布记录继续保留。
- 工程自己的 `__pycache__/`、`.pyc`：Python 字节码缓存，重新运行自动产生。
- `slprj/`、`.slxc`：Simulink 可再生缓存，重新编译或仿真可能重建。不要在构建或仿真执行期间清理。

`.gitignore` 排除上述常见输出，以及本机环境、编译器、预编译 APP 和生成源码包；正式模型 ZIP 继续保留在 Git 中。忽略规则不会删除本机文件。GitHub 源码仓库与完整本机工作区的差异见[源码获取与依赖准备](SOURCE_CHECKOUT.md)。

## 4. 本机环境与辅助工具

`.python/`、`.venv/`、`.vscode/` 保留以支持当前机器。它们可能含旧绝对路径，不能原样当作新机环境；按 [新机部署指南](NEW_MACHINE_DEPLOYMENT.md) 重建环境并更新配置。

`tools/matlab-agentic-toolkit`、`simulink-agentic-toolkit`、MCP 二进制和源码被当前注册路径/技能链接引用，不作为 APP 缓存删除。它们是开发辅助工具，不是正式 APP 或 Linux 的运行依赖。本次没有启动 MATLAB，也没有修改这些工具的启动配置。

## 5. 清理命令与记录

先预览，再在确认已完成构建/发布后执行。脚本只处理列出的固定重复输出及项目内常规缓存，不会清空任意指定目录。

```powershell
& ./tools/clean_generated.ps1 -ReportDirectory ./validation/cleanup_preview
& ./tools/clean_generated.ps1 -Apply -ReportDirectory ./validation/cleanup_applied
```

报告目录必须在工程内。执行前检查最终绝对路径与符号链接/目录联接；删除仅使用 PowerShell `Remove-Item -LiteralPath`。清理前后比对正式 APP、模型产物及源码哈希，删除失败会记录并返回失败。建议每次选择新的报告目录，保留历史清单。

| 报告 | 含义 |
| --- | --- |
| `cleanup_plan.json` | 每个目标的相对路径、文件数和字节数 |
| `removed_files.json` | 本次选择文件的路径、长度、SHA-256；预览时只是候选，不代表已删除 |
| `cleanup_result.json` | 是否执行、实际移除项、失败项和保护文件检查结果；`apply=false` 的预览不是删除成功报告 |

2026-09-19 已清理 53 处、4,293 个文件、606,735,888 字节（578.63 MiB），7,263 个受保护文件哈希检查通过。明细见 [本轮整理记录](../validation/project_cleanup_20260919/README.md)。后续运行 Python/MATLAB 会重新产生部分缓存，这是正常行为。

本轮不搬迁源码或重命名工作目录，避免破坏 MATLAB 注册、MCP 和旧构建证据中的绝对路径。历史报告所记的已删除缓存/暂存目录只用于溯源，不应作为当前运行入口。
