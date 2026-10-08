# ARK I/O 库验证：2026-10-05

后续复验发现：下面的“库注册刷新”只调用了 `sl_refresh_customizations`，没有实例化库浏览器，遗漏了六个 `slblocks.m` 的解析错误。此处历史结果不能作为库浏览器可见性的证据。注册入口已修复，且已在用户当前 R2024b 会话安装并打开库浏览器；复验见 [安装修复记录](../ark_serial_install_20261005/README.md)。

## 已完成

| 检查 | 结果与证据 |
| --- | --- |
| 库生成 | `simrt_ark_library.slx` 链接三个串口模块、三个 DIO 模块；渲染图 `ark_library.png` |
| MATLAB | R2024b Update 10，10/10 对象及模型测试通过；`matlab_validation.json`、`matlab_build.log` |
| 桌面仿真 | 六模块集成模型返回硬件不可用状态；未把桌面零值视为实际 DIO 输入 |
| 本地完整构建 | Windows GCC 7.5.0 交叉编译成功，包含串口和 DIO 的 open/read/write/close 调用，生成 ELF/A2L/清单 ZIP |
| 持久安装 | MATLAB 安装目录不可写，已使用用户 `startup.m` 注册；另启动全新 MATLAB 会话，不手动添加目标路径，六个库链接均解析成功；`installation_check.json`、`installation_check.log` |
| 库注册刷新 | 新 MATLAB 会话执行 `sl_refresh_customizations` 正常退出，没有重建库时出现的 `slblocks` 解析警告；`library_browser_check.log` |
| C 后端 | GPIO v2 ABI、参数边界、初值原子设置、顺序、64 位掩码、错误返回、过期 token、释放和争用等检查通过；`../../tests/drivers/dio/results/dio_runtime_tests.json` |
| 真实目标清单 | SSH 只读检查成功；六个有效 UART，没有 GPIO chip/iManager 驱动；`hardware_inventory*.json`、`driver_assessment.json` |

构建 ZIP：`ark_io_codegen_check_local/20261005_083637_562.zip`。
SHA-256：`4324bd4ab07367fa5536c631c6b82a8f4d4171bd4880365573471e21ddad1fcd`。
生成源码及同轮元数据保存在 `ark_io_codegen_check_ert_rtw/`。

首次联调产生在驱动测试目录的过程构建已经清理；本轮可复验模型与最终报告均集中在此目录。`slprj` 和 `.slxc` 已按工程清理规则移除，不影响保留的源码、SLX 与 ZIP。

## 未完成的硬件验收

板载 DIO 为 ITE8518E / iManager。当前模块使用标准 GPIO v2，需要经过确认的 iManager GPIO 驱动及端子映射；目标机没有该驱动节点。因此，**库安装和软件测试通过不代表板载 DIO 已接通**。

未进行 COM 到 tty 的实线映射、串口电气回环、DIO 外部电平收发，也未验证新 I/O 引入后的 1 ms 最坏耗时。没有强制处理 ACPI 资源冲突，没有向未知接线输出电平，未改变目标机正在运行的主模型。

构建模型使用 `/dev/simrt-validation-no-serial` 与 `/dev/simrt-validation-no-gpio`，不作为可直接部署的硬件例程。普通仿真返回 `-38`；实际应用必须同时处理 Status。

使用方法、板卡差异、驱动来源及安装入口见 [ARK I/O 指南](../../../docs/ARK_IO.md)。
