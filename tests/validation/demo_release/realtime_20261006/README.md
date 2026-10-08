# ARK2120 实时性与运行时间显示

环境：MATLAB/Simulink R2024b Update 10、Windows 本地 GCC 7.5.0 交叉编译；目标 `192.168.193.195`，Atom D2550、PREEMPT_RT `7.0.0-34-realtime`。目标机没有执行编译。

## 显示与库

- `Model elapsed` 和有限停止时间采用累计小时 + 剩余秒，例如 `16 h 1430.831 s`；不按 24 小时回绕。周期、执行耗时和间隔仍为 ms。
- 本地 29 项 console 测试通过；目标文件哈希校验、独立 tmux 显示测试通过，已更新正在显示的 pane。[部署记录](console/console_deployment.json)
- 库浏览器统一为 `SimRT`，五个功能子库及 13 个模块在 R2024b 真实浏览器目录验收通过。[库验收](../simrt_library_20261006/README.md)

## 原因与改动

[原始快照](before.json)中，模型为 CPU3/FIFO40，但普通主线程允许 CPU0–3，状态线程允许 CPU0–2。CPU2/3 同属一个物理核心；USB IRQ23 在 CPU2，AHCI 和网卡中断在 CPU3。之前约 16.5 小时的模型统计为 interval `0.098766–23.832695 ms`、4 次超期、88 个跳期；模型计算最大耗时仅 `0.282314 ms`。这说明应优先处理唤醒与系统干扰，但不能据此唯一认定那四次偶发停顿的原因。

运行器在初始化前将普通线程固定到其他物理核心；模型仍 FIFO40、锁内存。提前 50 us 绝对睡眠加短自旋保持原定释放网格，并在运行期间请求 CPU 低延迟空闲策略。状态和汇总新增实际 `spin_us` / `cpu_dma_latency_active`。不清零旧报告、不裁剪间隔、不屏蔽丢周期。

目标机安装 `simrt-rt-tuning.service`，将可迁移 IRQ 与非绑定工作队列移至 CPU0/1。`udev` 为模型用户组授权 `/dev/cpu_dma_latency`。服务已生效并启用开机加载；本轮没有重启验证。[安装记录](tuning_install.json)

## 分组测量

同一目标、同一 1 ms harness，每周期约 100 us 合成计算负载，每组 60,000 次。各组依次运行，原演示模型测试期间停止，结束恢复；无 XCP 负载。旧版 ELF 来自本轮修改前源码的 Windows 本地交叉编译。[完整结果](benchmark_run2.json)

| 配置 | 最小间隔 ms | 最大间隔 ms | 超期 / 跳期 |
| --- | ---: | ---: | ---: |
| 原运行器 | 0.824076 | 1.140470 | 0 / 0 |
| 仅应用线程分核 | 0.802878 | 1.263131 | 0 / 0 |
| 分核 + CPU 延迟请求 | 0.807606 | 1.262025 | 0 / 0 |
| 再加 50 us 提前唤醒 | 0.942733 | 1.057581 | 0 / 0 |
| 再移出可迁移 IRQ / 非绑定工作队列 | 0.967560 | 1.022726 | 0 / 0 |

16 项调度数学检查通过；不支持的周期/子任务被拒绝；故意注入 2.5 ms 运算的 200 周期用例仍报告 10 次超期、18 个跳期，实际最大间隔约 3 ms。

这里的短时分组最差值不能替代 16.5 小时的长时最差值，也不证明任意负载下严格 1 ms。暂以 0.9–1.1 ms 为工程检查范围，最终容差待用户确认。

## 完整模型联调

首次 300 秒 XCP 联调 [model_validation.json](model_validation.json) 的实时调度通过：307,197 次模型调用全部完成，间隔 `0.956385–1.048436 ms`，平均 `1.000000036 ms`，超期/跳期均为 0；线程分核、低延迟请求、标定写入和恢复、断开 SSH 后继续运行均通过。

该次联调整体失败：2,272 条 `rtExtModeUpload error: code -10`、282 个传输计数缺口、2,554 个时间戳缺样，不能写成 DAQ 无丢样。R2024b `ext_mode.h` 将 -10 定义为 `EXTMODE_NO_MEMORY`，DAQ 队列只有 64 个周期。构建配置已在原有固定 1 MiB 总池内将每 ODT 的缓冲深度改为 1,024，吸收发送短暂停顿；不在实时线程增加动态内存分配。旧报告与旧 ELF 保留，复测见 [model_validation_pool1024.json](model_validation_pool1024.json)。

最终 1024 周期缓冲版本的 300 秒复测：

| 指标 | 结果 |
| --- | ---: |
| model_step 调用 / 完成 | 307,030 / 307,030 |
| 最小 / 平均 / 最大间隔 | 0.953423 / 1.000000000 / 1.054240 ms |
| 超期 / 跳期 | 0 / 0 |
| 最大模型执行耗时 | 0.244999 ms |
| 目标端缓冲错误 / 其它新错误日志 | 0 / 0 |
| DAQ 接收样本 | 300,116 |
| UDP 传输缺口 / 时间戳缺样 | 195 / 195 |
| 主机应用队列丢弃 / 无效帧 / 重排 | 0 / 0 / 0 |
| 标定写入、回读、恢复及过程中继续采样 | 通过 |
| SSH 断开后模型继续自主运行 | 通过 |

**实时调度验收通过，DAQ 无丢样验收未通过。** Windows UDP Receive Errors 为 0，Linux UDP RcvbufErrors/SndbufErrors 均为 0；这不足以定位剩余缺口发生在无线链路的哪一段，没有以放宽无丢样检查来标记整体通过。

已依据通过的全部模型调度检查启用新版模型，单独保留 `daq_lossless_passed=false`。[启用记录](activation.json)记录实际运行目录。APP 默认模型包为 `20261006_005108_492.zip`，已打开的 APP 需重新加载该 ZIP，以使用匹配的新 A2L。当前不宣称 24 小时或任意负载下无超期；模型保持运行供后续长时间观察。

本地附加检查：Python client 18 项测试通过；CPU 列表及跨 32/64 位 affinity 掩码边界检查通过；新运行器在本地 GCC `-Wall -Wextra` 下编译无警告。

## 构建与回退

[本地构建收据](model_build.json)记录配套 ZIP、ELF/A2L/manifest 哈希；纯睡眠版本收据另存为 `model_build_sleep_only.json`，64 周期缓冲版本另存为 `model_build_pool64.json`，均未当作最终版本交付。当前桌面中的模型有未保存修改，构建使用独立 R2024b 后台进程，未保存或关闭用户桌面模型。

旧远程模型保留在 `/home/zh/MATLAB_ws/manual_demo_20261005_142634_972e73ba/`，原自启选择为空且本轮不新增选择。需要回退运行器时，先停止新模型，再通过 APP 选择旧目录及其匹配 ZIP。

管理员可用 `sudo systemctl disable --now simrt-rt-tuning.service` 恢复本次 IRQ/工作队列配置；备份位于 `/run/simrt-rt-tuning.json`，只恢复仍等于本工具写入值的项目。CPU 低延迟请求在模型退出时自动释放。完整取消设备授权时移除 `/etc/udev/rules.d/90-simrt-cpu-latency.rules`，重载规则，并根据安装收据恢复设备原所有者/模式。

复现入口：`linux/tools/audit_rt_latency.py`、`tests/tools/scripts/benchmark_rt_latency.py`、`linux/tools/install_rt_tuning.py`、`tests/tools/scripts/validate_rt_update.py`。benchmark 和完整模型验证会短暂停止显式指定的旧模型；失败会恢复原模型。
