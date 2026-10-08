# 1 ms 模型运行方案

当前仅保留 `simrt_rt_single` 一套单任务单速率模型，APP 为 Python/PySide6 Qt。
完整流程见 [TOOLCHAIN.md](TOOLCHAIN.md)：本地 Simulink 生成代码、本地交叉编译和 A2L 配套，再经 SSH 上传 Ubuntu 运行。

## 执行结构

```text
R2024b: Fixed-step 0.001 s, single-task
  -> CLOCK_MONOTONIC absolute release, SCHED_FIFO 40, locked memory
  -> generated model_step() once per release
  -> generated DAQ event samples model values
  -> SCHED_OTHER communication thread handles XCP
  -> Windows Qt APP receives batches and draws independently
```

运行器保留生成算法，使用独立实时入口。生成代码已有 DAQ 事件时外层不再重复发出。
网络收发使用普通线程；SSH、XCP 连接与 DAQ 启停不驱动模型步进。
超期时统计并跳过已错过的释放点，不积压补算。日志直接测量模型调用次数、完成次数、间隔及执行耗时。

## ARK2120 调度配置（2026-10-07）

运行器在模型初始化前查询在线、隔离和实际允许的 CPU 集合，将主线程及其后台线程移出模型 CPU 所在的整个物理核心。ARK2120 的 CPU2/3 共用一个物理核，模型使用 CPU3、FIFO40，XCP 和状态写入使用 CPU0/1。隔离启动后 SSH 可能只继承 CPU0/1；运行器在初始化前探测可访问的隔离 CPU，回读内核实际 affinity 后选核，不能仅从继承掩码中选择。cgroup cpuset 仍然有效；显式指定不可访问的 `SIMRT_RT_CPU` 会报错。

绝对睡眠默认提前 **500 us** 结束，余下时间自旋至原定释放时刻；环境变量 `SIMRT_RT_SPIN_US=0..500` 可调整。已进入自旋窗口时不再执行睡眠；被信号打断后重新判断剩余时间。1 ms 模型最多约占用半个逻辑 CPU 的自旋时间，以额外功耗换取唤醒余量。500 us 是提前量，不是抖动容差，也不能保证屏蔽所有硬件/内核停顿。

保留原有绝对时间网格和真实调用间隔；迟到不会裁剪成 1 ms，不使用每次 `now + period` 累计漂移。新的验收范围是 **0.950–1.050 ms（含边界）**，超出即累计 early/late。屏幕保留终生 min/avg/max，并增加 `Jitter > +/-50 us`。状态和最终摘要还包含睡眠返回延迟、释放迟到、模型入口开销与最近一次越界上下文；实时线程只更新固定大小的数据，JSON 文件由普通后台线程写入。

运行期间持有 `/dev/cpu_dma_latency` 的 0 us 请求，停止后释放；`SIMRT_RT_LOW_LATENCY=0` 可关闭。请求失败会明确输出告警，状态 JSON 的 `cpu_dma_latency_active` 给出实际结果。该请求影响 CPU 空闲策略，可能增加功耗；不是 CPU 频率设置。[Linux PM QoS](https://docs.kernel.org/power/pm_qos_interface.html)

XCP 每 ODT 的 DAQ 预分配块数为 1024，总池仍限制为 1 MiB，用于承受后台发送短暂停顿，避免原 64 周期队列耗尽后在模型线程打印 `EXTMODE_NO_MEMORY`。这不能保证 Wi-Fi/UDP 不丢包；模型周期、目标端分配失败与主机 DAQ 缺样分别计量。

目标机 `simrt-rt-tuning.service` 将可迁移 IRQ 和非绑定工作队列分配到另一个物理核心，保留固定 IRQ；启动后生效，停止服务时按保存值恢复，且不会覆盖后来被其他程序修改的值。本轮额外启用 `isolcpus=domain,managed_irq,2,3 nohz_full=2,3 rcu_nocbs=2,3 irqaffinity=0,1`，重启核验后生效，将普通调度、可卸载时钟和 RCU 工作移出模型物理核。CPU 编号只适用于当前 ARK 拓扑；新机器须重新核对，不能直接照抄。[Linux CPU isolation](https://docs.kernel.org/admin-guide/cpu-isolation.html)

当前证据、15 小时记录工具和回退入口见 [50 us 优化与验收](../tests/validation/realtime_50us_20261006/README.md)。此前仅提前 50 us 的[旧版测试](../tests/validation/realtime_20261006/README.md)和 14 小时异常数据继续保留。模型总运行时间使用累计小时加剩余秒，周期及任务耗时仍以 ms 表示。

## 历史机器验证（2026-09-16）

本地构建证据：`tests/validation/local_ctrlb_final_20260916/build_report.json` 中的 `simrt_rt_single`。
运行证据：`tests/validation/requirements_20260916/local_workflow.json` 中同名记录。
目标为 `192.168.219.86`，实际使用 PREEMPT_RT、FIFO 40、CPU 7 和锁内存。

| 指标 | 实测 |
| --- | ---: |
| 设定基本周期 | 1 ms |
| model_step 平均间隔 | 0.999999984 ms |
| model_step 间隔范围 | 0.582483 至 1.418177 ms |
| 最大 step 耗时 | 8.631 us |
| 调用及完成次数 | 均为 34,943 |
| 30 秒 DAQ 样本数 | 30,102 |
| 超期 / 跳期 | 0 / 0 |

SSH 断开 3 秒后重新连接，核对同一进程仍在运行；DAQ 期间标定写入、回读和恢复均通过，DAQ 未中断。
本次有限测试中的传输错误及样本缺口计数为零。测试结束恢复标定并停止本次模型，没有改变开机自启配置。
对应 ELF SHA-256 为 `bb6b638a3ff86a536e6acace97dd761264c261decf01ffc2b0adf10d8f87158c`。

当前 APP 预设可指向后来重新编译的三文件结果；其具体哈希见 `tests/validation/demo_release/current_selection.json`。上述真机结论只对应这里记录的 ELF 哈希，目录整理不会重做目标机运行验收。

这是软实时结果，存在唤醒抖动，不保证任意负载下每两个调用都精确相隔 1 ms。
历史 WLAN 中断长测仍保留在原始报告中；短时通过不能替代长期或最坏情况验收。

## APP 与复现

入口为 `demos/Demo_XCP_Qt/START_DEMO.cmd`，默认加载 `demo.json` 指定的 `simrt_rt_single_local/<时间戳>.zip`，内部解压三文件并校验；重新编译后选择新一轮 ZIP。
每信号默认保留 1,000,000 个原始点，超过容量才淘汰最旧点；显示抽样不改变原始缓存。
SSH 上传完整 payload 并校验哈希成功后才允许启动，运行中的目录禁止覆盖。
复现及新的真机验证命令见 [TOOLCHAIN.md](TOOLCHAIN.md)。历史报告中其它模型名称仅供追溯，其模型和产物已删除。
