# 2026-09-13 更新需求验收

后续状态：已于本日完成实际 RT 重启、开机自启验证和两模型 1 ms 调度测试；发现 XCP 缓冲不足告警，DAQ 无丢样验收仍未完成。以 `../rt_boot_20260913_121920/README.md` 为当前状态，以下保留重启前基线记录。

需求原文未修改。本轮新增范围：需求 2 第 11–16 项、需求 3 联调与 Demo、需求 4 的 PREEMPT_RT / 单任务 1 ms 运行时。

## 状态

已实现：游标旁随动 t/y 测量标签；曲线/采样点；密码专用 SSH；合并“模型部署”；连接主动刷新模型；单模型开机自启配置；观测/标定/图表/模型右键菜单；按模型周期的真实 DAQ，标定不停止 DAQ。

实时目标运行时代码和两个模型已生成、上传、编译、下载并导出匹配 A2L。当前 Ubuntu 仍运行 `6.8.0-90-generic`。机器上已安装 `5.15.129-rt67-intel-ese-standard-lts-rt`，配置确有 `CONFIG_PREEMPT_RT=y`，但本轮没有切换引导或重启。因此“使用 PREEMPT_RT 运行”和“实际开机自启”尚未验收，不能将普通内核基线当作需求 4 完成。

## 真机证据

本轮 Python 回归共 269 项通过：上位机 230、共享后端 27、pyxcp 原生兼容性 5、RT 构建包 7。`python_regression.log` 保存前三组完整结果，compileall 和 pip check 也通过。

- `live_ui_daq_fixed/report.json`：原 10 ms Demo 的桌面联调 19 项检查通过，UDP 17726，4597 个 DAQ 样本，包含采集中写入、恢复、游标与截图。
- `build_report.json`：两个模型在 Ubuntu GCC 编译成功，ELF 回传 SHA-256 一致；`single_payload` / `multirate_payload` 是各自匹配 ELF/A2L/manifest。
- `baseline_validation.json`：19 项基线检查通过。调度夹具 7 个确定性计算用例、非法周期/子任务拒绝，以及故意超时的 200 周期运行均验证。
- 自启选择先设单速率，再切多速率，确认只有一个服务选择，且配置不即时启动模型；结束后恢复原选择。
- 仅停止本轮启动的模型。原先使用 UDP 17725 的模型未被停止。

| 普通内核基线（约 30 秒，不是长期最坏情况保证） | 单任务单速率 | 单任务多速率 |
| --- | ---: | ---: |
| 基本周期 | 1 ms | 1 ms |
| 慢速任务 | 无 | 10 ms |
| 接收 DAQ 样本 | 30009 | 30022 |
| 调度策略 / CPU | FIFO 40 / 7 | FIFO 40 / 7 |
| 内存锁定 | 是 | 是 |
| 最大唤醒延迟 | 487.066 us | 435.769 us |
| 最大循环执行时间（含 XCP） | 412.610 us | 431.105 us |
| 跳过释放 / deadline miss | 0 / 0 | 0 / 0 |
| 接收队列丢样 / 帧序号缺口 | 0 / 0 | 0 / 0 |
| 时间戳 gap / reorder 计数 | 10 / 2 | 8 / 0 |

多速率慢信号相邻相同样本占比约 90%，符合 1 ms 观测 / 10 ms 更新。目标使用仿真时间戳，时间戳异常不能直接解释为网络丢包或墙钟抖动；当前报告不足以定位原因，不宣称全程无丢样。原 10 ms UI 测试也记录 12 个 gap、2 个 reorder，未隐藏。

## 可复现入口

Windows 交付入口：`Demo_XCP/START_DEMO.cmd`，当前指向 `app_20260913/PyXCPHost.exe`。
已实际打开打包程序核对部署页、DAQ 控件和信号右键；窗口保持打开，未替用户连接远程。
EXE SHA-256：`A2463701962315086BA4B0FE50DA2B669A498424D148826B8DB062156B485EA1`。
Demo 原 10 ms payload 与新增 `realtime/single/payload`、`realtime/multirate/payload` 的 ELF/A2L 哈希均已复核。
旧 `app` / `app_current` 保留用于回退。本次仅将 `python_xcp_host/build/PyXCPHost` 构建中间文件移入 Windows 回收站，可恢复；构建警告保留在 `packaging_warnings.txt`。
MATLAB 文件生成配置已恢复为本轮工作前的配置。

