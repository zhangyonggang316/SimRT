# 复现与开发工具

## 目录体积与用途

原根目录 `tools` 在整理前实测约 **922 MiB**，主要来自开发工具，并非模型临时文件。现按职责迁入以下位置，体积为迁移前记录：

| 内容 | 约占用 | 用途 |
| --- | ---: | --- |
| `toolchain/qt_toolchain/` | 804 MiB | LLVM-MinGW，供 `app/qt_xcp_host/build_native.ps1` 编译 Windows APP 的 `xcp_core.dll` |
| `toolchain/development/simulink-agentic-toolkit/` | 42 MiB | Simulink 自动化开发工具与示例 |
| `toolchain/development/matlab-mcp-server-windows-x64.exe` | 31 MiB | MATLAB 自动化连接服务 |
| `toolchain/development/python-3.9.10-amd64.exe` | 28 MiB | Python 安装包，已安装环境运行时不使用此文件 |
| `toolchain/development/matlab-agentic-toolkit/` | 12 MiB | MATLAB 自动化开发工具与示例 |
| `toolchain/development/matlab-mcp-core-server/` | 6 MiB | MATLAB 自动化服务源码与测试 |
| 其余脚本、测试和缓存 | 小于 1 MiB | 工程构建、校验、部署及维护入口 |

模型 Ctrl+B 使用 `toolchain/portable-linux-toolchain/`，与 Windows DLL 编译器不同。已打包的 APP 运行时使用现成 DLL，不读取 `toolchain/qt_toolchain/`；重新编译 DLL 则需要它。VS Code 自动化入口和 MATLAB 工具链注册已同步到新位置。开发工具保留，未作为临时文件删除。

表中入口按文件名查找时，构建辅助脚本在 `toolchain/tools`，系统维护脚本在 `linux/tools`，联调脚本在 `tests/tools/scripts`，快照与清理入口在 `tests/maintenance`。当前模块边界见 [目录说明](PROJECT_LAYOUT.md)。

新机器安装见 [部署指南](NEW_MACHINE_DEPLOYMENT.md)，源码阅读见 [技术路线](ARCHITECTURE.md)，日常构建见 `../docs/TOOLCHAIN.md`。主模型为 `simrt_rt_single`（1 ms）；构建在 Windows 本地完成。示例地址 `192.168.219.86` 应按实际机器修改，SSH 密码使用隐藏输入。当前证据见 [验收索引](../tests/validation/README.md)。

| 入口 | 用途 |
| --- | --- |
| `../toolchain/simrt_linux_target/installSimRTARKLibrary.m` | 为当前 R2024b 用户持久安装 SimRT ARK I/O 库 |
| `validate_ark_library.m`、`check_ark_installation.m` | ARK 库对象、仿真、本地完整构建及新会话路径检查 |
| `inspect_ark_resources.py` | 只读检查 ARK 串口、GPIO 节点及驱动元数据，不操作实际 I/O |
| `../toolchain/simrt_linux_target/buildSimRTLocal.m` | 当前完整入口：本地生成、交叉编译、A2L 配套及 ZIP 发布；也可在 Simulink Ctrl+B |
| `../toolchain/simrt_linux_target/generateSimRTRealtimeBundle.m` | 分阶段诊断：生成普通及 RT 源码包，无远程操作 |
| `../toolchain/simrt_linux_target/buildSimRTDemoModels.m` | 构建唯一 1 ms 模型，本地生成代码、交叉编译并导出配套产物 |
| `generate_period_models.m` | 在新目录对已保存的唯一 1 ms 模型生成代码与普通 bundle |
| `build_local_bundles.py` | Windows 本地 portable-linux-toolchain 交叉编译 |
| `validate_local_workflow.py` | 从回执校验并解压 ZIP，再执行 SSH 部署、断连自主运行、DAQ 与标定验收；会启动并停止本轮模型 |
| `../toolchain/simrt_linux_target/tools/enable_realtime_bundle.py` | 将普通 bundle 转为自主 1/10/100 ms RT 源码包 |
| `audit_realtime_target.py` | 读取目标内核、权限、CPU 和系统配置证据 |
| `export_period_payloads.m` | 用同轮代码生成元数据与本地 ELF 导出 A2L/manifest |
| `validate_model_periods.py` | 唯一 1 ms 模型的自主 step、DAQ、标定及运行时统计检查 |
| `validate_runtime_harness.py` | 上传本地交叉编译的夹具 ELF，校验哈希并检查调度数学、正常周期、故意超期和停止行为；参数 `--executable` |
| `verify_archive.ps1` | 只读校验指定历史清单；默认旧清单不代表当前文件集 |
| `clean_generated.ps1` | 默认预览可再生输出；`-Apply` 清理并核对正式 APP、模型和源码未被删除/改动 |
| `save_version.py` | 完整工程保存到独立版本目录，拒绝覆盖，逐文件校验归档 SHA-256；见[版本说明](VERSION_20261006.md) |
| `tests/` | 验证器的本地单元测试，不连接目标 |

`prepare_realtime_target.py` 会改变目标系统配置。`validate_realtime_models.py` 仅提供当前验证器共用的日志解析与清理函数。原机器专用的重启脚本已移入工程外回退目录。诊断工具不是启动 APP 的必要步骤；历史报告不代表当前交付验收。

开发环境依赖单独保留：`python-3.9.10-amd64.exe`、`matlab-mcp-server-windows-x64.exe`、`matlab-agentic-toolkit/`、`simulink-agentic-toolkit/`、`matlab-mcp-core-server/`。本机注册路径和技能链接仍引用这些文件，不应作为旧 APP 缓存删除；版本见 `../docs/ENVIRONMENT.md`。
