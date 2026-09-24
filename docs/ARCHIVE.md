# 阶段归档说明

2026-09-16 更新：仅保留 `Demo_XCP_Qt` 中 Python/PySide6 Qt APP 和 `x280_rt_single` 一套 1 ms 模型。旧 Tk 界面、兼容入口、其它三套模型及历史 APP 源码 ZIP 已删除；共享服务和原始测试记录保留。本轮清单见 `validation/single_model_qt_20260916/`。
最新结构见 [工程入口](../README.md)，新工具链及清理验证见 [TOOLCHAIN](TOOLCHAIN.md) 和 `validation/toolchain_20260915/README.md`。
以下为 2026-09-13 的历史归档记录；其中 `Demo_XCP`、四模型交付及 `legacy_reference_sources.zip` 的存在状态不再适用，不作为当前操作入口。

归档版本 1.0，基线日期 2026-09-13，整理跨日于 2026-09-14 完成。本次只整理本地文件与文档，不修改 APP 功能、模型算法、目标机配置或远程进程。

## 归档结构

根目录 [README](../README.md) 为唯一总入口。按四类保存：

| 类别 | 保留位置 |
| --- | --- |
| 需求与说明 | `需求说明.md`、`docs/` |
| 复现文件 | `python_xcp_host/`、`x280_linux_target/`、`tools/`、根 `requirements.txt` |
| 正式交付 | `Demo_XCP/`，仅一份 APP 和四套当前模型 |
| 验收证据 | `validation/`，当前证据与必要历史基线分目录索引 |

源码路径保持不变：MATLAB 硬件注册、共享 Python 导入及工具连接依赖这些路径。`tools` 下三个 MathWorks 仓库、MCP 二进制和 Python 安装介质仍用于本机开发或异机恢复，不属于垃圾文件；说明见 [环境记录](ENVIRONMENT.md)。

`.python`、`.venv`、`.vscode` 是本机环境，保留以免中断开发。分享 APP 只需 `Demo_XCP`；迁移完整工程时不要把 `.venv` 当作跨路径可用的安装包。

## 清理记录与恢复

已将 39 项旧目录/文件移入 Windows 回收站，共 4,568 个文件、216,860,445 字节（约 206.81 MiB），没有永久擦除：

- 旧 MATLAB APP、旧 Python 监控器及早期树莓派示例从根目录移除。
- 重复 PyInstaller 输出、旧 Demo 副本、代码生成缓存、重复普通 bundle、下载副本及日期专用旧打包脚本移除。
- 唯一历史源码、原始模型和必要设计参考先合并成 `history/legacy_reference_sources.zip`，共 199 个文件；压缩后逐文件 SHA-256 校验通过。历史 ZIP 不是当前启动或打包依赖。
- 当前四套 RT 源码、SLX、匹配 ELF/A2L/manifest、全部当前原始验收结果保留。历史失败记录不改写为成功。

清理计划与结果：`history/cleanup_plan_20260913.json`、`history/cleanup_result_20260913.json`。后续测试缓存和 APP 子目录重复说明的清理另记 `history/cache_cleanup_result_20260913.json`；Demo 根目录统一保留正式手册，后续打包也不再复制这些重复说明到 `app/`。

需要恢复被移除的完整旧目录，可在 Windows 回收站按原路径还原；回收站被清空后只能从已有备份恢复。历史 ZIP 和 `history/legacy_reference_manifest.json` 另保留唯一参考材料及条目哈希，不含可再生构建缓存。建议把正式交付、文档及复现源码同步备份到其他存储介质。

## 需求整理边界

需求按环境、工具链、APP、DAQ/SDI、实时运行和交付编号，区分目标、当前实现与验收事实。明文 SSH 密码不保留。

文档中的 100 万点缓存和记住登录凭据目标保留为后续工作；当前 APP 为 10,000 点有界缓存且不持久保存密码。本次归档不扩展功能。Wi-Fi 长测未通过全程无丢样条件、软实时抖动、完整 SDI 的分工均明确保留。

## 完整性与验收

`archive_manifest_20260913.json` 记录归档文件的相对路径、字节数和 SHA-256。覆盖需求、说明、复现源码、交付包、验证材料和工具文件；排除本机 `.python`/`.venv`、供应商 `.git`、可再生 Python 缓存、清单自身及后续 `manifest_verification.log` 校验输出，避免循环哈希。

```powershell
& '.\tools\verify_archive.ps1'
```

校验检查已登记文件缺失或变更，不把以后新增文件自动纳入原基线。完整工程移动后相对路径仍可校验；本机 MATLAB/工具配置需按环境说明重新注册。

本次归档复核记录见 `../validation/archive_20260913/README.md`，与原有真机测试分开。清理的代码生成中间目录可以按 [复现指南](REPRODUCE.md) 在新目录生成；历史报告中的绝对构建路径只代表当时环境，不保证归档后仍存在。
