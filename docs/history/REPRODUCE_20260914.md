# 阶段归档复现指南

> 历史记录：下文的 `X280 target` 指当时的注册名称，当前统一为 `SimRT`；原始日志和产物不改写。当前注册、本地编译和部署步骤以[新机部署指南](../NEW_MACHINE_DEPLOYMENT.md)为准，旧环境升级后需重新运行 `setupX280LinuxTarget`。

适用基线：2026-09-13，Windows x64 / MATLAB R2024b / Python 3.9.10。所有 PowerShell 命令从工程根目录执行。以下远程步骤是供后续复现使用，本次归档没有连接或改动 Ubuntu。

## 1. 直接运行交付包

复制整个 `Demo_XCP`，双击 `START_DEMO.cmd`。不能只复制 EXE；`app/_internal`、`models` 和 `demo.json` 必须一起保留。此方式不需要 Python/MATLAB，只有可选的原生 SDI 分析需要 MATLAB。

按 [手工测试](../Demo_XCP/MANUAL_TEST.md) 操作。启动器不自动连接、上传或启动模型。实验目标为 `192.168.219.86`，用户 `zh`；密码由主机负责人另行提供。目标须满足 PREEMPT_RT、FIFO 与锁内存权限。更换主机后配置实际地址，并核对 SSH 主机指纹。

## 2. 恢复本地开发环境

本机原路径下可继续使用 `.python/3.9.10` 和 `.venv`。虚拟环境不是可移植安装包；工程移到另一目录或电脑后，在新位置创建新的 `.venv`，不要继续使用指向旧路径的环境。

安装本地 Python 的保留介质为 `tools/python-3.9.10-amd64.exe`，安装时包含 Tcl/Tk。默认期望解释器位于 `.python/3.9.10/python.exe`；其他安装位置可将下一条命令中的解释器替换为实际绝对路径。

仅在 `.venv` 不存在时创建；已存在且需要重建时先将旧环境另存，不覆盖活动环境：

```powershell
& '.\.python\3.9.10\python.exe' -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install 'pip==25.2'
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' -m pip check
```

根 `requirements.txt` 只安装当前 APP/打包依赖。`python_xcp_host/constraints-archive.txt` 固定本阶段 Windows x64 / Python 3.9 的实际依赖闭包，不要求旧文档处理库或 MATLAB Engine。Python 安装介质、工具版本、MATLAB 许可和 Toolkit 路径见 [环境说明](ENVIRONMENT.md)。本归档未附所有 Python wheel，不承诺全新离线安装；联网恢复后仍须执行测试。

## 3. 本地回归与 APP 打包

```powershell
& '.\python_xcp_host\run_tests.ps1'
& '.\.venv\Scripts\python.exe' -m unittest discover -s tools/tests -v
& '.\.venv\Scripts\python.exe' -m unittest discover -s x280_linux_target/tests -p test_realtime_bundle.py -v
& '.\python_xcp_host\run.ps1'
```

源码入口为 `python_xcp_host/main.py`，共享后端位于 `x280_linux_target/python`。这些本地测试不需要 SSH；回环测试只绑定本机套接字，不代替真机验收。

重新打包 APP 和基于已保留验收产物创建新 Demo：

```powershell
& '.\python_xcp_host\build.ps1'
& '.\python_xcp_host\package_demo.ps1' -OutputDirectory '.\Demo_XCP_reproduced'
```

第一步生成 `python_xcp_host/dist/PyXCPHost`。第二步默认读取 `validation/model_period_1ms_20260913` 的四套 SLX、RT bundle、payload 和报告；无需依赖已清理的 `codegen`、`downloaded`、普通 bundle 或打包暂存目录。输出目录必须不存在，脚本拒绝覆盖正式 `Demo_XCP`。新构建 EXE 不承诺逐字节复现旧二进制，旧正式 EXE 及 SHA-256 已保留。

## 4. 从 SLX 重新生成四套模型

需要 MATLAB R2024b 和许可、X280 target、通用 Linux 远程构建依赖，以及已准备好的 Ubuntu 实验机。脚本固定实验地址/用户；异机应先调整 `deploy_realtime_bundles.py`、`validate_model_periods.py`、`export_period_payloads.m` 的地址，不能误操作原实验机。

准备一个全新输出目录，不覆盖阶段验收基线：

