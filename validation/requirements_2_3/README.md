# 具体需求 2 / 3：Simulink 与上位机联调

> 历史记录：本文的 `X280 Linux (SSH)` / `X280 target` 对应当时验证的注册名称，当前统一为 `SimRT`。原始日志和产物保持不变；当前工程使用本地交叉编译，安装与注册以[新机部署指南](../../docs/NEW_MACHINE_DEPLOYMENT.md)为准，旧环境升级后需重新运行 `setupX280LinuxTarget`。

## 当前状态（2026-09-12）

- 上位机已增加实时机资源、模型扫描及受进程身份保护的启停页面。
- MATLAB R2024b Update 6 已成功生成 `x280_integration_demo` 的 C 代码。
- 模型连线检查通过；`app_bundle` 含 23 个 C 源文件及 48 个头文件。
- 原模型 `x280_linux_target/models/x280_calibration_demo.slx` 未覆盖；本目录保存独立联调模型。
- Ubuntu 恢复连接后，已完成源码上传、GCC 原生编译、ELF 回传和匹配 A2L 导出。
- 真机 APP 联调 13 项检查通过：资源与模型发现、UDP 读写、标定响应、恢复、持续采样和停止。
- 已实际检查观测曲线和实时机页面；连续复测约 3 分钟，采样保持活动，曲线缓冲区达到 600 点上限。
- APP 的停止操作先恢复标定并断开 XCP，再停止 ELF；本次模型进程已停止。
- Python 130 项测试及 MATLAB 工具链 8 项离线回归通过。

之前的普通 C 程序 SSH 验证记录见 `python_xcp_host/validation_ssh/report.json`；
它不是本 Simulink 模型的验证结果。本轮真机结果见 `integration_report.json`，
日志见 `app_diagnostics.log`，标定与恢复的 42 个验收样本见 `observation.csv`。

本轮成功目录为 `/home/zh/MATLAB_ws/pyxcp_integration_05418e0400`，
ELF SHA-256 为 `8c309c5d6a369013a8e4a11e3bb73c258fbe447b8d38ce4e676c68a9f2317496`。
首次编译失败的独立目录 `pyxcp_integration_7f3fcda582` 也保留供核查，没有启动程序。
没有删除已有远程项目，也没有修改需求文档或 sudo 配置。

## 验证边界

目标通过 Wi-Fi 连接，实测出现过 pyXCP 的超时自动重试，重试后请求完成；
最终 APP 无错误并保持采样。0.05 秒是请求的轮询间隔，不是确定性的 20 Hz 采集保证。
需要低抖动采集时应使用有线网络并另做时序验收；当前观测为轮询，不是 DAQ。
本测试只覆盖这个单速率示例模型，不能证明任意其他 Simulink 模型或硬件驱动都能直接部署。

## 环境

Windows 端使用本工作区的 Python 3.9.10、pyxcp 0.22.32、MATLAB R2024b、
Simulink Coder、Embedded Coder 和已注册的 X280 Linux (SSH) target。
Ubuntu 端需要 x86-64 Linux、OpenSSH、Python 3、GCC/G++、libc 开发头文件；
本流程不自动安装软件，不使用 sudo，不修改调度权限或全局配置。
UDP 17725 必须可达且没有其他模型占用。

## 1. 生成代码和打包

下面从本目录已保存的联调模型复现。更换输出目录时应使用新的空目录。
在 MATLAB 执行：

```matlab
workspace = 'C:/DataSave/03matlabUbuntu/01AI ToolLinux';
addpath(fullfile(workspace, 'x280_linux_target'));
setupX280LinuxTarget;
out = fullfile(workspace, 'validation', 'requirements_2_3');
open_system(fullfile(out, 'x280_integration_demo.slx'));
previous = Simulink.fileGenControl('getConfig');
Simulink.fileGenControl('set', ...
    'CodeGenFolder', fullfile(out, 'codegen'), ...
    'CacheFolder', fullfile(out, 'cache'), 'createDir', true);
slbuild('x280_integration_demo', 'GenerateCodeOnly', true);
bundle = prepareX280AppBundle('x280_integration_demo', fullfile(out, 'app_bundle'));
```

