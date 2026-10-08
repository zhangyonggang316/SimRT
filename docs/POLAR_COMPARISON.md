# PolarDriver 对照与 SimRT 构建优化

2026-10-07 对照用户提供的 `PolarDriver_V3.2.2.1_Beta(R2022a~R2025b)/PolarDriver.mltbx`。这是另一套目标硬件和运行时方案，本轮仅阅读包内可读注册文件、TLC、构建钩子和元数据，不运行安装器，不将其驱动或运行库加入 SimRT。

包版本为 3.2.2.1，元数据声明从 R2022a 起支持 Windows。用户原方案使用 R2023b 注册；当前 SimRT 的独立交叉工具链清单也记录来源于该 R2023b 环境，使用 GCC 7.5.0。**编译器这一层已经借鉴，不需要再次安装一套同名工具链。** 当前 SimRT 继续只验收 MATLAB R2024b。

## 可借鉴的做法与处理结果

| 做法 | PolarDriver 中的依据 | SimRT 处理 |
| --- | --- | --- |
| 正式工具链注册、统一功能库入口 | `simulink/coder/rtwTargetInfo.m`、`slblocks.m` | 已有同类机制，保留唯一 SimRT 根库和专用工具链；不增加 GY 系列目标 |
| 在生成代码前检查模型约束 | `GY1005_make_rtw_hook.m` 的 `entry` 阶段 | 已增强：早期检查固定步长、单任务、C 语言、目标硬件及已保存状态；错误周期在生成模型 C 之前拒绝 |
| 分阶段处理编译和打包 | 同一钩子的 `after_tlc`、`before_make`、`exit` | 沿用既有 BuildInfo 和本地打包链；修正模型重新配置时默认 IP 覆盖用户 IP 的问题，并保护已打开的同名不同路径模型 |
| 将工具链依赖随开发环境管理 | `env/x86_64-linux`、`env/usr` | 新增必要工具及 sysroot 文件预检和 GCC 目标身份检查，缺少 G++、汇编器、链接器、归档器、ELF 检查器或 sysroot 基础文件时提前报告 |
| 库和注册入口集中管理 | `slblocks.m`、目标注册入口 | 移除程序化构建中的重复 setup，顶层统一刷新；路径或定义未变化时复用注册 MAT 并跳过刷新，变化时刷新一次 |
| 发布包与实际编译参数一致 | 构建结束后调用模型打包函数 | 对照中发现并修复 SimRT 原生编译 1024 块、离线包却记为或重建为 64 块的 DAQ 缓冲差异；两条路径统一配置，清单从真实编译定义读取 |
| 驱动模块与依赖分离 | `simulink/blocks` 各功能目录独立 | SimRT 已按功能库和 Native 后端分离，继续按模型所用模块加入源码/依赖；保留源码说明方便学习 |
| 单一安装包和配套帮助 | `.mltbx`、`helpdoc` | 可作为后续发布方式；本轮保留工程内可读源码和已有安装入口，避免重复打包交叉编译器和大体积环境 |

本轮在 R2024b 上通过 19 项 MATLAB 回归、41 项 Python 回归，并完成独立 1 ms 模型的本地构建和 APP 离线导入。单次测量中，注册强制刷新约 48.45 s，配置不变时复用约 2.81 s；这是注册开销的差异，不是模型运行速度的提升。损坏的派生注册缓存也能自动重建。

## 不适合直接搬过来的设置

1. `GY1005` 使用 Xenomai/Cobalt/Alchemy 库和入口包装，属于不同运行时。SimRT 当前为 PREEMPT_RT；替换链接库不能直接获得相同实时性，也不适用于已经验证的调度入口。
2. `GY1005_make_rtw_hook.m` 显式加入 AVX-512 编译参数。这些参数属于另一硬件目标，不能用于本工程的 Atom D2550 目标配置；本轮保持当前通用 x86-64 指令设置。
3. `toolstrip/sl_customization.m` 对 `buildHardwareBoardAction2` 无条件返回 `Disabled`。若加入公共 MATLAB 路径，可能禁用其他目标的 Hardware 构建按钮。当前 R2024b 路径未加载这份脚本，本轮没有安装或修改 PolarDriver，也没有以全局强制启用的方式覆盖其他工具箱。
4. 私有板卡、串口通道编号和方向控制不能直接用于 ARK。COM5/6 的接线及物理映射问题仍需按[当前实测](RS485_COM56_TEST.md)确认；本轮构建优化不等于串口已接通。

包内有 592 个受保护 `.p` 文件。安装器、主类及部分注册回调的内部实现未读取，不能将函数名或公开钩子推定为完整实现。上述建议仅依据实际可见的文件。

## 新增或改变的使用方式

```matlab
% 省略 Address、Username、BuildDirectory 时保留模型中的已有值。
configureSimRTModel('my_model');
buildSimRTLocal('my_model');

% 只有显式提供非空值才覆盖；空字符串同样表示保留。
configureSimRTModel('my_model', Address="192.168.193.195");

% 独立查看工具链缺失项与目标架构。
report = inspectSimRTToolchain;
inspectSimRTToolchain(Strict=true);

% 即使工具链缺失，非严格检查也返回失败报告和缺失清单。
report = verifySimRTEnvironment(Strict=false, ProbeTarget=false);

% 更改外部 MATLAB 自定义设置后，可显式强制刷新。
setupSimRTLinuxTarget(Refresh=true);
```

新建模型仍使用其创建参数或硬件注册中的缺省地址；本轮没有将已有模型统一改成某个固定 IP。配置入口明确选择 C 语言，与现有单任务实时运行器一致。模型有未保存修改时，`buildSimRTLocal` 会先拒绝构建。

运行参数 [realtime_config.json](../toolchain/simrt_linux_target/registry/realtime_config.json) 是两个本地构建入口共享的 DAQ 配置源：1024 个保留块、1 MiB 总预留池。打包的 `build_spec.json` 从 BuildInfo 读取本次实际定义；编译脚本拒绝清单值与 `-D` 定义矛盾的包。旧生成包继续作为历史证据，未被批量重写；需要采用新行为时重新构建。

## 实现与验证入口

- 配置保留及文件身份检查：[configureSimRTModel.m](../toolchain/simrt_linux_target/configureSimRTModel.m)。
- 构建早期检查：[onCodeGenEntry.m](../toolchain/simrt_linux_target/+codertarget/+simrtlinuxssh/+internal/onCodeGenEntry.m)、[inspectSimRTToolchain.m](../toolchain/simrt_linux_target/inspectSimRTToolchain.m)。
- 注册调用去重：[setupSimRTLinuxTarget.m](../toolchain/simrt_linux_target/setupSimRTLinuxTarget.m)、[setupSimRTARKLibrary.m](../toolchain/simrt_linux_target/setupSimRTARKLibrary.m)。
- 清单与编译一致性：[prepareSimRTAppBundle.m](../toolchain/simrt_linux_target/prepareSimRTAppBundle.m)、[本地构建脚本](../toolchain/simrt_linux_target/tools/build_model.py)。
- [本轮验证记录](../tests/validation/polar_comparison_20261007/README.md)。

这些修改改善构建正确性、错误定位和重复操作开销，没有更换实时内核或降低实时线程优先级，也不宣称能进一步缩小硬件抖动。本轮不重新启动目标机上的运行模型。
