# ARK DIO 万用表测试模型验证

**2026-10-07：按用户决定停止板载 GPIO/DIO 适配和硬件测试。以下软件验证结果保留为历史记录，不再安排后续物理测试。**

模型：`demos/io/dio/simrt_dio_loopback/simrt_dio_loopback.slx`。
用户已明确不接外部回环线，使用万用表测量 DIO0–3 输出。模型沿用文件名，默认手动保持输出且关闭回环检查；具体测量点及操作见 [DIO 测试指南](../../../docs/DIO_TEST.md)。

## 本轮结果

- 1 ms 固定步长，使用现有 DIO Setup、Write、Read 库模块。
- 自动模式按 1、2、4、8 掩码各保持 1000 个采样；手动模式覆盖 0–15。
- 默认 Enable=0、Automatic=0、ManualMask=0、CheckLoopback=0。手动输出持续保持；关闭输出或回环检查均会清除不一致计数。
- 连续 2100 个采样确认手动掩码 8 保持不变；关闭回环检查时，即使输入全低、驱动状态成功，也不产生比较有效标记、通过标记或错误计数。
- 可选回环检查屏蔽输出变化后的 20 ms；驱动错误、未启用、尚未稳定均不报告通过。
- Windows 桌面仿真通过，四个驱动状态均为 -38，Ready/Valid/Matched 均为 0。
- R2024b 本地代码生成、Linux x86-64 交叉编译、A2L 导出和 ZIP 哈希校验通过。生成代码包含实际 GPIO open/read/write/close 调用。
- A2L 包含四个标定控制参数、输入/输出掩码、驱动状态及回环结果。导出器跳过内部 MATLAB System 对象结构的提示不影响这些标量接口。
- APP 的 ZIP/清单/ELF 校验及 A2L 解析结果见 `app_payload.json`，检查四个标定参数和全部十个预期观测量。
- 模型已保存并在 R2024b 中打开，Hardware 页构建按钮可用，见 `hardware_button.json`。

部署包位于模型同级 `simrt_dio_loopback_local/`。本轮对应 ZIP 路径、精确产物哈希和构建目录见 `matlab_validation.json` 的 `build` 字段；早期 ZIP 默认自动输出且没有回环开关，不用于本次万用表流程。

## 硬件前提

通过已保存的 APP 凭据对 `192.168.193.195` 做了只读检查，证据为 `target_inventory.json`：

- 目标机 `ark2120`，内核 `7.0.0-34-realtime`。
- `/dev/gpiochip*`、GPIO sysfs chip 清单均为空。
- 动态库缓存无 SUSI/EAPI/iManager；扫描未发现对应板载 DIO 驱动。

**未验证实际引脚电平，不能据此判断硬件正常或损坏。** 默认设备 `/dev/simrt-ark-dio-unconfigured` 为未配置占位符；待匹配驱动接通且 chip/offset 映射核实后，更新两个 Setup 块并重新构建。现有后端使用 GPIO v2，SUSI 是另一套 API。

## 复验与源码

`validateDIOLoopback.m` 包含模式切换、全部手动掩码、稳定等待、错误抑制、失败计数重置、桌面仿真和完整本地构建检查。重新生成前应关闭测试模型并将已有 SLX 另存，生成器默认不覆盖已有文件。`model.png` 为 MATLAB 导出的模型图，`matlab_validation.log` 保留构建输出。

源码入口：`createSimRTDIOLoopbackModel.m`、`+simrtlinux/+dio/loopbackPattern.m` 和 `loopbackMonitor.m`。本轮没有上传、启动测试 ELF，没有改动正在运行的实时模型、GPIO 方向、电平或系统驱动。
