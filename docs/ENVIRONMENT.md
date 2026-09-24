# 阶段复现环境

本页记录已使用环境，原归档基线为 2026-09-13，后续 Qt/本地交叉编译变化以现有源码为准。新机安装应按 [新机部署指南](NEW_MACHINE_DEPLOYMENT.md)，不直接复制本机绝对路径或虚拟环境。

## MATLAB 与目标机

- MATLAB 安装：`C:\Program Files\MATLAB\R2024b`。
- 已验证版本：`24.2.0.2923080 (R2024b) Update 6`。
- 已验证许可：Simulink、Simulink Coder、Embedded Coder、MATLAB Coder、Vehicle Network Toolbox。
- 本地交叉编译工具链：`portable-linux-toolchain/portable-linux-toolchain`，Windows GCC 7.5.0、Linux x86-64 sysroot。
- SimRT 目标源码：`x280_linux_target`；MATLAB 中运行 `setupX280LinuxTarget` 注册，异机、迁移或旧名称升级后重新注册，并更新模型的 `HardwareBoard` 为 `SimRT`。

注册工具链为 `X280 portable-linux-toolchain`。Ctrl+B 在 Windows 完成代码生成、交叉编译和 ELF/A2L 配套；目标机不参与编译。原 Linux 远程构建支持包保留用于历史复现，当前标准流程不调用远程构建。

原实验目标为 `192.168.219.86`、用户 `zh`，Ubuntu 22.04.5、内核 `5.15.129-rt67-intel-ese-standard-lts-rt`。需要 OpenSSH/SFTP、Python 3、兼容运行库、PREEMPT_RT、FIFO 调度与锁内存额度；不要求 GCC 或 make。自启功能另需用户 linger。实际内核和权限以每轮审计为准。APP 不隐式安装系统软件、更换内核或修改 sudo 配置。

## Python 与依赖

- 固定 Python `3.9.10`，解释器 `.python/3.9.10/python.exe`，含 Tcl/Tk 8.6。
- 本机虚拟环境 `.venv` 指向此解释器，不能原样跨路径迁移。
- 运行依赖：pyxcp `0.22.32`、paramiko `4.0.0`、matplotlib `3.9.4`。
- 已安装打包器：PyInstaller `6.22.2`，hooks `2026.7`；pip `25.2`。
- 当前 APP 不依赖 MATLAB Engine。既有环境中保留的 MATLAB Engine 24.2 和旧文档工具包不是新环境必装项。
- 根 `requirements.txt` 引用当前 APP 开发依赖；`qt_xcp_host/constraints-archive.txt` 记录 Windows x64 / Python 3.9 的已安装直接与传递依赖版本。
- 本机环境没有因归档而卸载包。Python 版本按工程原约束保留；升级语言、依赖或平台应作为下一阶段重新测试。

安装介质 `tools/python-3.9.10-amd64.exe`，28,909,456 字节，SHA-256：

```text
7391537C87161625F1B82E2A8C543533C75152445F22A58C9B26961911477E76
```

前次检查 Authenticode 有效，签名者为 Python Software Foundation。本归档保留安装器，但未附全套离线 wheel。安装及检查命令见 [复现指南](REPRODUCE.md)。

## MATLAB 开发辅助工具

这些目录仍被本机工具配置和已注册技能引用，保留原路径；它们不是正式 APP 的运行依赖：

| 项目 | 位置 / 版本 |
| --- | --- |
| MATLAB MCP Server | `tools/matlab-mcp-server-windows-x64.exe`，v0.11.2 |
| MATLAB MCP Server Toolbox | R2024b 已启用 0.3.0 |
| 工作区连接配置 | `.vscode/mcp.json`，含本机绝对路径，异机须更新 |
| Simulink MCP 扩展 | `tools/simulink-agentic-toolkit/tools/tools.json` |
| MATLAB Agentic Toolkit | `tools/matlab-agentic-toolkit`，提交 e413e69b8902bd965540dcfee9d6d7e1f747520b |
| Simulink Agentic Toolkit | `tools/simulink-agentic-toolkit`，提交 d1f2fbcbb073cb3f033d8d162663890daf57b33f |
| MATLAB MCP Core Server 源码 | `tools/matlab-mcp-core-server`，提交 c7a39e3967ea96dd0cce517dd297891de017dda2 |

本机 `C:\Users\Administrator\.agents\skills` 中相关 MathWorks 技能通过符号链接引用这里的 Toolkit 源码；移动或删除会破坏链接。无需辅助工具的纯 APP 测试电脑不必安装它们。恢复 Toolkit 时按保留仓库中的 README 和安装说明执行。

## 归档后检查

```powershell
& '.\.venv\Scripts\python.exe' --version
& '.\.venv\Scripts\python.exe' -m pip check
& '.\qt_xcp_host\run_service_tests.ps1'
```

`verify_archive.ps1` 默认检查 2026-09-13 历史清单，不能用来证明当前工程完整；后续正常修改和清理会使旧清单报差异。当前整理记录位于 `validation/project_cleanup_20260919/`。MATLAB 配置、MCP 连接和虚拟环境的机器相关路径需要单独恢复；哈希验证不能替代许可、依赖安装或目标硬件验收。
