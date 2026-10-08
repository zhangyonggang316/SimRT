# SimRT 名称与构建路线迁移

日期：2026-10-07。当前工程统一使用 SimRT 名称，目录、函数、模型、包、宏、环境变量、遥测标识与 APP 导入路径一起迁移。

## 本地验证

| 检查 | 结果 |
| --- | --- |
| Python 目标构建测试 | 40 项通过 |
| 工具测试 | 81 项通过 |
| APP 服务测试 | 191 项通过 |
| Qt 界面测试 | 172 项通过 |
| MATLAB R2024b 测试 | 78 项通过，见 `matlab_tests.json` |
| 主模型与 CAN 模型 | 本地重新生成 Linux ELF、A2L 和 ZIP，见 `matlab_builds.json` |
| R2024b 安装及库浏览器 | 一个 SimRT 根库、五个功能子库、13 个模块，见 `desktop/installation_check.json` |
| Windows Qt 显示 | 1320x820、1000x660 两种尺寸、八个页面，见 `qt_windows/visual_report.json` |
| 打包 APP 启动 | 加载当前模型 ZIP 后保持运行 15 秒，无启动错误日志，见 `packaged_startup.json` |

生成的 APP 位于 `app/distribution/SimRT.exe`。交付模型由 `demos/Demo_XCP_Qt/demo.json` 选择，当前 SHA-256 见其 `package_report.json` 与 `tests/validation/current_selection.json`。本地汇总见 `local_summary.json`。

代码生成和编译仅在 Windows 上进行；SSH 保留部署、运行及状态读取。最初实时机断开，先完成本地验证。用户恢复网络后已补做[实时机回归](../simrt_target_20261007/README.md)：模型周期和功能通过，120 秒 UDP DAQ 有 40 个采样缺口，整体未通过并恢复原模型。未开展长期观察；CAN 硬件不在当前 USB 清单中。

## 重复本地检查

```matlab
addpath('D:/05SimRT/tests/tools/scripts');
validate_simrt_migration;
```

此入口安装库、运行 MATLAB 测试并本地构建两个模型，不连接实时机。仅重新构建可使用 `validate_simrt_migration(BuildOnly=true)`。

## 存档同步

原存档位置 `D:/05SimRT_versions/SimRT_2026.10.06/` 同步当前工程，沿用目录名；归档程序按清单逐文件复读校验 SHA-256。实际文件数量及 ZIP 哈希以该目录 `snapshot_result.json` 为准。

迁移前的完整快照保存在 `D:/05SimRT_versions/pre_migration_20261007/original_archive/SimRT_2026.10.06/`。旧生成目录、过期 APP 和调试缓存移至同级回退目录。历史记录的原始名称和哈希保留用于核对；第三方通用工具、驱动和工具链不做品牌替换。

源码中的解释注释、生成 C、模块 README 及[架构说明](../../../docs/ARCHITECTURE.md)保留供学习和优化使用。
