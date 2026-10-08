# ARK2120 的 1 ms / 50 us 抖动优化

本轮于 2026-10-06 开始，构建及复验跨至 2026-10-07。验收按 **1 ms ±50 us**，即实际 `model_step` 入口间隔 **0.950–1.050 ms（含边界）**，提前/延后越界、超期和跳期均应为零。有限测试与超过 14 小时的长测分别记录。

环境：Atom D2550 / ARK2120，Ubuntu `7.0.0-34-realtime`，4 个逻辑 CPU、2 个物理核心；Windows MATLAB R2024b Update 10、本地 GCC 7.5.0 交叉编译。没有在目标机编译，也没有保存或关闭用户 MATLAB 桌面中的模型。

## 为什么旧版不满足要求

[修改前快照](before.json)保留旧 PID 17319 的长期累计计时：最小 0.813731 ms、最大 1.196440 ms，偏差分别为 -186.269 us、+196.440 us，虽然超期/跳期均为零，仍不符合本次要求。旧运行器提前量为 50 us，系统尚未启用启动级 CPU 隔离；普通进程和部分内核工作仍可使用模型物理核心。

绝对释放网格下，`实际间隔 = 1 ms + 本次入口迟到 - 上次入口迟到`。因此一次迟到可能接着出现短周期，平均值仍接近 1 ms。旧极值没有逐事件上下文，不能仅据截图认定某次 IRQ、SMI 或驱动是唯一原因。

## 本轮实现

1. 按实际 SMT 拓扑隔离 CPU2/3，模型使用 CPU3/FIFO40；普通主线程、XCP、状态写入及监视器使用 CPU0/1。加入 `isolcpus=domain,managed_irq,2,3 nohz_full=2,3 rcu_nocbs=2,3 irqaffinity=0,1` 并实际重启核验。保留原有 IRQ/非绑定工作队列配置服务和运行期 `/dev/cpu_dma_latency` 请求。
2. 默认提前 500 us 从绝对睡眠返回，自旋至原定释放点。进入尾段后不再睡眠，EINTR 后重新检查剩余时间。`SIMRT_RT_SPIN_US=0..500` 可调整，默认 500；这会增加约半个逻辑 CPU 的自旋负担，不是将容差改成 500 us。
3. 修正隔离后 SSH 只继承 CPU0/1 时的选核逻辑：自动探测实际允许的隔离 CPU，回读 affinity 并遵守 cgroup cpuset。显式指定不可访问 CPU 时报错；未读取到 SMT 信息时明确告警。
4. 保留真实累计极值与原超期/跳期口径。新增 ±50 us 的 early/late 计数、睡眠返回延迟、释放迟到、模型入口开销及最近越界样本。实时线程只更新固定大小内存；JSON 由普通后台线程写入。屏幕增加 `Jitter > +/-50 us`，旧模型无计数时显示 unavailable。

