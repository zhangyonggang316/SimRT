# Simulink 工具链与编译器

| 目录 | 用途 |
| --- | --- |
| `simrt_linux_target/` | MATLAB R2024b 硬件注册、统一 SimRT 功能库、代码生成钩子、实时模型运行器、A2L 与打包 |
| `portable-linux-toolchain/` | Windows 上运行的 Linux x86-64 GCC、binutils 和 sysroot |
| `qt_toolchain/` | 编译上位机 C++ DLL 的 Windows LLVM-MinGW |
| `tools/` | 分阶段生成模型、导出产物和本地编译辅助入口 |
| `development/` | MATLAB/Simulink 自动化工具、MCP 服务、Python 安装包；不是 APP 或实时机运行依赖 |

工程根目录是 `D:/05SimRT` 时，在 R2024b 中执行：

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
setupSimRTLinuxTarget(Persist=true);
verifySimRTEnvironment(Strict=true);
open_system('D:/05SimRT/demos/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single.slx');
```

随后使用 Ctrl+B 或 `buildSimRTLocal('simrt_rt_single')`。模型示例位于 [demos](../demos/README.md)，测试位于 [tests](../tests/README.md)，不在工具链源码中重复存放。系统安装与 CPU 调优归入 [linux](../linux/README.md)；随模型链接的实时运行器仍在 `simrt_linux_target/src`，保持构建依赖集中。

详见 [完整构建说明](../docs/TOOLCHAIN.md)、[库使用说明](../docs/ARK_IO.md)和 [PolarDriver 对照](../docs/POLAR_COMPARISON.md)。移动整个工程后重新注册，旧生成 Makefile/回执用于历史追溯，重新构建生成当前路径的产物。