```powershell
$reproFolder = Join-Path (Get-Location).Path ('validation\repro_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $reproFolder -ErrorAction Stop | Out-Null
$modelNames = @('x280_rt_single', 'x280_rt_multirate', 'x280_period_10ms', 'x280_period_100ms')
foreach ($name in $modelNames) {
    Copy-Item -LiteralPath "Demo_XCP\models\$name\$name.slx" -Destination $reproFolder
}
$reproFolder
```

在 R2024b 中将 `outputFolder` 设置为刚打印的绝对路径。保存其他模型的未保存修改后执行：

```matlab
projectRoot = 'C:\DataSave\03matlabUbuntu\01AI ToolLinux';
outputFolder = "C:\实际复现目录";
addpath(fullfile(projectRoot, 'tools'));
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget;
generate_period_models(outputFolder);
```

脚本检查固定步长、单任务模式及 1/1/10/100 ms 配置，并在新输出目录生成 `cache`、`codegen`、四个普通 `*_bundle` 和 `generation_report.json`。保留本轮中间目录直到 A2L 导出完成。

回到前述 PowerShell 会话，把普通生成包转换为 RT 包：

```powershell
foreach ($name in $modelNames) {
    & '.\.venv\Scripts\python.exe' x280_linux_target/tools/enable_realtime_bundle.py `
        --source (Join-Path $reproFolder "${name}_bundle") `
        --output (Join-Path $reproFolder "${name}_rt_bundle")
    if ($LASTEXITCODE -ne 0) { throw "RT conversion failed: $name" }
}
```

生成模型算法不变；RT 入口实现绝对周期、模型自主步进、普通线程处理网络。不得仅修改运行时环境把 10 ms 模型当成 1 ms 模型。

## 5. Ubuntu 编译、A2L 与真机验证

以下步骤会连接 Ubuntu、上传到新的专用目录并编译/运行测试模型。先取得实验机使用授权，确认目标 PREEMPT_RT 和资源权限，不占用其他人的模型端口。密码经隐藏输入提供。

```powershell
& '.\.venv\Scripts\python.exe' tools/audit_realtime_target.py `
    --output (Join-Path $reproFolder 'target_audit.json')
& '.\.venv\Scripts\python.exe' tools/deploy_realtime_bundles.py --folder $reproFolder
```

检查每条命令成功退出。部署脚本为四个模型分别创建随机远程子目录，生成 `build_report.json` 并下载 ELF 到本轮 `downloaded`。不会自动设置开机自启或重启系统。系统安装/权限配置脚本 `prepare_realtime_target.py` 不属于日常复现步骤，需要主机管理员单独授权。

保持同一轮 MATLAB 代码生成目录，在 R2024b 中执行：

```matlab
export_period_payloads(outputFolder);
```

必须使用刚下载的实际 ELF 导出 A2L。不能拿历史 `build_report.json` 中已经清理的下载路径重新导出，也不能混用不同编译轮次的 ELF/A2L。归档 payload 已成套保留，直接运行旧交付不需要重新导出。

```powershell
& '.\.venv\Scripts\python.exe' tools/validate_model_periods.py --folder $reproFolder `
    --output (Join-Path $reproFolder 'period_validation_first.json') --seconds 30
& '.\.venv\Scripts\python.exe' tools/validate_runtime_harness.py --folder $reproFolder `
    --output (Join-Path $reproFolder 'runtime_harness_current_run01.json')
```

每条命令必须成功退出。报告以新文件独占创建，不覆盖旧证据。模型周期验证分别记录无连接自主运行、DAQ/标定、直接 step 间隔、超期/跳期、网络完整性及清理结果；结束时停止本次启动的测试模型。夹具测试含故意超期，异常计数不能当作零而隐去。

复用已构建 APP，打包这次通过验收的新模型：

```powershell
& '.\python_xcp_host\package_demo.ps1' -ValidationDirectory $reproFolder `
    -OutputDirectory '.\Demo_XCP_new_validation'
```

不要复制旧 GUI CSV 或旧网络日志冒充新测试结果。新轮次 GUI 操作、有线连续采集和人员签字验收按 Demo 手册另做。

## 6. 归档完整性

```powershell
& '.\tools\verify_archive.ps1'
```

校验范围、删除记录及恢复方式见 [归档说明](ARCHIVE.md)。开发后源码或证据有变化，哈希校验失败是预期信号；保留原清单，建立下一阶段的新基线，不覆盖本阶段证据。
