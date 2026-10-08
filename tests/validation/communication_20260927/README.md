# 2026-09-27 通信库与实时机显示验证

## 已执行

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 显示采集、单位、全部接口、分页、状态边界 | 21 项通过 | `tests/linux/test_console.py` |
| 真机单一全屏显示更新 | 文件哈希一致；最终仅 python3 一窗格，240×75；独立 3 次尺寸/输入检查通过 | `console_deployment.json`、`live_console_capture.txt` |
| Linux TCP/UDP | 真实 localhost 双向收发、TCP 小缓冲区完整性/重连、有界队列和令牌检查通过 | `linux_runtime_tests.json` |
| Linux 串口 | PTY 双向字节收发、失效令牌、无数据、RS485 不支持错误检查通过 | `linux_runtime_tests.json` |
| EtherCAT 运行库 | SOEM API 替身覆盖 PDO/WKC/状态故障；真实 SOEM v1.4.0 已链接执行输入校验 | `linux_runtime_tests.json` |
| MATLAB System 对象 | 网口 5 项、串口/EtherCAT 3 项通过 | 对应 MATLAB 测试文件 |
| Simulink 模型结构 | 全部通信块接入检查模型，无悬空端口/连线 | `communication_codegen_check.slx` |
| 本地完整构建 | R2024b 生成 C、GCC 7.5.0 交叉编译、ELF/A2L/manifest 三文件 ZIP 通过；ZIP 哈希已核对 | `matlab_build.log`、`communication_codegen_check_ert_rtw/simrt_local_build.json` |
| APP-14 服务及 Qt 回归 | Qt 136 项、共享服务 190 项通过 | `../../tests/validation/app_network/test_report.json` |
| 实际 IPv4 修改/确认/回滚 | 独立 network namespace 内 dummy 网卡通过真实 45 秒超时回滚 | `network_namespace_test.json` |
| 打包 APP | PyInstaller 完成；真实 EXE 启动并显示新增“网络接口 / IPv4”入口，断连时禁用正确；已更新正式 APP | `qt_build.log`、`app_promotion/promotion.json` |

本轮生成库文件：`simrt_network_library.slx`、`simrt_serial_library.slx`、`simrt_ethercat_library.slx`。库中未连线端口是供模型使用的公开端口；库只检查悬空连线，完整连接检查在集成模型执行。三个 `*_library.png` 是 MATLAB 渲染图，已调整块尺寸避免图标与端口名称重叠。

构建产物：`communication_codegen_check_local/20260927_101838_706.zip`，SHA-256 `2f0cc9fdba1c16808270f350354b272561fd7f94934b83fdeb89cf4c87bf6017`。构建只在 Windows 本地执行；该模型是编译检查，不启动真实串口或 EtherCAT 总线。ASAP2 导出跳过内部 System 对象结构体的提示不影响字节数组、状态和计数输出。

## 尚未验收

- 实际 RS232/RS485 接线、BIOS/跳线模式以及 DB9 与 Linux tty 设备对应关系。
- 真实 EtherCAT 从站的 PDO 布局、设备参数、状态切换及持续通信；未指定从站型号/ESI。
- 上位机修改真实物理网卡 IP；当前未收到要配置的新 IP，实际网络地址保持原值。隔离命名空间测试不等同于修改管理网口验收。
- 通信库接入后的 1 ms 最坏执行时间、长期丢包/超期和实际重启显示自启。

目标地址 `192.168.219.195`。只读硬件清单 `target_inventory.json` 显示三张有线网卡和 Wi-Fi，DMI 未提供 L/F 完整产品名。官方手册型号差异及入口见 [通信库交付说明](../../../docs/COMMUNICATION_LIBRARIES.md)。

正式入口继续使用 `demos/Demo_XCP_Qt/START_DEMO.cmd`。本次按 SHA-256 比对更新 APP 的 4 个文件，之前的文件保存在 `app_promotion/previous_files`，示例模型及其选定构建未改动。打包日志含第三方 pyxcp 可选 recorder converter 的 `pa` 导入警告；APP 启动、现用通信路径和回归测试通过，该可选转换器不属于本轮功能。
