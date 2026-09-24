# 归档后本地复核

基线 2026-09-13，复核完成于北京时间 2026-09-14。本轮只操作本地工程，不连接 Ubuntu，不重新运行或更改目标模型、自启、内核及网络配置。

## 检查结果

| 检查 | 结果与证据 |
| --- | --- |
| APP 回归 | 234 项通过，包含 UI 状态、DAQ、标定、部署和 10,000 点缓存；`host_regression.log` |
| 共享后端与 pyxcp 兼容 | 27 + 5 项通过，含本机 TCP/UDP 套接字回环；同上 |
| 验证工具 | 56 项通过；`tools_regression.log` |
| RT 打包 | 10 项通过；`rt_bundle_regression.log` |
| Python 语法和依赖 | `compileall`、`pip check` 通过；当前依赖约束离线 dry-run 无缺失 |
| 从清理后的源码重新打包 APP | `build.ps1` 成功；`build_smoke.log` |
| 从保留的基线重新组装 Demo | `package_demo.ps1` 成功，不依赖已清理代码生成缓存；`package_smoke.log` |
| 正式 Demo 与新组装 Demo | 四套 SLX 存在且与基线一致；各 23 个编译输入存在；四对 ELF/A2L 大小、SHA-256 和固定地址 x86-64 ELF 检查通过；`delivery_integrity.json` |
| 正式 EXE | SHA-256 未变，仍是原阶段已测版本；新构建仅作复现检查，不替换正式 EXE |
| 文档与脚本 | 33 份文档的 99 个本地链接通过；4 份 PowerShell 脚本语法通过；归档校验器匹配、篡改、缺失、越界 4 场景通过；见相应 JSON/日志 |

本轮共 332 项 Python 测试通过。MATLAB 9 项结果保留上一阶段原始证据，本轮没有重新生成代码或重跑 MATLAB 测试；没有新电脑全新安装验收，也没有再次对打包 EXE 做真机 GUI 长测。

PyInstaller 日志仍含 pyxcp 可选 recorder converter 的 `pa` 未定义和 USB 后端不可用提示；当前 APP 使用 Ethernet TCP/UDP，不使用该可选录制转换器或 USB。构建成功不代表这些额外功能得到支持。UI 回归有 Pillow 的弃用告警，未造成测试失败。

## 清理与保留

本轮复现生成的 `package_smoke/`、`python_xcp_host/build/`、`dist/`、`.spec` 和 Python 测试缓存已在检查后移入回收站，保留日志与产物哈希。正式交付仅保留 `../../Demo_XCP/`。清理记录见 `../../docs/history/cache_cleanup_result_20260913.json`。

归档清单为 `../../docs/archive_manifest_20260913.json`，根目录执行 `tools/verify_archive.ps1` 复核。该清单不包含自己、后续生成的校验输出和本机 Python/虚拟环境；校验日志是对清单的独立检查，避免循环哈希。

原真机测试与边界见 [阶段证据索引](../README.md)。复现命令见 [REPRODUCE.md](../../docs/REPRODUCE.md)，清理范围与恢复方式见 [ARCHIVE.md](../../docs/ARCHIVE.md)。
