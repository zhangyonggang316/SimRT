# 2026-10-06 工程清理与版本保存

本轮按“删除临时文件、保存当前版本、保留学习说明”整理；没有重新编译模型或操作目标机。清理前读取 MATLAB 共享会话，所有已加载库均为 stopped、Dirty=off；没有发现运行中的交叉编译任务。

## 清理结果

- 删除 12 个缓存/重复目录或文件，共 47 个文件、6,411,959 字节（6.11 MiB）。
- 8,418 个受保护的源码、正式 APP、模型及交付文件，清理前后 SHA-256 一致。
- 删除失败 0 项，`applied/cleanup_result.json` 中 `passed=true`。
- 清理后再次预览为 0 个候选（`postcheck/cleanup_result.json`）；当前模型 SLX/ZIP 哈希与版本基线一致，更新文档的本地链接检查通过。
- Python 字节码、Simulink `slprj` / `.slxc` 会在后续使用时重新生成。
- 清除了 `20260926_080641_012` 的重复展开模型目录；三个文件均与保留的同名 ZIP 逐文件 SHA-256 一致。

明细：[预览](preview/cleanup_plan.json)、[执行清单](applied/cleanup_plan.json)、[删除文件及哈希](applied/removed_files.json)、[执行结果](applied/cleanup_result.json)。预览文件仅为候选，实际结果以 applied 为准。

## 保留与规则修正

保留正式 APP、最新回退 APP、SLX、Simulink 库、模型 ZIP、生成 C 与构建证据、验证日志/JSON/截图、测试夹具、工具链、SDK/许可证、本机环境和解释说明。历史失败记录也是优化依据，不按日志后缀统一删除。

`tests/maintenance/clean_generated.ps1` 去掉了早期 DIO 生成代码目录与模型产物目录的整目录删除规则，避免今后误删学习材料；补扫交付验证目录内的 Python 缓存。主模型时间戳展开目录只有在三文件与同名 ZIP 完整一致时才可删除；无 ZIP 或内容不同的目录继续保留。

完整归档及恢复校验兼容 Windows 超过 260 字符的证据路径，校验清单按 UTF-8 读取。[长路径和中文文件名校验夹具](long_path_check.json)已通过，保留用于说明路径兼容问题。

## 当前版本

版本标识、完整备份位置、恢复校验、源码阅读路线及尚未通过的验收项统一见 [SimRT 2026.10.06 版本说明](../../../docs/VERSION_20261006.md)。完整快照及生成后的校验回执位于工程之外的 `D:\05SimRT_versions\SimRT_2026.10.06\`，不再向工程内复制一套重复源码或工具链。
