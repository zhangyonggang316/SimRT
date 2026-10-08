# XCP 端口迁移与验证，2026-10-05

本轮将项目 XCP 默认端口统一为 UDP `55555`、TCP `17725`，并保留实时机页面输入 IP 优先于模型 ZIP/A2L 地址的行为。当前交付模型实际运行 UDP。

## 自动化测试

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| Qt 界面、IP 同步、跨层端口默认值 | 144 项通过 | `host_tests/qt_tests.json` |
| 共享服务、真实 TCP/UDP socket 回环 | 190 项通过 | `host_tests/baseline_tests.json` |
| Python XCP 后端 | 31 项通过 | 本轮代理执行 `unittest discover -s tests/protocol` |
| 工具脚本 | 101 项通过 | 本轮代理执行 `unittest discover -s tests/tools/unit` |
| 目标构建与实时源码打包 | 39 项通过 | `target_python_tests.log` |
| MATLAB R2024b 全量测试 | 首轮 77/79；修复后 CAN 类 7/7，覆盖的 79 项最终均通过 | `matlab_tests.json`、`matlab_can_retest.json` |
| Windows EXE 启动 | 通过，加载当前预设、进程响应正常 | `app_smoke.json` |

MATLAB 首轮失败的两项 CAN 测试仍期待旧版 8 字节常量，而交付模型已改为 double 正弦信号。测试改用两路不同的受控波形，校验每毫秒接收值、路由、ID、状态和时间；没有修改 CAN 模型。一次复测暴露 SimulationInput 参数调用方式错误，修正后 7 项通过。原始日志均保留。

## 模型与交付

- MATLAB：R2024b Update 10；代码生成、Linux 交叉编译、A2L 导出均在 Windows 本地完成。
- 集成测试完成两次构建、重复发布、ZIP 哈希和 ELF/A2L 一致性验证。
- 正式模型：`simrt_rt_single`，固定周期 `0.001 s`，目标地址 `192.168.193.195`。
- 新 ZIP：`models/simrt_rt_single/simrt_rt_single_local/20261005_022258_551.zip`，默认启动预设已选择此包。
- ZIP SHA-256：`bc320d3582b17d532b748771d290ef95795a0d0e46139ebcb117e101650e19bf`。
- ELF SHA-256：`570f967721691a229843067d3edf46e22efeee5282fc226b38b97a2ac56cd794`。
- EXE SHA-256：`ed9c50d2b69fae8f564a15537166c7f6f54844927a08eb69da0be9435e99e5d7`。
- 构建后的临时检查错误地搜索十进制字符串；实际 A2L 使用十六进制端口。已改用现有解析器验证 A2L 与清单均为 UDP 55555，见 `artifact_check.json`。编译本身成功，见 `model_build.json` 与构建日志。
- 旧 APP 备份位于工作区 `tests/validation/xcp_ports_20261005_previous_app/app`。历史 ZIP 保留原始内容，不修改旧 ELF 的配套元数据。

## 真机验证

目标 `192.168.193.195`，x86-64，内核 `7.0.0-34-realtime`。使用隔离目录部署本地产生的 ELF，未修改开机自启；测试结束恢复标定并停止本轮模型。

首轮 `target_test.json`：连接、标定写入/回读/恢复、1 ms 调度通过，但 DAQ 有 506 个传输计数缺口、972 个时间戳缺失样本和 2 个乱序帧；目标出现 `rtExtModeUpload error: code -10`（XCP_NO_MEMORY），整体判定失败。该轮与本机 MATLAB 测试并行；尚未证明后台负载或 Wi-Fi 是根因。

停止后台构建任务后，使用相同 ZIP 和代码进行 30 秒复测，`target_retest.json` 所有检查通过：

- UDP `55555` 连接成功，接收 30,694 个原始样本；采集启动与停止的边界样本包含在总数中。
- 传输计数缺口、时间戳缺失、乱序、无效帧、队列丢弃和过载均为 0。
- `CalOffset` 从 0 写为 0.25，回读正确；恢复为 0，回读正确；过程中 DAQ 持续。
- 实际 model_step 平均间隔 `999999.973 ns`，超期和跳期均为 0。
- SCHED_FIFO、锁内存和实时内核检查通过；SSH 断开期间模型继续自主运行。
- 新增目标错误日志为 0，清理错误为 0。

复测通过不能消除首轮的间歇性异常；两轮证据均保留。当前真机覆盖 UDP，TCP 覆盖默认值和真实 socket 回环，未运行 TCP 目标模型。EXE 启动检查不是桌面逐控件人工验收。
