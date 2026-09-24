# 1 ms 模型编译与验收

> 历史记录：下文的 `X280 Linux (SSH)` 是当时的硬件注册名称，当前名称为 `SimRT`，编译工具链名称仍为 `X280 portable-linux-toolchain`。保留当时名称以对应原始证据；当前注册与本地构建步骤见[新机部署指南](../NEW_MACHINE_DEPLOYMENT.md)，旧环境升级后需重新运行 `setupX280LinuxTarget`。

默认模型位于 `models/x280_rt_single`，1 ms 多速率位于 `models/x280_rt_multirate`。各目录包含 SLX、`source` 和匹配的 `payload`。
Ubuntu 必须运行 PREEMPT_RT，并已为 SSH 用户配置 FIFO 与锁内存额度。当前验证主机为 `192.168.219.86`、用户 `zh`；不在包内保存密码。

## 使用已有源码重新编译

1. 启动 APP、连接 SSH，选择新的远程工作目录，确认不会覆盖运行中的模型。
2. 本地目录选择 `models/x280_rt_single/source`，上传源码；编译命令为 `python3 build_model.py`，ELF 为 `x280_rt_single.elf`。
3. 下载实际 ELF 到新的测试结果目录。**重新编译后的 ELF 必须重新导出 A2L，不能混用包内旧 A2L。** 导出需要下面同轮 R2024b 代码生成元数据。

## 从 Simulink 重新生成

需要完整工程、Python 3.9.10、MATLAB R2024b、Simulink、Simulink Coder、Embedded Coder 和已注册的 X280 Linux (SSH) 工具链。
在 MATLAB 中创建新的输出目录，不覆盖现有测试记录：

```matlab
workspace = 'C:/DataSave/03matlabUbuntu/01AI ToolLinux';
addpath(fullfile(workspace, 'x280_linux_target'));
setupX280LinuxTarget;
out = fullfile(workspace, 'validation', ['manual_1ms_' char(datetime('now','Format','yyyyMMdd_HHmmss'))]);
mkdir(out);
open_system(fullfile(workspace, 'Demo_XCP', 'models', 'x280_rt_single', 'x280_rt_single.slx'));
assert(strcmp(get_param('x280_rt_single','FixedStep'),'0.001'));
assert(strcmp(get_param('x280_rt_single','EnableMultiTasking'),'off'));
previous = Simulink.fileGenControl('getConfig');
Simulink.fileGenControl('set', 'CodeGenFolder', fullfile(out,'codegen'), ...
    'CacheFolder', fullfile(out,'cache'), 'createDir', true);
slbuild('x280_rt_single', 'GenerateCodeOnly', true);
prepareX280AppBundle('x280_rt_single', fullfile(out,'generated'));
disp(out);
```

保持该 MATLAB 会话与代码生成目录直到 A2L 导出完成。在工程根目录的 PowerShell 中将路径换成上一步 `out`：

```powershell
.\.venv\Scripts\python.exe x280_linux_target/tools/enable_realtime_bundle.py --source '<out>/generated' --output '<out>/source'
```

APP 上传转换后的 `<out>/source`，不是 `generated`；编译命令仍为 `python3 build_model.py`。下载到 `<out>/x280_rt_single.elf`，然后在原 MATLAB 会话中执行：

```matlab
[a2lFile, elfFile, manifestFile] = exportX280A2L('x280_rt_single', ...
    OutputFolder=fullfile(out,'payload'), MapFile=fullfile(out,'x280_rt_single.elf'), ...
    TargetAddress='192.168.219.86');
Simulink.fileGenControl('setConfig', 'config', previous);
```

流程中途失败也应执行最后一行恢复文件生成配置。加载新导出的 A2L，并且仅启动与其匹配的远程 ELF。

## 确认模型实际 1 ms

1. 启动模型，暂不连接 XCP，确认模型进程持续运行。
2. 连接 XCP，选择 `B.MeasuredOutput`，以 DAQ 采集；周期显示 `0.001 s`。默认端口 UDP 17725；被占用时选择空闲端口并在启动参数中同步设置 `-port <端口>`。
3. DAQ 运行期间读写、回读、恢复 `CalOffset`，确认观测不中断。停止观测后模型仍运行；重新开始后继续得到动态信号。
4. 曲线默认保存 10,000 点，在 1 ms 周期下约 10 秒。不要把 GUI 刷新频率当作模型周期。
5. 断开 XCP，再停止本次模型；读取其 `.pyxcp-host.log` 中 `x280_rt_summary`。检查 `period_ns=1000000`、`model_step_interval_mean_ns` 约为 1000000、调用完成数一致，并记录最小/最大间隔、超期、跳期及错误日志。图上横轴或 DAQ 周期本身不足以证明调度达标。

多速率模型替换为 `x280_rt_multirate`，其基本周期仍为 1 ms，`B.SlowSampledOutput` 约每 10 ms 更新。10/100 ms 对照模型分别位于 `models/x280_period_10ms`、`models/x280_period_100ms`，不要修改生成代码的周期常量来冒充不同模型。

本方案是软实时，不保证每一次调用间隔都精确等于 1 ms；实测数据及边界见 `SOLUTION_1MS.md`。
