# 新 Ubuntu 实时机部署与持续验证

目标：`ark2120`，SSH `192.168.219.195`，普通用户 `zh`，Intel Atom D2550，Ubuntu 26.04.1。

本轮按用户最新选择**暂不重启**。已安装的实时内核和当前运行内核分别记录，普通内核上的功能测试不计为 PREEMPT_RT 或 1 ms 最坏时延验收。登录凭据不写入新增脚本或报告。

## 持续验证状态

本轮开始于 2026-09-26 07:39:23 UTC（北京时间 15:39:23），用户要求 AI 处理时间不少于三小时。最早完成时间为 10:39:23 UTC。目标机三小时资源监测另从 07:50:20 UTC 开始；长测结果尚在收集中，不能提前标为通过。

约束与时间记录：[session_plan.json](session_plan.json)。

## 已配置内容

| 项目 | 实际状态与证据 |
| --- | --- |
| 实时内核 | 已安装 `7.0.0-34-realtime`，配置 `CONFIG_PREEMPT_RT=y`；当前仍运行 `7.0.0-30-generic`。见 `kernel_installed.json`、`boot_configuration_review.json`。 |
| GRUB | 默认第 0 项指向 realtime 内核，generic 内核保留。见 `grub_default_review.json`。 |
| Wi-Fi | 现有热点自动连接配置保留；实时内核含当前 MT7601U 无线驱动。当前地址 `.195/24`。 |
| 开机联网等待 | `systemd-networkd-wait-online.service` 已禁用并屏蔽。原启动耗时 2 分 22.667 秒，其中联网等待约 120 秒；优化后的实际开机时间待重启测量。 |
| 实时权限 | 新 SSH 会话 `rtprio=80`、锁内存 1 GiB；用户管理器对应限制已配置，linger 已开启。模型默认 FIFO 40，权限上限与模型优先级不是同一数值。 |
| 本地显示器 | tty1 自动登录普通用户 `zh`。上方黑底、白色标签、青色状态；下方保留六行 Bash 输入。当前 1920x1200 显示器对应 120x37 字符。 |
| 状态采集 | 系统信息读取本机；模型信息来自匹配 manifest 与模型运行器的实际测量。未知、无效、过期数据标为不可用。UI 刷新 1 秒，模型基本周期 1 毫秒。 |
| 命令输入 | 已在实际下方命令行执行标记输出及 `id -un`，确认输出为 `zh` 并保留输入焦点。见 `console_input_check.json`。SSH 仍为普通终端。 |
| 软件包状态 | `dpkg --audit` 无异常；安装内核前停止的 apt 下载服务，其 SIGTERM 失败标志已清除，自动更新计时器仍启用。见 `package_cleanup_check.json`。 |

实际显示器截图：[空闲状态](console_idle_framebuffer.png)。截图直接读取目标机 framebuffer，不是模拟界面。

## 运行器与状态屏验证

- 控制台 18 项测试通过，覆盖状态缺失、陈旧数据、PID 不匹配、模型暂停、初始零步数、退出事件、尺寸变化、控制字符、深层 JSON 和超大整数。
- 运行器的普通执行、主动过载、SIGTERM 与最终统计一致性检查通过，见 `telemetry_diagnostic_result.json`。
- 状态目录只读、状态路径被目录占用两种故障均通过：模型各完成 4000 次调用，仅输出一次错误，无遗留临时文件。见 `telemetry_failure_result_v2.json`。
- `/proc` 和调度 API 确认模型线程为 FIFO 40、固定 CPU 3；状态写入线程为 SCHED_OTHER、优先级 0、CPU 0/1/2。运行器没有把文件写入放入模型实时线程。
- `telemetry_failure_result.json` 保留首次测试脚本错误：它误把 rtprio 权限上限 80 当作模型优先级，并误要求等待主线程避开 CPU 3。修正测试判据后重跑，未因此修改生产调度配置。
- 本轮曾复现 XCP 第二次连接超时，失败记录保留在 `model_soak_90min.json`。修正后结果须另存，不能将此记录改写为通过。

本地构建记录见 [local_build_20260926](../local_build_20260926/README.md)；Qt 分层测试见 [qt](qt/README.md)；UDP 重连回归见 `../udp_reconnect_20260926/`。

## CAN 驱动

原始厂商 SDK 保留在 `/home/zh/.local/lib/tscan`。新系统上的连接崩溃已定位为厂商 `libTSH.so` 对已 detach 的线程对象获取空句柄，然后调用 `pthread_setschedparam`。

独立的一字节修正副本安装于 `/home/zh/.local/lib/tscan-thread-fix-20260926`。修正只调整该指令使用的线程对象地址，受源文件 SHA256 和原指令字节检查约束；其来源及 MIT 许可证均保留。它是本地派生库，**不是厂商发布的修复版本**。当前十次独立连接/断开测试通过，CAN 和 CAN FD 实际收发验证仍在进行。

完整原因、原始与派生哈希、复现方式及调度边界见 [sdk_crash_resolution.md](sdk_crash_resolution.md)。

## 重启后的验证

本轮没有授权重启，不执行重启命令。以后由用户安排重启后，可在 Windows 工程目录运行下列只读检查；它会交互询问 SSH 密码，不重启、不改配置：

```powershell
& ./.venv/Scripts/python.exe tests/validation/new_ubuntu_20260926/target_session.py `
  --script tests/validation/new_ubuntu_20260926/verify_boot.py `
  --output tests/validation/new_ubuntu_20260926/boot_audit_after_reboot.json
```

当前执行同一检查时，除 `realtime_kernel_active` 外其余九项均通过，见 `boot_audit_pending_reboot.json`。重启后还需运行严格模式的主模型及 CAN 测试，确认实际 1 ms 统计、锁内存、FIFO、驱动兼容性、本地自动显示和启动耗时；不能只凭内核包已安装验收这些项目。

## 已部署文件与回退依据

- 状态程序：`/home/zh/.local/lib/simrt-console/`。
- tty1 配置：`/etc/systemd/system/getty@tty1.service.d/90-simrt-console.conf`。
- 本地登录入口：`/home/zh/.profile` 的 `SIMRT LOCAL CONSOLE` 标记段；原 profile 备份于 `/var/lib/simrt/console-before-20260926/profile`。
- 实时权限：`/etc/security/limits.d/90-simrt-zh.conf` 和 `/etc/systemd/system/user@1000.service.d/90-simrt.conf`。
- USB 权限：`/etc/udev/rules.d/70-simrt-tc1013.rules`。
- 配置前后审计：`audit_before.json`、`audit_after_install.json`、`console_before.json`。

回退应只撤销本轮对应配置，保留用户随后修改的内容。终端状态区更新可单独替换上方面板，避免打断下方已输入的命令。
