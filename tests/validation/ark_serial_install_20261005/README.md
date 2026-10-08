# ARK 库安装与串口复验：2026-10-05

## 安装修复

用户当前打开的 MATLAB R2024b 会话未加载项目库路径；此外，实际初始化库浏览器时，六个项目 `slblocks.m` 均出现 `Simulink:dialog:parseError`。此前只验证库文件能加载，遗漏了浏览器解析步骤。

ARK、DIO、Serial、Network、EtherCAT、TC1013 注册函数已统一返回 `blkStruct`，补全顶层 `Name`、`OpenFcn`，保留原有 `Browser` 信息。ARK 自定义排序将 `SimRT ARK I/O` 放在库浏览器前部。安装器现在实际初始化并刷新浏览器，解析警告按错误处理。

已在用户原有 MATLAB R2024b 桌面会话（PID 29452）执行安装，保留已打开的用户会话；库浏览器与 `simrt_ark_library` 已打开。安装路径保存在当前用户 `Documents/MATLAB/startup.m` 的专用注册段中，保留原有内容；另一个全新 MATLAB 进程确认无需再次添加目标路径。

| 验证 | 结果与证据 |
| --- | --- |
| 当前 R2024b 桌面 | 实际读取两个已打开的浏览器组件：六个项目库均在目录中，`SimRT ARK I/O` 排第一，选中后包含六个预期模块；[catalog_retest/installation_check.json](catalog_retest/installation_check.json) |
| 全新 R2024b 会话 | 持久路径、实际浏览器目录和六模块调色板均验证通过；[catalog_fresh_session/installation_check.json](catalog_fresh_session/installation_check.json) |
| 对象与代码生成 | `testDIO` 7 项、`testSerialEtherCAT` 3 项通过，包含模块端口及代码生成；[fresh_session.log](fresh_session.log) |
| 串口协议 | 序号、方向、随机标记、负载和 CRC 检查通过，Linux ELF 在本地交叉编译；[build_report.json](../../drivers/serial/physical_loopback_results/build_report.json) |
| Linux 伪终端 | 6 项通过：RS232/硬件自动方向双向收发、损坏帧、超时、SIGTERM、RTS 不支持；所有场景恢复原始 termios；[pty_tests.json](pty_tests.json) |
| 恢复逻辑复验 | 调整测试程序后重跑 6 项 PTY，加上 6 项 RS485 状态恢复回归，全部通过；[pty_restore_retest.json](pty_restore_retest.json) |

本轮未更改生产驱动实现；修复只涉及库注册、安装验收及串口测试程序。六模块完整 ELF/A2L/ZIP 构建的历史产物见 [ARK I/O 验证](../ark_io_20261005/README.md)。本轮对象测试重新执行了端口和代码生成检查。目录检查使用本机 R2024b 提供的浏览器组件接口；其他 MATLAB 版本须重新适配和验收。

## 物理测试状态

用户铭牌确认 ARK-2120F / ARK2120F1501E-T。依据[研华官方标准手册](https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf)，COM1/2 为 RS232，COM3–6 可在 BIOS 设置 RS485，COM3–5 明确支持自动方向。尚无完整定制料号配置表，不能据料号推断额外功能。

用户再次确认 COM1/2 已接彩虹线后，已进行一次受限的 **RS232 实机诊断，结果失败**。这不是 RS485 验收；接线针号和转换器仍未得到确认。

预检使用 ACPI `UAR1/UID=1`、`UAR2/UID=2` 及 `0x3F8/IRQ4`、`0x2F8/IRQ3`，共同支持 COM1 对应 `ttyS0`、COM2 对应 `ttyS1`。无端口占用、serial-getty 或串口控制台。证据：[com12_preflight.json](com12_preflight.json)。

115200、8N1、总限时 3 秒：COM1 发送 256 字节，COM2 只读到 1 字节，未验证任何完整帧，第一方向在 3001 ms 返回 `-110/ETIMEDOUT`。两口均记录一次 break，未进入反向发送。结果不证明接线连通，不据此断言硬件损坏。失败后未重试或向其他串口发送数据。完整证据：[com12_physical_test.json](com12_physical_test.json)。

原测试器同时报告 `restore_ok=false`，具体为 RS485 配置写回/校验失败，没有 termios 恢复失败信息。发现原恢复逻辑无条件调用 RS485 setter，即使读回状态未变也会因 RS232 驱动不支持写入而报错；现已改为先比较状态，仅在不一致时写回并再次校验。离线回归覆盖无需写入、实际恢复、首次读取失败、写入失败、读回不一致及读回失败六种情形。**原始物理测试的失败标志保留，没有追溯改成恢复成功。**

随后只读查询显示两口均为 9600 波特率、Linux RS485 状态全零，UART 收发计数保持不变，无占用进程；未进行参数写入或再次发送。该查询记录当前状态，不能替代测试前未保存到报告的完整 RS485 快照。证据：[com12_post_state.json](com12_post_state.json)。

修正后的测试 ELF SHA-256 为 `3180147d51f43dc234bc6a7f164fa93f852a8efcb98749e30fac956d526ffe27`，已通过 PTY 和恢复逻辑回归，尚未再次运行物理通信。原实机记录中的 `be22975d...` 是修复前版本。

- COM1/2 直接做 RS232 回环：2↔3、3↔2、5↔5。
- 板载 RS485 建议使用 COM3/4，两端 BIOS 设 RS485：1↔1（DATA−）、2↔2（DATA+）、5↔5（GND）。
- DIO 仍缺目标机 iManager/GPIO 驱动，未进行物理电平测试。

针号必须以连接器标识为准，不按线色推断。下一次物理测试需要先核对上述接线和电气模式；不能把 COM1/2 直连结果标记为板载 RS485 通过。PTY 及离线回归不证明电气链路或 1 ms 实时性。

## 复验入口

MATLAB R2024b：

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
installSimRTARKLibrary;
addpath('D:/05SimRT/tests/tools/scripts');
check_ark_installation(ShowBrowser=true);
open_system('simrt_ark_library');
```

本地构建串口测试程序：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/drivers/serial/build_physical_loopback.ps1
```

仅在已确认两端 tty、接线和电气模式后，物理测试程序的命令格式为：

```sh
./serial_physical_loopback.elf "$DEVICE_A" "$DEVICE_B" "$MODE" 115200 32 10000
```

`MODE` 为 `rs232` 或与 BIOS 匹配的 `rs485-auto`；默认整次测试限时 10 秒，交替发送 32 轮，每帧 256 字节，校验两个方向的完整帧，退出时恢复串口配置。Linux RTS 模式需底层驱动实际支持，不能代替 BIOS 电气模式选择。