模型参数 `InputAmplitude`、`CalGain`、`CalOffset` 可标定；
`MeasuredBeforeLimits`、`MeasuredOutput` 为测量量。该测试模型为 0.01 秒单速率离散模型。
`prepareX280AppBundle` 通过结构化 RTW.BuildInfo 和官方 packNGo 收集文件，
不修改 MATLAB 安装目录或原生工具链。附带构建脚本面向这一类无外部库的单速率模型；
它不是任意 Simscape、自定义 S-Function、硬件驱动或第三方库的通用打包器。

## 2. SSH 编译并回传 ELF

恢复 Ubuntu 网络后，在 PowerShell 执行：

```powershell
cd 'C:\DataSave\03matlabUbuntu\01AI ToolLinux\python_xcp_host'
..\.venv\Scripts\python.exe .\validate_integration.py --host 192.168.219.86 --username zh --phase build
```

密码采用隐藏输入，不写进命令行或报告。脚本创建
`/home/zh/MATLAB_ws/pyxcp_integration_<随机标识>`，上传 `app_bundle`，执行
`python3 build_model.py`，下载 `artifacts/x280_integration_demo.elf`。
该 ELF 使用 `-g -fno-pie -no-pie`，便于根据固定的符号地址导出 A2L。
上传/编译/下载调用的就是上位机服务层，同时记录资源和模型发现结果。

也可以在上位机“SSH 部署”完成同样操作：本地源码选 `app_bundle`、
远程目录选独立的 `MATLAB_ws` 子目录、编译命令填 `python3 build_model.py`、
ELF 路径填 `x280_integration_demo.elf`。

## 3. 根据实际 ELF 导出 A2L

保持同一 MATLAB 会话和同一轮代码生成结果，在 ELF 下载成功后执行：

```matlab
exportX280A2L('x280_integration_demo', ...
    OutputFolder=fullfile(out, 'artifacts'), ...
    MapFile=fullfile(out, 'artifacts', 'x280_integration_demo.elf'), ...
    TargetAddress='192.168.219.86');
Simulink.fileGenControl('setConfig', 'config', previous);
```

将生成匹配的 A2L 和带 SHA-256 的 manifest。重新编译、更换源代码或 ELF 后必须重新导出，
不允许拿旧 A2L 对新 ELF 执行标定。若中途失败，也应恢复 `previous` 文件生成配置。

## 4. APP 观测和标定验收

```powershell
..\.venv\Scripts\python.exe .\validate_integration.py --host 192.168.219.86 --username zh --phase observe --ui --review-seconds 60
```

脚本检查 UDP 端口未占用后启动本轮 ELF，连接 UDP 17725，
通过实际上位机窗口加载 A2L、连接及启动曲线。设置输入幅值为 0、偏置为 0.75，
检查输出稳定为 0.75；随后恢复标定并检查波形恢复变化。
结束前再次改写一个标定量并调用 APP 的停止操作，验证恢复、断开和停止的完整顺序，
保留远程源码和产物供核查。
若报告失败，不应视为验收通过；脚本不会停止占用该端口的其他应用。

成功时产物包括 `integration_report.json`、`observation.csv`、`app_diagnostics.log` 和 `artifacts`。
手动操作可在“实时机”选择该模型启动，再到“观测/标定”使用同一个 A2L；
停止模型前由应用自动执行 XCP 断开和会话标定恢复。

## 参考依据

本轮使用已安装 R2024b 的本地官方帮助：`slbuild`、`packNGo`、
`RTW.BuildInfo`、`coder.asap2.export`（MapFile 指定 ELF），以及工作区已有 X280 target。
没有运行 R2025b 专属 API，也没有以回环数据伪造真机测量结果。

真机编译暴露并修复了两个集成问题：构建钩子补入官方 `xcp_ext_mode.c` 适配器；
`exportX280A2L` 向 R2024b 的 ASAP2 导出器传递字符向量路径，避免内部 CodeWriter 类型断言失败。
