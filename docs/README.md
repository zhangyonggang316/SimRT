# 工程学习与使用手册

本工程在 Windows/MATLAB 本地生成 C 并交叉编译 Linux ELF，通过 SSH 部署，Linux 自主运行 1 ms 模型，Python/Qt APP 通过 XCP 观测和标定。

实时机的 Simulink 注册名称为 `SimRT`。新机和旧工程升级均按[注册与迁移步骤](NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链)执行；源码中的 `x280linux`、`setupX280LinuxTarget` 等标识符保留，便于既有脚本继续使用。

## 推荐阅读顺序

| 目的 | 阅读入口 | 内容 |
| --- | --- | --- |
| 从 GitHub 克隆后准备环境 | [源码获取与依赖准备](SOURCE_CHECKOUT.md) | 仓库内容、未随 Git 分发的工具链与 APP、源码启动和模型构建 |
| 先理解整体设计 | [技术路线与源码阅读](ARCHITECTURE.md) | 两套编译器、Ctrl+B 调用链、XCP/A2L 来源、实时线程、Qt/C++ 数据流、CAN 分层及源码链接 |
| 在新电脑和 Linux 上安装 | [新机部署指南](NEW_MACHINE_DEPLOYMENT.md) | MATLAB/工具箱、交叉工具链、Python/Qt、Linux SSH/RT 权限、自启、CAN SDK、地址迁移和首次验收 |
| 日常构建与上传 | [构建工具链](TOOLCHAIN.md) | 模型配置、Ctrl+B、分阶段编译、ZIP 发布、SSH 上传和验收 |
| 遇到问题时定位 | [故障排查](TROUBLESHOOTING.md) | 从失败阶段定位日志、错误信息、只读检查命令及对应源码 |
| 判断哪些文件可以清理 | [目录与清理规则](PROJECT_LAYOUT.md) | 源码、正式产物、构建元数据、缓存和本机环境的区别 |
| 查看验证依据 | [验收索引](../validation/README.md) | 区分当前本地/回环验证、已有硬件证据和历史记录 |

只需运行已有 APP 时，从 [启动入口](../Demo_XCP_Qt/START_DEMO.cmd) 和 [手工操作](../Demo_XCP_Qt/MANUAL_TEST.md) 开始，无需先安装 MATLAB 或编译器。修改模型或 APP 源码时按新机部署指南准备对应开发环境。

## 学习源码的方法

1. 先在技术路线文档中找到一次构建的输入、输出和调用顺序，对照 `x280_local_build.json` 追踪一个已有 ZIP 的来源。
2. 比较 SLX、生成的模型 C、工程实时入口和最终 A2L，理解算法、调度与变量地址的不同职责。
3. 从 `MainWindow` 的上线按钮追到 `HostController`、`XcpSession` 和 `x280_xcp.client`，再沿 DAQ 数据返回路径看到 C++ 缓存和游标。
4. 做小范围修改后运行对应层测试；模型/CAN/调度修改需要新构建及真实目标验证，历史报告不自动适用于新产物。

当前文档依据已有机器和源码核对。本次没有在另一套新 Windows/Linux 上重装并验收；新机应按部署指南建立自己的版本、哈希和运行证据。
