# 1 ms 模型运行方案

当前仅保留 `x280_rt_single` 一套单任务单速率模型，APP 为 Python/PySide6 Qt。
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

## 已验证构建的真机结果

本地构建证据：`validation/local_ctrlb_final_20260916/build_report.json` 中的 `x280_rt_single`。
运行证据：`validation/requirements_20260916/local_workflow.json` 中同名记录。
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

当前 APP 预设可指向后来重新编译的三文件结果；其具体哈希见 `Demo_XCP_Qt/validation/current_selection.json`。上述真机结论只对应这里记录的 ELF 哈希，目录整理不会重做目标机运行验收。

这是软实时结果，存在唤醒抖动，不保证任意负载下每两个调用都精确相隔 1 ms。
历史 WLAN 中断长测仍保留在原始报告中；短时通过不能替代长期或最坏情况验收。

## APP 与复现

入口为 `Demo_XCP_Qt/START_DEMO.cmd`，默认加载 `demo.json` 指定的 `x280_rt_single_local/<时间戳>.zip`，内部解压三文件并校验；重新编译后选择新一轮 ZIP。
每信号默认保留 1,000,000 个原始点，超过容量才淘汰最旧点；显示抽样不改变原始缓存。
SSH 上传完整 payload 并校验哈希成功后才允许启动，运行中的目录禁止覆盖。
复现及新的真机验证命令见 [TOOLCHAIN.md](TOOLCHAIN.md)。历史报告中其它模型名称仅供追溯，其模型和产物已删除。
