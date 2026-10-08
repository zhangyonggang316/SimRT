# PolarDriver 对照与本地构建验证

日期：2026-10-07。范围：Windows、MATLAB R2024b、SimRT 本地交叉编译与 APP 离线导入。没有连接、停止或重新部署实时机模型。

## 对照依据

只读检查用户提供的 `PolarDriver_V3.2.2.1_Beta(R2022a~R2025b)/PolarDriver.mltbx`。版本 3.2.2.1，共 7639 个归档条目，其中 592 个 `.p` 文件未反编译。没有运行安装器，也没有把 PolarDriver 加到 MATLAB 路径。

包 SHA-256：`46c3eff8dd6663140b7b9cc9a314c514f7dc22e19e5dbeb38c738d8da117cbdc`。

具体文件依据见 [polar_inventory.json](polar_inventory.json)，取舍和实现说明见 [POLAR_COMPARISON.md](../../../docs/POLAR_COMPARISON.md)。当前工具链清单已经记录来源于 PolarDriver 的 R2023b 环境，本轮继续使用 GCC 7.5.0 和 PREEMPT_RT。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| MATLAB 回归 | `tSimRTBuildWorkflow` 8 项、`tSimRTLinuxTarget` 11 项通过 |
| Python 回归 | `test_realtime_bundle.py` 10 项、`test_build_model.py` 31 项通过 |
| 非法周期 | 5 ms 配置在 TLC 生成模型 C 文件前拒绝；检查实际 `slbuild` 路径 |
| 合法模型 | 独立 1 ms 模型完成代码生成、本地编译、链接、A2L 导出与 ZIP 打包 |
| 配置保留 | 不传 Address 构建，模型及 A2L 仍为 `192.168.193.195` |
| Hardware 构建动作 | `buildHardwareBoardAction2` 存在并启用，模型 Dirty 为 off，ExtMode 为 on |
| 注册缓存复用 | MAT 文件哈希及修改时间不变；一次强制刷新 48.45 s，复用 2.81 s |
| 注册缓存恢复 | 将派生 JSON 模拟为不完整内容，setup 自动重建成功；MAT 仅含一个工具链对象 |
| APP 离线导入 | ZIP 校验、ELF 哈希及 A2L 解析通过；6 个测量量、12 个标定量，UDP `192.168.193.195:5555` |
| 源码包契约 | 74 个源码/头文件通过校验；DAQ 为 1024 块，总预留池 1048576 字节，清单与编译定义一致 |

注册时间是本机单次测量，仅反映 setup 的开销，不代表模型总构建时间或目标机运行性能。逐项结果见 [matlab_validation.json](matlab_validation.json)、[registration_cache.json](registration_cache.json)、[cache_recovery.json](cache_recovery.json)。

最终独立模型在 [model_20261007_224249](model_20261007_224249)，部署包为 [20261007_144323_931.zip](model_20261007_224249/simrt_workflow_probe_local/20261007_144323_931.zip)。APP 及源码包检查结果见 [artifact_validation.json](artifact_validation.json)。本次 Simulink 构建阶段报告 18.219 s，不包含整个测试套件、会话连接和 setup 等时间。

## 回归中修正的问题

1. MATLAB 的工具链 MAT 文件只允许保存一个工具链对象，缓存签名已移入独立 JSON。
2. `coder.coverage.BuildHook.entry` 在此构建链中触发得较晚，预检已前移到目标的 `onCodeGenEntry`。
3. DAQ 清单从实际 BuildInfo 定义读取，并按整数序列化，避免科学计数法被 Python 识别为浮点数而拒绝。

早期试验日志和模型保留用于解释修正过程；最终结果以 `matlab_validation.json` 中的 `build` 回执及配套部署包为准。`matlab_validation.log` 为多次运行的追加日志，包含预期的非法周期拒绝记录。

## 复测入口

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
addpath('D:/05SimRT/tests/validation/polar_comparison_20261007');
validate_workflow;
validate_registration_cache;
validate_cache_recovery;
```

```powershell
.\.venv\Scripts\python.exe validation\polar_comparison_20261007\validate_artifacts.py
.\.venv\Scripts\python.exe -m unittest discover -s simrt_linux_target\tests -p test_realtime_bundle.py
.\.venv\Scripts\python.exe -m unittest discover -s simrt_linux_target\tests -p test_build_model.py
```

`validate_artifacts.py` 使用生产 APP 的 `PayloadArchive` 和 `A2LCatalogService`，核对 ZIP、ELF 哈希、信号、标定量及 UDP 端点，并检查生成源码包的 DAQ 清单与编译定义一致。深层验证目录访问使用 Windows 扩展路径，APP 导入仍直接使用普通 ZIP 路径。

上述验证不能替代硬件上的 XCP、RS485 或实时抖动验收；本轮未改变实时内核、调度参数和目标机运行状态。
