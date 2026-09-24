# 工程整理与部署文档验证

日期：2026-09-19。本轮按用户要求清理过程文件并编写技术路线、新 Windows/MATLAB 与 Linux 部署、源码导读和故障排查手册。

## 清理结果

- 移除 53 处、4,293 个文件，合计 606,735,888 字节（578.63 MiB）。
- 主要内容：PyInstaller build/dist/spec、两轮暂存交付和旧 APP 备份、工程 Python 字节码及 Simulink 缓存。
- 清理前后校验 7,263 个受保护文件，全部一致。保留正式 APP、11 个模型 ZIP、SLX、源码、两套编译器、SDK、生成代码/描述符和历史原始报告。
- 未移动工程目录，未删除 `.python`、`.venv`、`.vscode` 或正在被注册引用的开发辅助工具。
- `cleanup_plan.json` 是目录清单；`removed_files.json` 记录删除文件的大小和 SHA-256；`cleanup_result.json` 记录实际删除与保护检查。

清理后的二次预览 `postcheck/cleanup_result.json` 没有剩余候选。本次保留的生成元数据与部署 ZIP 有不同用途，详见 [目录与清理规则](../../docs/PROJECT_LAYOUT.md)。

## 文档与修正

- [工程手册](../../docs/README.md)：阅读入口与建议学习顺序。
- [技术路线](../../docs/ARCHITECTURE.md)：Ctrl+B 调用链、XCP/A2L、实时线程、Qt/C++、CAN 和源码映射。
- [新机部署](../../docs/NEW_MACHINE_DEPLOYMENT.md)：上位机环境与两套工具链、Linux SSH/实时权限/自启/CAN SDK、迁移和验收。
- [故障排查](../../docs/TROUBLESHOOTING.md)：错误信息、日志、检查命令和对应实现。
- 修正旧组件 README 中的远程 GCC 主流程、手填端口说明、旧 APP 路径和过期验收入口。
- 修复 `tools/validate_local_workflow.py` 对当前 ZIP 构建回执的兼容：复用 APP 解压校验、检查 ZIP/ELF 哈希与模型身份、退出清理临时目录，继续兼容已有三文件目录。

文档核对时发现的本机路径迁移风险、历史 Linux 配置脚本中的固定用户/UID，以及纯净 MATLAB 安装尚未隔离验收的边界均已写明。

## 验证范围

| 检查 | 结果/证据 |
| --- | --- |
| 清理后的 Qt 与共享服务回归 | 130 + 172 项通过，无失败或跳过；`tests/test_report.json` |
| ZIP 构建回执兼容 | 5 项测试通过；`workflow_tests.log` |
| 真实模型 ZIP、构建回执、文档本地链接 | `project_verification.json`，复验入口 `verify_project.py` |
| 正式 EXE 启动 | `installed_startup.json`；Qt Widgets 与 C++ 核心正常加载 |
| EXE 身份 | SHA-256 `139885a5e927c52e3135c953dac774bbff76f904646cc0691ed7e567317eb934`，本轮没有重建 APP |

本轮没有启动 MATLAB、执行模型编译、连接 Linux、修改实时权限或做 CAN 硬件操作；新机文档依据现有源码、固定版本和已有证据核对，尚未在另一台全新机器完成安装验收。自动验收脚本仅验证本地 ZIP 预检和退出清理，真实 SSH/模型运行仍需在新机按部署手册执行。
