# SimRT 注册名称变更验证

日期：2026-09-19。目标：将 Simulink 注册的硬件名称统一为 `SimRT`，同步现用模型、构建元数据和文档。

结果：`tX280LinuxTarget` 的 10 项测试和 `tX280LocalArtifacts` 的 1 项集成测试全部通过，无失败或跳过。集成测试执行两轮本地构建，验证 ZIP 内仅含 ELF、A2L、JSON，新 manifest 的 `TargetHardware` 为 `SimRT`，配套文件哈希一致，且不留下外层 ELF。

## 修改范围

- 硬件、属性、参数三份注册 XML，注册检查、模型配置和实时配置校验均使用 `SimRT`。
- 新构建的 `xcp-manifest.json` 中 `TargetHardware` 为 `SimRT`。
- 主模型 `x280_rt_single.slx` 与 CAN 示例 `x280_can_loopback.slx` 已保存新名称。
- README、需求说明、技术路线、新机部署、故障排查、工具链和组件文档已同步。历史报告保留原名，并标明当前名称。
- `x280linux`、`x280linuxssh`、函数和文件名、`X280 portable-linux-toolchain` 仍为既有接口名称；`X280 Linux TC1013 CAN` 是模块库名称。

## 验证证据

| 文件 | 说明 |
| --- | --- |
| [models.json](models.json) | 两个模型保存后的实时配置检查；均为 SimRT、1 ms、单任务 |
| [model_comparison.json](model_comparison.json) | SLX 保存前后哈希、变动条目和配置差异 |
| [verify_models.py](verify_models.py) | 比较模型模块、连线、工作区内容的复验脚本 |
| [models_before](models_before/) | 本次变更前的两份模型副本，仅作审计及恢复依据 |
| [matlab_tests.log](matlab_tests.log) | MATLAB 注册测试及实际本地编译集成测试原始日志 |
| [tests.json](tests.json) | 11 项测试的名称、结果及耗时 |

模型配置差异仅包含 `HardwareBoard` 与 `CoderTargetData.TargetHardware` 两个名称。模块和连线、模型工作区、1 ms 步长、IP、XCP 端口及其他配置保持原值。保存模型时 MATLAB 自动更新版本及窗口状态，比较脚本仅忽略这两类非算法元数据。两个模型的端口和连线结构检查均通过。

本轮复用已运行的 MATLAB R2024b 会话；未新开 MATLAB，未连接或部署 Linux 目标机。构建测试使用临时模型副本及临时输出目录。

## 已有环境升级

当前会话已重新注册，硬件列表显示 `SimRT`。其他环境按[新机部署指南的注册与迁移步骤](../../docs/NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)重新注册并更新旧模型配置。

既有 ZIP、构建回执和原始日志保留生成时的名称与哈希。SLX 已更新，后续部署新模型需重新构建，并使用同轮 ZIP 中配套的 ELF、A2L、JSON；本次未将旧产物改写为新构建结果。