隔离依据：[Linux CPU isolation](https://docs.kernel.org/admin-guide/cpu-isolation.html)。它减少操作系统干扰，不能屏蔽所有固件/硬件延迟。目标 CPU 不支持本轮 MSR SMI 计数读取，因此没有宣称已排除或测量所有 SMI。后续若越界，可对照新增事件上下文使用 [timerlat](https://www.kernel.org/doc/html/latest/trace/timerlat-tracer.html)进一步定位。

[安装及重启回执](isolation_install_retry.json)记录生效的启动参数、boot ID 和不变的自启选择。[首次安装失败记录](isolation_install.json)是 GRUB 条目解析验证失败，已自动恢复配置；该轮没有重启。修正解析后才执行成功的一轮。

## 分组实测

每周期约 100 us 合成运算，直接计量函数入口间隔。前四组未启用启动隔离，各 60,000 周期，保留原 IRQ 配置；均无 XCP 负载。[提前量对照](spin_comparison.json)

| 配置 | 周期数 | 最小 ms | 最大 ms | early / late | 超期 / 跳期 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 提前 50 us | 60,000 | 0.971356 | 1.030740 | 0 / 0 | 0 / 0 |
| 提前 100 us | 60,000 | 0.998715 | 1.001288 | 0 / 0 | 0 / 0 |
| 提前 250 us | 60,000 | 0.998880 | 1.001296 | 0 / 0 | 0 / 0 |
| 提前 500 us | 60,000 | 0.998288 | 1.001674 | 0 / 0 | 0 / 0 |
| 隔离 + 500 us + CPU0/1 满负载 | 180,000 | 0.999369 | 1.000633 | 0 / 0 | 0 / 0 |
| 最终选核修正 + 同样满负载 | 60,000 | 0.999151 | 1.000947 | 0 / 0 | 0 / 0 |

后两组证据：[3 分钟负载测试](isolated_stress.json)、[最终运行器回归](final_runtime_regression.json)。短时零越界不是 14 小时结论；500 us 提前量用于增加对稀有唤醒迟到的余量，不能把这些有限样本解释为最坏情况保证。

回归包括 38 项时间数学测试、7 组伪时钟/EINTR/计数边界测试、6 组选核/cpuset/CPU 列表测试；全部在本地交叉编译后于目标 Linux 执行。故意注入 2.5 ms 计算的用例仍得到 10 次超期、18 个跳期、约 3 ms 最大间隔，证明异常未被隐藏。10 ms / 100 ms 调度兼容性各执行 20 周期，仅为运行器测试，不增加交付模型。

本地 Python 验证器及监视器测试 35 项通过，console 测试 30 项通过；目标端 console 文件哈希和独立 tmux 测试通过。[显示部署记录](console/console_deployment.json)

## 完整模型与长时间验证

最终构建为 **20261006_161834_217.zip**，配套三文件上传哈希已经核对。[构建回执](model_build_final.json)与 `matlab_build_final.log` 保留构建来源；两份更早的 model_build 回执为中间构建，不作为最终交付。

```text
ZIP SHA256: 0b16ac6f2bf7fc163340aadb8d755a8880e6671e11e81c946a741a83fbddebda
ELF SHA256: df2f8d5bb47b18c0e64e2116ae8739ab67c022a0669528dea91727a72742a821
A2L SHA256: 2ed3071e55bca38fb5a86662cc5b9aafa1fe294c91f1fd99f0e3ca7f146f63cf
```

10 分钟 XCP DAQ、标定及 SSH 断开验证已完成：[model_validation.json](model_validation.json)。[联调中只读核验](during_daq.json)确认模型 CPU3/FIFO40、普通线程 CPU0/1、锁内存及低延迟请求。

| 指标 | 结果 |
| --- | ---: |
| model_step 调用 / 完成 | 607,230 / 607,230 |
| 最小 / 平均 / 最大间隔 | 0.999185 / 0.999999999 / 1.000779 ms |
| 最大绝对周期偏差 | 0.815 us |
| early / late、超期 / 跳期 | 全部为 0 |
| 最大模型执行耗时 | 0.236644 ms |
| 最大睡眠返回延迟（相对于提前唤醒点） | 93.946 us |
| 目标端新错误日志 | 0 |
| DAQ 接收样本 | 600,294 |
| UDP 传输计数缺口 / 时间戳缺样 | 96 / 96 |
| 队列丢弃 / 无效帧 / 重排 / 过载事件 | 全部为 0 |
| 标定写入、回读、恢复及过程中继续采样 | 通过 |
| SSH 断开后相同模型继续自主运行 | 通过 |

**周期精度检查通过，DAQ 无丢样验收未通过。** 验证器保留 `passed=false` 并恢复旧模型；核对所有模型检查及 50 us 条件通过，且唯一失败项为 UDP 计数和时间戳缺口后，另行[启用新版模型](activation.json)。没有放宽 DAQ 判定或改写失败报告。

当前模型 `/home/zh/MATLAB_ws/realtime_50us_7fdb1347/simrt_rt_single.elf`，启用时 PID 3143。APP 默认 ZIP 已同步更新；已打开的 APP 请重新加载匹配的新 ZIP。[新模型屏幕快照](console/new_model_snapshot.txt)确认 early/late 正常显示。

目标端长测工具 `tests/tools/scripts/monitor_rt_soak.py` 每分钟读取模型的累计计数，记录 ELF 哈希、boot ID、PID、进程启动标记、线程 affinity 和状态新鲜度，不控制或重启模型。任何累计越界、进程更换或状态失效都会保留首次失败。只有连续完成指定时长且无失败才设置 `passed=true`；正在运行始终为 `passed=false`。

`tests/tools/scripts/start_rt_soak.py` 通过 systemd 用户服务独立运行监视器，SSH 断开后继续记录。[60 秒工具自检](monitor_smoke_finished/summary.json)通过，服务已结束；该结果不是 15 小时验收。**用户于 2026-10-07 确认抖动基本解决，暂不需要长期观察，因此计划中的 15 小时监测未启动。** 当前只保留正常模型运行，长测脚本留作以后需要时使用。

## 复现与回退

工程根目录运行以下验证会暂时停止所指定的旧模型，失败恢复旧模型。必须先核对旧路径仍是当前模型，并使用新的输出文件名，避免覆盖历史证据。

```powershell
./.venv/Scripts/python.exe -B tests/tools/scripts/validate_rt_update.py --receipt tests/validation/realtime_50us_20261006/model_build_final.json --previous-model /home/zh/MATLAB_ws/realtime_20261006_e2947e81/simrt_rt_single.elf --output tests/validation/realtime_50us_repeat.json --seconds 600
```

先在 APP 停止模型，再通过下列目标端管理员命令撤销本轮启动隔离；实际启动参数恢复后才运行旧模型，避免旧选核逻辑受 SSH 继承 CPU0/1 限制：

```bash
sudo rm /etc/default/grub.d/92-simrt-cpu-isolation.cfg
sudo update-grub
sudo reboot
```

本轮 GRUB 备份在 `/var/backups/simrt/rt-isolation-37a7125abe76/grub.cfg`。旧模型位于 `/home/zh/MATLAB_ws/realtime_20261006_e2947e81/`，匹配 ZIP 为 `20261006_005108_492.zip`；新模型路径见联调报告。原模型自启为空且禁用，本轮保持这一选择。

要撤销前一轮 IRQ 调整，另用 `sudo systemctl disable --now simrt-rt-tuning.service`；CPU 延迟请求在模型停止后释放。只改运行期提前量可设置 `SIMRT_RT_SPIN_US=50` 或 `0`，需重新启动模型；更小提前量必须重新验收，不能沿用当前结果。

学习入口：`toolchain/simrt_linux_target/src/simrt_rt_runtime.c` 的 `simrt_rt_prepare`、`__wrap_sem_wait`、`simrt_rt_step_begin`；对应 `tests/rt_runtime_*` 测试和 `docs/1ms_solution.md`。此前版本备份 `D:\05SimRT_versions\SimRT_2026.10.06\` 保持不变。
