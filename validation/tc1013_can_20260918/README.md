# TC1013 CAN 验证记录

验证对象：`x280_linux_target/drivers/tc1013/x280_can_library.slx` 和 1 ms 示例 `x280_can_loopback.slx`。

| 记录 | 结果与范围 |
| --- | --- |
| `matlab_tests.json` | 28/28 通过：16 项 System 对象测试、2 项模型回环测试、10 项目标配置回归测试 |
| `driver_preparation_tests.txt` | 12/12 通过：ELF 架构、依赖文件、哈希、上传不完整、拒绝覆盖已有目录 |
| `runtime_offline_tests.json` | C mock 测试及 Linux x86-64 交叉编译、链接通过；未加载厂商实际 SDK |
| `final_build.json` | 最终本地构建结果，固定步长 0.001 秒；记录模型、编译器和 ELF 哈希及最终三件套路径 |
| `local_build.log` | 最终 Simulink 代码生成、交叉编译及 A2L 导出日志 |
| `library.png` / `loopback_model.png` | 最终模型库和双通道测试模型截图 |
| `sdk_contract.md` / `sdk_manual.txt` | 厂商资料的接口核对及 PDF 文本提取 |

模型回环测试在 0 至 0.02 秒验证 21 个采样点：CAN1 接收 ID 514、数据 `[8 7 6 5 4 3 2 1]`；CAN2 接收 ID 257、数据 `[1 2 3 4 5 6 7 8]`，有效标志为 true，初始化和收发状态为 0。最终构建完成后再次运行这两项测试，均通过。模型连线检查通过，保存模型与构建记录哈希一致，Qt APP 的 `validate_payload` 校验通过。

`intermediate_builds/` 是本次调试产生的中间构建归档，里面的绝对路径和哈希属于各自历史版本；不用于部署。最终交付目录只包含 ELF、A2L、JSON 三个文件，位置以 `final_build.json` 为准。

本次没有执行 SSH 部署，没有访问 USB/CAN 硬件，也没有验证实际 1 ms 调度或总线通信。用户提供的资料缺少 `libTSCANApiOnLinux.so`、`libTSH.so`、`blf.so`；需取得匹配的厂商 Linux x86-64 SDK 后按驱动目录 README 完成实机验证。
