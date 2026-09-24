# PREEMPT_RT 重启验收

Windows 记录时间：2026-09-13。用户已确认重启；SSH 恢复连通后执行一次 `sudo -n shutdown -r +0`。

## 已确认

- 运行内核：`5.15.129-rt67-intel-ese-standard-lts-rt`，`/sys/kernel/realtime=1`。
- Boot ID 从 `efe7183a-8b51-479f-939d-838e9a57e60a` 变为 `0c0cc3ce-7590-44e7-9538-fedd1311a0b8`，证明发生实际重启。
- `pyxcp-host-model.service` 在本次开机启动单速率测试模型，MainPID 830，路径、参数、进程起始标记一致。未手动启动前通过 UDP 17727 采集 4916 个样本，模型周期 1 ms。
- 进程观测：模型线程 FIFO 40、CPU 7，锁定内存 4776 KiB；用户服务限制 rtprio 80、memlock 1 GiB。
- 完成启动验证后停止服务，再分别运行单/多速率模型；采集期间标定写入与恢复保持 DAQ 运行。
- 测试结束无本次 ELF 遗留运行。原自启为禁用，选中多速率模型但不自启；原 JSON、unit、runner 内容与权限均恢复并逐项比较一致。

## 调度结果

均为约 30 秒的软实时观察，不是长期最坏情况或硬实时保证。

| 指标 | 单任务单速率 | 单任务多速率 |
| --- | ---: | ---: |
| 基本周期 | 1 ms | 1 ms |
| 慢速率 | 无 | 10 ms |
| 接收样本 | 30008 | 29995 |
| 最大唤醒延迟 | 368.400 us | 362.265 us |
| 最大循环执行时间（含 XCP） | 181.008 us | 79.591 us |
| deadline misses / skipped releases | 0 / 0 | 0 / 0 |
| Ethernet 序号缺口 | 0 | 0 |
| 时间戳 gap / reorder | 10 / 2 | 8 / 0 |
| 目标 XCP 无内存错误 | 30027 | 8 |

多速率保持输出相邻重复约 90%，符合 1 ms 观测 / 10 ms 更新。故意超期夹具在 RT 内核上记录 10 次 deadline miss、18 个跳过周期，没有将超期隐藏。

## 未解决事项

1. **DAQ 完整性未通过无丢样验收。** 目标日志有 `extmodeEvent error: code -10` / `rtExtModeUpload error: code -10`；生成代码 `ext_mode.h` 将 -10 定义为 `EXTMODE_NO_MEMORY`。单速率重复出现，不能只归因于 Wi-Fi。源码中单速率 `step()` 的 `rtExtModeUpload()` 与 `ert_main.c` 的 `extmodeEvent()` 是后续排查线索，尚未用修复后构建验证因果。本轮未改模型或重新发布 ELF/A2L。
2. 开机 DAQ 首次 5 秒采集出现 93 个 Ethernet 序号缺口；首次 30 秒单速率采集有 79 个，末次两模型测试均为 0。网络表现不稳定，不能把末次零缺口解释为系统保证。
3. 原 GRUB 的 ECI 与普通 Ubuntu 菜单复用标识。本轮按唯一标题请求一次性普通 RT 项，但实际 `/proc/cmdline` 仍含既有 ECI 的 `isolcpus=1,3`、`hugepages=1024`、`audit=0`、`mce=off` 等参数；原因未完全确定，结果仅代表这组实际参数，不能称为无额外调优基线。未另行修改这些参数，未再次重启。普通内核文件仍保留，可从 GRUB 回退。
4. 启动后目标系统时钟显示 2025-12-29，`NTPSynchronized=no`。没有擅自改时钟；启动顺序用 boot ID / 进程起始标记验证，调度计时使用 `CLOCK_MONOTONIC`。

因此，`rt_validation.json` 中的 `passed=true` 仅表示脚本定义的模型运行/调度/功能检查通过，不代表目标日志无错误、DAQ 完全无丢样或全部原始需求已经验收。

## 证据与改动

- `before.json`：原内核、boot ID、GRUB/环境、自启文件内容与运行状态。
- `after.json`：真实开机后的内核、命令行、服务 journal、PID/线程/锁内存证据。
- `boot_daq.json`：未手动启动模型前的 DAQ 检查。
- `target_log_diagnostics.json`：从本次启动前日志偏移开始逐行统计的错误数及新运行摘要。
- `final.json`：恢复后的自启配置、无运行模型、当前内核和 GRUB 环境。
- `first_validation_failed_log_read.json`：初次摘要读取失败的记录，未覆盖。
- `rt_validation.json`：最后一次两个模型的完整调度报告。

本轮加固 `tools/validate_realtime_models.py`：拒绝复用已运行模型、只解析本次新增摘要、限制远端日志响应大小、检查精确信号与严格 RT 标志、独立记录清理失败。新增 18 项本地回归均通过。

GRUB 一次性启动与菜单路径规则参考 [GNU GRUB next_entry](https://www.gnu.org/software/grub/manual/grub/html_node/next_005fentry.html) 和 [default](https://www.gnu.org/software/grub/manual/grub/html_node/default.html)。未宣称本机重复菜单问题已经修复。
