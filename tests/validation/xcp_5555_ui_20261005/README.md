# UDP 5555、界面与 IP 配置验证

日期：2026-10-05。当前交付入口：`demos/Demo_XCP_Qt/START_DEMO.cmd`。

## 本轮修改

- 删除 MATLAB SDI 入口及专用导出服务，保留 CSV 和图表 PNG 导出。
- 本项目 XCP 默认端口统一为 UDP **5555**、TCP **17725**。已重新生成匹配的模型、A2L 与清单；历史 ZIP 保持原样。
- 目标 IPv4 可在线编辑，回车或离开输入框提交并自动保存；保存不依赖 SSH 密码记忆，重启 APP 可恢复。
- 在线切换 IP 时停止采集、恢复标定、断开旧 XCP，再连接新地址；此前处于采集状态时，重连成功后恢复采集。
- “网络接口 / IPv4”可在线应用并保存目标网口的静态 IPv4，使用 Netplan + systemd-networkd 持久配置。保留其他网口、Wi-Fi 凭据和 IPv6；未确认时 45 秒回滚。配置生成失败也继续尝试恢复实时地址、路由和网口状态。
- 部署操作显示“上传模型 / 启动模型 / 停止模型”，路径和状态名称也改为“模型”；实际文件格式仍为 `.elf`。

## 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Qt 界面与在线 IP 切换回归 | 148/148 通过，无跳过 | [测试报告](host_tests/test_report.json) |
| 共享服务回归，包括保存与失败回滚 | 187/187 通过，无跳过 | [服务日志](host_tests/baseline_tests.log) |
| Python XCP 后端 | 31 项通过 | [后端日志](python_backend_tests.log) |
| 构建、端口及工作流回归 | 75 项通过 | [工作流日志](python_workflow_tests.log) |
| MATLAB R2024b 目标测试 | 11/11 通过 | [MATLAB 结果](matlab_tests.json) |
| Windows 本地模型交叉编译 | 1 ms 模型，UDP 5555，成功 | [构建记录](model_build.json) |
| Ubuntu 实机采集与标定 | 30 秒 DAQ，30,358 个样本，标定写入和恢复通过 | [实机记录](target_test.json) |
| 目标机网络持久化 | 在线应用、保存、重新生成及 45 秒回滚通过 | [隔离网口结果](network_persistence_target.json) |
| Windows Qt 界面渲染 | 两种窗口尺寸、四个页面，按钮无越界或截字 | [渲染报告](visual_windows/visual_report.json) |
| 最终 Windows EXE | 加载演示预设、窗口响应、正常退出通过 | [启动检查](app_smoke.json) |

实机地址 `192.168.193.195`，内核 `7.0.0-34-realtime`。模型以 `SCHED_FIFO`、优先级 40、CPU 3 和锁定内存运行；完成 36,975 次周期，无 deadline miss、skipped release、丢帧、队列丢样或时间戳缺口。模型步长实测均值为 `1,000,000.934 ns`。验证包含断开 SSH 后自主运行 3 秒，结束时已停止本次测试模型并恢复标定。

## 交付产物

- 模型 ZIP：`models/simrt_rt_single/simrt_rt_single_local/20261005_052620_728.zip`
- ZIP SHA256：`5cce5e56b2ac24ebd805b192b26054357b711c00161d844d195ea1fcb1d4da8e`
- ELF SHA256：`461a6ac4ef015877f28b6bb76f08c5d843f429b20ffd8085f3438a97e87a23ba`
- EXE SHA256：`815f6e501753e60137b593e5d428fb046cce8e92fd9141c4edbe51a868349650`
- EXE 构建环境与 C++ DLL 哈希：[构建报告](app_build_report.json)。
- 工作区旧程序备份：`tests/validation/xcp_5555_ui_20261005_previous_app/app`。

## 验证边界

网络持久化在实机独立 Linux 网络命名空间、虚拟网口和隔离 Netplan 根目录中测试，使用真实 Netplan 生成器和真实 45 秒回滚进程。已验证新的生成进程能够读取保存地址；**未修改物理网口 IP，也未对目标机断电或重启**。当前持久化支持有独立 Netplan 定义且使用 networkd 的网口；不提供 DHCP 模式切换。

`visual_windows` 为测试夹具截图，使用合成信号和模拟目标状态，不是实机采集截图。`visual` 的 offscreen 渲染缺少字体，仅供布局诊断；中文外观以 Windows 平台截图为准。EXE 检查是进程启动和正常退出检查，未宣称人工点击验收。30 秒实机测试不代表长期或任意负载验收。

## 复现入口

- 界面与服务：`.venv/Scripts/python.exe app/qt_xcp_host/validate_tests.py --output <新报告目录>`。
- MATLAB：使用 R2024b 执行本目录的 `build_and_test.m`，会重新构建本地模型。
- 目标采集：`tests/tools/scripts/validate_local_workflow.py --receipts <构建记录> --host <目标IP> --user <用户> --seconds 30 --output <新报告文件>`，密码交互输入。
- 隔离网口持久化：[verify_network_persistence.py](verify_network_persistence.py)，需要目标 sudo 权限；脚本固定使用本轮目标地址，复用前核对。
