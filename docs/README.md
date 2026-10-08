# 工程学习与使用手册

本工程在 Windows/MATLAB 本地生成 C 并交叉编译 Linux ELF，通过 SSH 部署，Linux 自主运行 1 ms 模型，Python/Qt APP 通过 XCP 观测和标定。

实时机、源码和内部标识统一使用 SimRT。新机和旧工程升级均按[注册与迁移步骤](NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)执行。

## 推荐阅读顺序

| 目的 | 阅读入口 | 内容 |
| --- | --- | --- |
| 当前版本与后续优化 | [SimRT 2026.10.06](VERSION_20261006.md) | 完整备份、恢复校验、源码阅读路线及尚未通过的验收项 |
| 1 ms 周期与 50 us 容差 | [调度方案](1ms_solution.md)、[本轮实机记录](../tests/validation/realtime_50us_20261006/README.md) | CPU 隔离、提前唤醒、真实极值、越界计数、长期记录及回退 |
| 使用 SimRT 功能库 | [ARK 串口与数字 I/O](ARK_IO.md)、[通信库](COMMUNICATION_LIBRARIES.md) | R2024b 统一根库、五个功能子库与 13 个模块、驱动状态及硬件验收边界 |
| 测试 COM5/6 RS485 | [双向测试模型](RS485_COM56_TEST.md) | 交替发送、CRC 与序号检查、XCP 计数；模型已构建，实际收发尚未通过 |
| 查阅 DIO 历史方案 | [万用表测试与可选回环](DIO_TEST.md) | 已停止板载适配与测试；模型、测量点及说明仅保留作学习参考 |
| 先理解整体设计 | [技术路线与源码阅读](ARCHITECTURE.md) | 两套编译器、Ctrl+B 调用链、XCP/A2L 来源、实时线程、Qt/C++ 数据流、CAN 分层及源码链接 |
| 在新电脑和 Linux 上安装 | [新机部署指南](NEW_MACHINE_DEPLOYMENT.md) | MATLAB/工具箱、交叉工具链、Python/Qt、Linux SSH/RT 权限、自启、CAN SDK、地址迁移和首次验收 |
| 日常构建与上传 | [构建工具链](TOOLCHAIN.md) | 模型配置、Ctrl+B、分阶段编译、ZIP 发布、SSH 上传和验收 |
| 对照其他实时机方案 | [PolarDriver 借鉴与优化](POLAR_COMPARISON.md) | 注册和构建流程对比、配置保留、构建前检查及 DAQ 参数一致性 |
| 遇到问题时定位 | [故障排查](TROUBLESHOOTING.md) | 从失败阶段定位日志、错误信息、只读检查命令及对应源码 |
| 判断哪些文件可以清理 | [目录与清理规则](PROJECT_LAYOUT.md) | 源码、正式产物、构建元数据、缓存和本机环境的区别 |
| 了解模块解耦与目录迁移 | [整理与验证记录](../tests/layout/README.md) | APP、共享服务、工具链、Linux 维护的依赖方向、路径映射与本地验证 |
| 查看验证依据 | [验收索引](../tests/validation/README.md) | 区分当前本地/回环验证、已有硬件证据和历史记录 |
| 使用网口、串口及 EtherCAT | [通信库交付说明](COMMUNICATION_LIBRARIES.md) | 模块入口、ARK-2120 串口规格及硬件验收边界 |

只需运行已有 APP 时，从 [启动入口](../demos/Demo_XCP_Qt/START_DEMO.cmd) 和 [手工操作](../demos/Demo_XCP_Qt/MANUAL_TEST.md) 开始，无需先安装 MATLAB 或编译器。修改模型或 APP 源码时按新机部署指南准备对应开发环境。

## 学习源码的方法

1. 先在技术路线文档中找到一次构建的输入、输出和调用顺序，对照 `simrt_local_build.json` 追踪一个已有 ZIP 的来源。
2. 比较 SLX、生成的模型 C、工程实时入口和最终 A2L，理解算法、调度与变量地址的不同职责。
3. 从 `MainWindow` 的上线按钮追到 `HostController`、`XcpSession` 和 `simrt_xcp.client`，再沿 DAQ 数据返回路径看到 C++ 缓存和游标。
4. 做小范围修改后运行对应层测试；模型/CAN/调度修改需要新构建及真实目标验证，历史报告不自动适用于新产物。

当前文档依据已有机器和源码核对。本次没有在另一套新 Windows/Linux 上重装并验收；新机应按部署指南建立自己的版本、哈希和运行证据。
