# 当前版本复现入口

当前仅交付 Python/PySide6 Qt APP：`Demo_XCP_Qt/START_DEMO.cmd`，模型仅有 `x280_rt_single`（1 ms）。旧 Tk 界面、入口、旧 APP 归档及其它三套模型已移除；Qt 共享服务和测试仍保留。

新机器从 [部署指南](NEW_MACHINE_DEPLOYMENT.md) 开始；先理解实现可阅读 [技术路线与源码](ARCHITECTURE.md)，故障按 [排查手册](TROUBLESHOOTING.md) 定位。日常构建步骤见 [模型与 XCP on UDP 工具链](TOOLCHAIN.md)，涵盖：

1. Windows / MATLAB R2024b 与 Ubuntu 环境。
2. 1 ms、单任务、ERT、可标定对象的模型配置。
3. XCP on UDP 的目标生成后处理、A2L 和 APP 一致性。
4. `generateX280RealtimeBundle` 的生成前检查、代码生成、打包与 RT 转换。
5. 本地 `build_local_bundles.py` 交叉编译、配套 A2L 生成及 APP 的 SSH 上传校验。
6. 本轮实际 ELF 与 A2L 配对及运行验证边界。

Qt APP 本身的依赖与构建见 [Qt 源码说明](../qt_xcp_host/README.md)。工程根目录 `requirements.txt` 安装当前 Qt 依赖。

当前 APP/构建证据见 [ZIP、层级及自动上线](../validation/app12_app13_20260919/README.md)，整理后检查见 [工程清理记录](../validation/project_cleanup_20260919/README.md)。历史阶段复现指南另存 `history/REPRODUCE_20260914.md`，其中旧 APP 路径仅供历史审计，不能作为当前启动或打包入口。
