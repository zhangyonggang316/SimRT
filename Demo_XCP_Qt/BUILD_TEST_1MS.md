# 1 ms 模型构建与验收

仅保留 `models/x280_rt_single`。SLX 为模型源文件，编译结果为 `x280_rt_single_local/<时间戳>.zip`，包内一层时间戳目录仅含 ELF、A2L、manifest 三个文件；外部不保留展开副本。
完整操作见 [TOOLCHAIN.md](TOOLCHAIN.md)。所有代码生成、编译、链接和 A2L 导出在 Windows 本地完成。

## 本地重新构建

在 MATLAB R2024b 中执行，输出目录必须尚不存在：

```matlab
projectRoot = 'C:/DataSave/03matlabUbuntu/02AIToolLinux';
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget;
outputFolder = fullfile(projectRoot, 'validation', ...
    ['single_' char(datetime('now','Format','yyyyMMdd_HHmmss'))]);
report = buildX280DemoModels(outputFolder);
disp(report.models.payload);
```

该入口只构建唯一 1 ms 模型，调用本地 `portable-linux-toolchain`，无需连接目标机。
也可打开 SLX，执行 `configureX280Model` 并按 Ctrl+B；模型硬件应为 `SimRT`，编译工具链仍为 `X280 portable-linux-toolchain`。旧开发环境升级后先重新运行 `setupX280LinuxTarget`，再更新并保存模型配置。成功后从生成目录的 `x280_local_build.json` 的 `archive` 获取本轮 ZIP。源码包和报告位于 `_ert_rtw/x280_build_evidence/<时间戳>/`。
只重新编译已有源码时，使用完整工程 `tools/build_local_bundles.py`；新的 ELF 必须使用同轮代码生成元数据重新导出 A2L，不能混用旧 A2L。

## SSH 部署与运行

1. 启动 `START_DEMO.cmd`，默认加载 `demo.json` 指定的结果；重新编译后选择本轮 `x280_rt_single_local/<时间戳>.zip`，由 APP 内部解压校验。
2. 连接 SSH，选择专用远程目录，点击“上传产物”；等待目标端哈希校验成功。
3. 启动 ELF。Ubuntu 需具备 PREEMPT_RT、FIFO 权限、锁内存额度及兼容运行库，无需编译器或 MATLAB。
4. 在观测页检查自动识别的协议、主机和端口，点击“上线”；默认模型使用 UDP 17725。DAQ 周期应为只读的 `0.001 s`。
5. 采集中写入、回读和恢复 `CalOffset`，确认 DAQ 持续；停止 DAQ 不应停止模型。
6. 断开 XCP、恢复标定并停止本次模型，检查日志中的实际 `model_step` 间隔、完成数、超期和跳期。

APP 每信号默认缓存 1,000,000 个原始点。GUI 刷新、DAQ 上传及模型执行是不同周期。
模型在 SSH/XCP 断开时仍自主运行；有限测试结果不等于每步严格无抖动的硬实时保证。

本轮构建和真机证据见 `validation/model_baseline`；Qt 测试见 `validation/qt_ui`。
