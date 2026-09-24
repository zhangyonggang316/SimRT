# 复现与开发工具

新机器安装见 [部署指南](../docs/NEW_MACHINE_DEPLOYMENT.md)，源码阅读见 [技术路线](../docs/ARCHITECTURE.md)，日常构建见 `../docs/TOOLCHAIN.md`。主模型为 `x280_rt_single`（1 ms）；构建在 Windows 本地完成。示例地址 `192.168.219.86` 应按实际机器修改，SSH 密码使用隐藏输入。当前证据见 [验收索引](../validation/README.md)。

| 入口 | 用途 |
| --- | --- |
| `../x280_linux_target/buildX280Local.m` | 当前完整入口：本地生成、交叉编译、A2L 配套及 ZIP 发布；也可在 Simulink Ctrl+B |
| `../x280_linux_target/generateX280RealtimeBundle.m` | 分阶段诊断：生成普通及 RT 源码包，无远程操作 |
| `../x280_linux_target/buildX280DemoModels.m` | 构建唯一 1 ms 模型，本地生成代码、交叉编译并导出配套产物 |
| `generate_period_models.m` | 在新目录对已保存的唯一 1 ms 模型生成代码与普通 bundle |
| `build_local_bundles.py` | Windows 本地 portable-linux-toolchain 交叉编译 |
| `validate_local_workflow.py` | 从回执校验并解压 ZIP，再执行 SSH 部署、断连自主运行、DAQ 与标定验收；会启动并停止本轮模型 |
| `../x280_linux_target/tools/enable_realtime_bundle.py` | 将普通 bundle 转为自主 1/10/100 ms RT 源码包 |
| `audit_realtime_target.py` | 读取目标内核、权限、CPU 和系统配置证据 |
| `deploy_realtime_bundles.py` | 历史原生编译诊断工具，不用于当前 APP 构建流程 |
| `export_period_payloads.m` | 用同轮代码生成元数据与本地 ELF 导出 A2L/manifest |
| `validate_model_periods.py` | 唯一 1 ms 模型的自主 step、DAQ、标定及运行时统计检查 |
| `validate_runtime_harness.py` | 当前 RT 调度数学、正常周期、故意超期和停止行为验收 |
| `verify_archive.ps1` | 只读校验指定历史清单；默认旧清单不代表当前文件集 |
| `clean_generated.ps1` | 默认预览可再生输出；`-Apply` 清理并核对正式 APP、模型和源码未被删除/改动 |
| `tests/` | 验证器的本地单元测试，不连接目标 |

`prepare_realtime_target.py` 会改变目标系统配置，`realtime_boot_validation.py` 涉及真实重启和自启状态，`validate_realtime_models.py` 是前一阶段对照验证器。这些工具为历史诊断保留，不是启动 APP 的必要步骤；历史报告不代表当前交付验收，相关旧模型已删除。

开发环境依赖单独保留：`python-3.9.10-amd64.exe`、`matlab-mcp-server-windows-x64.exe`、`matlab-agentic-toolkit/`、`simulink-agentic-toolkit/`、`matlab-mcp-core-server/`。本机注册路径和技能链接仍引用这些文件，不应作为旧 APP 缓存删除；版本见 `../docs/ENVIRONMENT.md`。
