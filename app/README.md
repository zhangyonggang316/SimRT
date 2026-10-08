# 上位机 APP

双击 [START_APP.cmd](START_APP.cmd) 启动已发布的 SimRT，默认加载
`../demos/Demo_XCP_Qt/demo.json` 指定的模型。启动不会自动连接目标机。

| 目录 | 用途 |
| --- | --- |
| `distribution/` | 正式 EXE、Qt/Python 依赖及许可证；必须完整保留 `_internal/` |
| `qt_xcp_host/` | Qt 界面、界面生命周期、C++ 数据核心，以及启动、构建、打包脚本 |
| `tools/` | 经测试后更新正式 APP 的发布工具 |

测试统一位于 `../tests/app/` 和 `../tests/protocol/`，Demo 模型位于 `../demos/`，
Windows DLL 编译器位于 `../toolchain/qt_toolchain/`。

无界面的 XCP、SSH、部署与目标状态服务独立位于 `../shared/python/`。
APP 使用共享层；Linux 管理脚本和自动化测试也可直接使用共享层，无需导入 Qt 或 APP 源码。

源码运行、依赖与打包方法见 [APP 开发说明](qt_xcp_host/README.md)。
`package_demo.ps1` 可输出自包含的便携 Demo 包；包内包含运行依赖和选定模型，
不会改变当前工程按功能分类的目录布局。