工作区 Python 为 `.venv/Scripts/python.exe`，Python 3.9.10。运行命令时在工程根目录；SSH 密码均交互输入，不保存到文件。

```powershell
.\python_xcp_host\run_tests.ps1
.\.venv\Scripts\python.exe -m unittest discover -s x280_linux_target/tests -p test_realtime_bundle.py -v
.\.venv\Scripts\python.exe tools/audit_realtime_target.py --help
.\.venv\Scripts\python.exe tools/validate_realtime_models.py --folder validation/requirements_update_20260913 --seconds 30 --baseline
```

`--baseline` 显式允许普通内核，仅用于对照。RT 内核启动后去掉这个参数再测；默认运行时会拒绝普通内核，且 FIFO 或 mlock 失败会退出，不会静默降级。重新运行验证前检查 UDP 17727、17728 没有其他会话，并保留自己的旧报告。

两个 SLX 位于本目录。均为 R2024b、Fixed-step 0.001、EnableMultiTasking=off；多速率额外零阶保持 SampleTime=0.01。原 Demo SLX 未改动。使用现有 `prepareX280AppBundle` 生成普通 bundle 后，运行：

```powershell
.\.venv\Scripts\python.exe x280_linux_target/tools/enable_realtime_bundle.py --help
```

该工具生成独立 RT bundle，只替换运行时初始化源并增加 `sem_wait` / `sem_post` 链接包装，保留生成的 `ert_main.c` 和模型源码。manifest 保存源文件哈希；不可把旧 ELF 和新 A2L 混用。编译、回传和 A2L 导出继续使用现有工具链。

## 运行时和系统设置

- `CLOCK_MONOTONIC` 绝对周期唤醒，单模型线程，不积压信号量补帧；错过的周期跳过并计数。
- 默认 FIFO 优先级 40，允许 `X280_RT_PRIORITY=1..49`；默认绑定最后一个允许的 CPU，可用 `X280_RT_CPU` 指定。
- `mlockall(MCL_CURRENT|MCL_FUTURE)`，模型栈预触页；SIGTERM 在模型线程边界执行生成的清理，不在信号处理函数内操作 XCP。
- 本轮仅为 zh 配置 `rtprio 80`、`memlock 1048576 KiB`，以及 user@1000 的同等限制；启用 linger。文件路径和改动前内容见 `runtime_setup.json`。
- 未扩大 sudo 权限，未关闭安全更新，未改全局 CPU 隔离或 IRQ 亲和性，未重启现有服务。PAM 限制对新 SSH 登录有效；现有 systemd 用户管理器的新限制需下次启动生效。
- 当前自启选择已恢复原状态。用户单元 `pyxcp-host-model.service` 和 runner 在用户目录中；不接管不属于本应用的同名单元。

## 待重启验收

需用户安排维护窗口并确认重启。保留 generic 内核作为回退，先核对实际 GRUB 引导入口，再一次性启动已安装 RT 内核；目前存在重复 GRUB 菜单，不能盲目写数字索引。重启后核对 `uname -r`、`/sys/kernel/realtime=1`、新用户服务限制，复测两个 1 ms 模型及单模型开机自启。需同时记录负载、最长延迟、超时/跳期，而非仅看平均周期。

参考：[PREEMPT_RT 项目](https://realtime-linux.org/)、[Linux 内核 RT 理论](https://docs.kernel.org/core-api/real-time/theory.html)、[Ubuntu 实时内核启用指南](https://ubuntu.com/real-time/docs/how-to/enable-real-time-ubuntu/)。PREEMPT_RT 不等于任何负载下都保证 1 ms 截止期限。
