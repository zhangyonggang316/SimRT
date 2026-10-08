# Demo 工程

| 目录 | 用途 |
| --- | --- |
| `Demo_XCP_Qt/` | 主模型 `simrt_rt_single`、1 ms XCP 演示配置、配套部署 ZIP 和生成代码 |
| `calibration/` | 标定基础示例 `simrt_calibration_demo.slx` |
| `io/serial/` | COM5/6 RS485 双向测试模型 |
| `io/tc1013/` | CAN 驱动示例模型 |
| `io/dio/` | 已停止适配的 DIO 参考模型与历史构建证据 |
| `app_examples/` | 上位机示例工程扩展位置 |

[启动 XCP Demo](Demo_XCP_Qt/START_DEMO.cmd) 会调用工程 `app/distribution/SimRT.exe`。APP 可执行文件不在模型目录重复存放；模型选择由 `Demo_XCP_Qt/demo.json` 中的相对路径决定。

模型的 `_local/` 保存三文件部署 ZIP，`_ert_rtw/` 保存生成代码与当轮构建证据，方便学习和对照。目录迁移不会证明旧模型已重新完成硬件验收。重新编译时先按 [工具链入口](../toolchain/README.md)注册新位置，再执行 Ctrl+B。
