# 实时机界面与通信库

本轮对应需求：本地显示时间使用 ms、不显示 Linux 版本及命令行、显示所有接口 IP、APP-14、TCP/UDP、EtherCAT、RS232/RS485。

## 模型库入口

库浏览器统一入口为 `SimRT`，内部按功能分为 `Serial`、`Digital IO`、`EtherCAT`、`CAN`、`TCP UDP`。R2024b 安装及当前板载驱动限制见 [ARK I/O](ARK_IO.md)。原 SLX 文件和内部模块标识继续兼容已有模型，但不再单独注册浏览器根目录。

MATLAB R2024b 中运行 `setupSimRTLinuxTarget` 注册硬件目标和全部通信库。

| 功能 | SLX | 模块 |
| --- | --- | --- |
| TCP/UDP | `toolchain/simrt_linux_target/drivers/network/simrt_network_library.slx` | TCP Setup、TCP Sent、TCP Receive |
| 串口 | `toolchain/simrt_linux_target/drivers/serial/simrt_serial_library.slx` | Serial Setup、Serial Sent、Serial Receive |
| EtherCAT | `toolchain/simrt_linux_target/drivers/ethercat/simrt_ethercat_library.slx` | EtherCAT Exchange |

各库使用 MATLAB System 对象，通过现有本地交叉编译流程将 Linux 驱动加入生成的 ELF；目标机无需安装 MATLAB 或编译器。普通 MATLAB 仿真明确返回未启用状态，不模拟成功收发。代码生成检查模型位于 `tests/validation/communication_20260927/communication_codegen_check.slx`，用于检查全部模块编译，不应直接部署到未知接线设备。

网口支持数值 IPv4、TCP 客户端/服务器和 UDP；TCP 是字节流，应用协议需要自己定义帧格式。后台线程与有界队列隔离网络等待，队列满、未连接等情况通过状态输出报告。详见 [网口说明](../toolchain/simrt_linux_target/drivers/network/README.md)。

串口使用 Linux termios，非阻塞收发，发送端返回实际已发送字节数；部分发送需调用方继续发送剩余字节。RS485 支持硬件自动方向或驱动 `TIOCSRS485`，不支持的驱动明确报错。详见 [串口说明](../toolchain/simrt_linux_target/drivers/serial/README.md)。

EtherCAT 内置官方 SOEM v1.4.0，提供默认 PDO 字节映像交换及工作计数器检查；需要专用网口、从站匹配的输入/输出长度和 raw socket 权限。当前不含设备专用 SDO、PDO 重映射或 DC 同步；不能代替特定伺服/IO 的工程配置。详见 [EtherCAT 说明](../toolchain/simrt_linux_target/drivers/ethercat/README.md)。

## ARK-2120 串口

依据 [研华官方 ARK-2120 手册](https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf) 的功能规格及 COM 接口章节：

| 型号 | RS232 | RS232/422/485 可切换 | 切换方式 |
| --- | --- | --- | --- |
| ARK-2120L | COM1、COM3、COM4 | COM2 | 内部线缆 1700001967 和 J2 跳线 |
| ARK-2120F | COM1、COM2 | COM3–COM6 | BIOS Super IO Configuration |

手册明确列出的 RS485 自动方向支持为 L 的 COM2、F 的 COM3–COM5，不能推定 F 的 COM6 同样支持。RS485 引脚为 DB9 1=DATA-、2=DATA+、5=GND。

用户提供的铭牌已确认 ARK-2120F / ARK2120F1501E-T；DMI 仍只有通用 OEM 字段。BIOS 电气模式及 DB9 到 `/dev/ttyS*` 的实际对应仍需确认；系统生成的 32 个 ttyS 节点不代表 32 个物理串口。COM1/2 直接接线应按 RS232 验证，板载 RS485 应选用支持该模式的 COM 口。接线和本轮安装复验见 [ARK I/O](ARK_IO.md)。

## 上位机 IP 设置

SimRT 上位机通过 `demos/Demo_XCP_Qt/START_DEMO.cmd` 启动，程序文件为 `app/SimRT.exe`，已配置窗口及 Windows 应用图标。

SimRT 的“实时机 → 模型部署 → 网络接口 / IPv4”列出实时机所有接口。选择网口后设置静态 IPv4、掩码/前缀及可选网关，确认后用管理员密码执行。密码只通过 SSH 标准输入发送，不写入配置或日志。

当前支持 Netplan + systemd-networkd 的独立网口配置。点击“应用并保存 IPv4”后，配置经 SSH 校验并持久保存，重启后继续使用；保留 Wi-Fi 凭据、IPv6 和其他网口设置，尚未提供 DHCP 切换。当前 SSH 管理地址在本次连接期间保留，其他全局 IPv4 按确认窗口说明替换。配置失败或 45 秒内未确认时自动回滚运行状态及配置文件。

上位机的“Ubuntu 主机”目标 IPv4 可在线编辑，回车或离开输入框后提交并独立保存，重启 APP 会恢复该地址，不依赖是否记住 SSH 密码。XCP 在线切换时先停止采集、恢复标定并断开旧会话，再连接新地址；原先正在采集时重连成功后恢复 DAQ。该地址输入用于指定连接目标，修改目标网口自身地址应使用上述“网络接口 / IPv4”入口。

2026-09-27 历史验证记录：实际物理网口 IP 未在本轮验证中修改。配置、校验和真实超时回滚已在目标机的独立网络命名空间内验证。当前 IPv4 配置验证见 [本轮记录](../tests/validation/xcp_5555_ui_20261005/README.md)。

## 验证边界

当前记录：[本轮验证目录](../tests/validation/communication_20260927/README.md)。已进行真实 Linux localhost TCP/UDP、串口 PTY、EtherCAT 适配层替身及真实 SOEM 链接检查。PTY 不能证明 RS232/485 电气接线；SOEM 链接或替身测试不能证明已与真实 EtherCAT 从站通信。现场还需按实际设备验证串口与 EtherCAT，测量通信引入的执行耗时及 1 ms 调度指标。

本地显示已更新到 `192.168.219.195` 的专用 tmux 会话，单一全屏、全部接口地址、时间单位 ms；未执行重启。部署工具及数据来源见 [显示界面说明](../linux/console/README.md)。
