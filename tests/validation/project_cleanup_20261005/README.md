# 工程整理：2026-10-05

已删除 53 处过程输出，共 16,804 个文件，2,227,792,742 字节（2,124.59 MiB，约 2.07 GiB）。清理成功，无删除失败；8,123 个受保护文件的哈希核对通过。

本轮清理包括 PyInstaller build/dist/spec、7 个已发布暂存交付目录、过期 APP 备份、Python/Simulink 缓存以及 ARK 联调中首次生成在驱动测试目录的过程构建。最新 ARK 验证模型及结果已集中于 `../ark_io_20261005`。

保留正式 `demos/Demo_XCP_Qt`、主模型及配套历史 ZIP、源码、两套工具链、MATLAB 库、必要测试记录及最新回退副本 `../startup_network_time_20261005_previous_app/app`。

| 记录 | 用途 |
| --- | --- |
| `cleanup_plan.json` | 具体清理目录、文件数和大小 |
| `removed_files.json` | 被移除文件的相对路径、大小与 SHA-256 |
| `cleanup_result.json` | 实际删除结果及保护检查 |

正式 APP SHA-256 保持为 `402a60c6c168bf3cd03503f4da8c620382f65eaba13cd17d647c643ec78fa573`；主 SLX 和选定 ZIP 哈希也与清理前一致。未重打包 APP 或替换正在运行的模型。

执行入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/maintenance/clean_generated.ps1 -Apply -IncludeStagedDeliveries -ReportDirectory D:/05SimRT/tests/validation/project_cleanup_20261005
```

后续执行应选择新的报告目录，避免覆盖本轮记录。规则见 [目录与清理](../../../docs/PROJECT_LAYOUT.md)；根 README、文档索引、需求和 ARK 指南已统一链接。本轮未移动源码目录，以保持已有 MATLAB 注册及历史构建引用。
