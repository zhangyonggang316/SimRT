# ARK 串口与数字 I/O

**2026-10-07：按用户决定，停止 ARK 板载 GPIO/DIO 的驱动适配与硬件测试，不纳入当前功能及验收范围。** 现有 Digital IO 模块、测试模型和以下技术说明保留作参考。

## 入口与安装

MATLAB R2024b 库浏览器的项目入口统一为 **SimRT**，文件为
`toolchain/simrt_linux_target/drivers/ark/simrt_library.slx`。内部按功能分为 `Serial`、`Digital IO`、`EtherCAT`、`CAN`、`TCP UDP`，链接既有驱动模块，不复制驱动实现。串口和 DIO 分别从前两个子库选择。

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
installSimRTARKLibrary;
open_system('simrt_library');
```

安装先注册 SimRT 硬件目标和库，再保存 MATLAB 路径。安装目录不可写时，在当前用户 `Documents/MATLAB/startup.m` 的专用标记段注册路径；保留原有代码，并在首次修改既有文件时保存 `.before-simrt-ark` 备份。库保存在工程内，不拷贝到 MATLAB 安装目录。移动工程后需从新位置重新安装。

普通 `setupSimRTLinuxTarget` 同时注册该库；`setupSimRTARKLibrary` 用于当前会话。已经打开的 MATLAB 会话可执行上述安装命令。重新启动 MATLAB 后路径自动恢复。

### 库浏览器排查

项目只保留一个 [slblocks.m](../toolchain/simrt_linux_target/drivers/ark/slblocks.m) 注册入口，包含顶级 `Name`、`OpenFcn` 及 `Browser` 结构；`IsFlat=0` 使功能子库显示在 SimRT 内部。安装器会实例化库浏览器并刷新；已有会话更新后重新运行上面的安装命令，再检查 `SimRT` 的五个子库。浏览器不再单独列出 `SimRT ARK I/O` 或 `SimRT Linux ...` 根目录。

若仍不可见或出现旧根目录，先用 `which simrt_library -all` 确认当前工程的库路径，再用 `which slblocks -all` 检查是否存在旧工程副本。`open_system('simrt_library')` 只证明库文件能打开，不代表浏览器注册成功。`tests/tools/scripts/check_ark_installation.m` 会初始化真实库浏览器，检查唯一根目录、五个子库及每个子库的模块清单；验收命令为 `check_ark_installation(ShowBrowser=true)`。

功能库文件统一使用 `simrt_ark_library.slx`、`simrt_serial_library.slx`、`simrt_dio_library.slx`、`simrt_ethercat_library.slx`、`simrt_can_library.slx` 和 `simrt_network_library.slx`。工程内 SLX 的内部标识与链接已同步迁移；工程外自有模型需将库引用改为对应 SimRT 库后重新构建。这些功能库可用 `open_system` 打开，但只通过 `SimRT` 根目录注册到浏览器。

## 模块与连接

| 模块 | 参数或端口 |
| --- | --- |
| Serial Setup | Device、BaudRate、DataBits、Parity、StopBits、Mode、RS485Direction、SampleTime；输出 Connection(uint32)、Status(int32) |
| Serial Sent | 输入 Connection、Data(uint8 向量)、Length(uint32)、Enable(logical)；输出 Sent、Status |
| Serial Receive | BufferSize；输入 Connection；输出 Data(uint8 列向量)、Length、Status |
| DIO Setup | Device、LineOffsets、Direction、ActiveLow、InitialValues、SampleTime；输出 Connection、Status |
| DIO Read | LineCount；输入 Connection；输出 Values(logical 列向量)、Status |
| DIO Write | 输入 Connection、Values(logical 向量)、Enable；输出 Status |

每个资源由 Setup 独占，相应读写模块连接同一个 Connection。串口设备不能重复打开；GPIO 同一线路不能重复申请。串口写入可能只接受一部分数据，应根据 Sent 继续发送剩余字节。

DIO 输入与输出分别放置 Setup，并选择互不重叠的 LineOffsets。Read 的 LineCount、Write 的向量长度必须等于其 Setup 的线路数量；数据顺序与 LineOffsets 一致。InitialValues 在申请输出线路时原子生效，标量自动展开。Enable=false 不进行本次写入，但不会取消 Setup 设置的方向或初值。停止模型时释放资源，释放后的电平取决于驱动及硬件，不能当作自动置零。

所有参数的线路编号均为 Linux GPIO chip 内的 **offset**，不是连接器引脚编号。ARK 板载只有 8 路 DIO；通用后端最多支持 64 路，不代表该机有 64 个端子。驱动请求须使用经过核实的设备与映射，不能直接假定 `/dev/gpiochip0` 的 0–7 即板载 DIO。

桌面解释仿真明确返回 `-38`，不接触硬件；Linux 返回 0 表示该次调用成功，负数为 errno。例如 `-2` 设备不存在、`-9` 连接无效、`-11` 暂忙、`-13` 权限不足、`-16` 线路占用、`-22` 参数错误、`-25` 接口不支持。Read 出错时 Values 为零，必须同时检查 Status，不能把错误数据当作低电平。

## 当前硬件

用户提供的铭牌照片已确认机型为 **ARK-2120F**，Part No. 为 **`ARK2120F1501E-T`**。尚未取得该完整料号的专用配置表，不能仅凭料号推断定制串口功能；下述接口能力和针脚依据公开的标准 ARK-2120F 手册。

2026-10-05 对 `192.168.193.195` 只读检查得到 6 个有效 16550A UART：
`/dev/ttyS0`、`ttyS1`、`ttyS4`、`ttyS5`、`ttyS6`、`ttyS7`。`ttyS2/3` 不是检测到的有效 UART。机壳 COM1 等编号与 tty 节点的对应关系尚未通过接线确认。

COM 是串口接口。依据[研华 ARK-2120 官方手册](https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf)印刷页 5、14、15、36：标准 F 型 COM1/2 仅支持 RS232；COM3–6 可在 BIOS 的 `Advanced → Super IO Configuration` 中选择 RS232/422/485，默认 RS232。手册仅明确 COM3–5 支持 RS485 自动方向，不能将同一结论直接用于 COM6。软件参数不会切换硬件电气模式；当前库提供 RS232/RS485 参数，RS422 尚未作为独立选项验收。更多说明见[串口库 README](../toolchain/simrt_linux_target/drivers/serial/README.md)。

标准 DB9 接口的无硬件流控双端互连如下，连接器针号应以接口或转接板标识核对，不按彩虹线颜色推断：

| 模式 | 标准针脚 | 两个同类串口的接线 |
| --- | --- | --- |
| RS232 | 2 = RXD，3 = TXD，5 = GND | 2 ↔ 3，3 ↔ 2，5 ↔ 5 |
| RS485，两线 | 1 = DATA-，2 = DATA+，5 = GND | 1 ↔ 1，2 ↔ 2，5 ↔ 5 |

RS485 测试前需确认两端均为可支持 RS485 的接口，且 BIOS 已选择该电气模式。使用标准 COM3/4 且确认硬件自动方向时，模型设置 `Mode=RS485`、`RS485Direction=Hardware auto`；不能只修改模型参数就把 COM1/2 变成 RS485。

2026-10-07 用户改为使用已配置 RS485 的 COM3–6，并要求测试已接线的 COM5/6。已建立 [COM5/6 双向测试模型](RS485_COM56_TEST.md)，候选设备为 `/dev/ttyS6`、`/dev/ttyS7`；实际映射和接线针号尚待有效接收确认，本轮物理通信尚未通过。此前 COM1/2 彩虹线测试属于历史记录，不能作为板载 RS485 验收依据。

同一手册说明 DIO 为 **ITE8518E / iManager 的 8 位接口**，不是网卡或串口。F 型 10 针端子：1 为 +5V，2–9 为 DIO0–7，10 为 GND；L 型 DB9：1–8 为 DIO0–7，9 为 GND。具体接线必须以已确认机型和连接器编号为准，不按接口外形推断电压或隔离能力。

当前 DMI 只报告通用主板名；机型确认依据用户提供的铭牌照片，不能用通用 DMI 名称替代完整料号配置说明。

## DIO 驱动状态

**当前 ARK 尚不能直接运行板载 DIO 收发。** 目标机没有 `/dev/gpiochip*`，也未安装匹配的 SUSI/EAPI/iManager 驱动。新增模块采用 Linux GPIO character-device v2 接口，需要板载控制器的驱动先正确暴露 GPIO chip。仅创建库和编译 ELF 不会自动产生硬件驱动。

2026-10-07 已通过 SSH 再次只读确认上述状态。新增 [DIO 万用表测试模型](DIO_TEST.md)，默认手动保持 DIO0–3 输出并关闭回环检查，无需连接 DIO4–7；也保留接线后的可选回环检查。需先接通实际板载驱动并核对映射，不能仅靠加载模型完成硬件验收。

目标启动日志还有 `lpc_ich` 与 ACPI 的 GPIO 资源冲突；其 NM10 GPIO 不能据此视为外部 iManager DIO。本轮未强制加载冲突驱动、关闭 ACPI 保护或直接访问猜测的寄存器。

此前调查的未完成项包括匹配当前内核的 iManager GPIO 驱动、chip 标签、8 路 offset 和访问权限，现已停止推进。厂商 SUSI 是另一种 API，**当前 GPIO 后端不能直接调用 SUSI**，不能仅安装 SUSI 后填写 gpiochip 路径。[驱动调查](../tests/validation/ark_io_20261005/driver_assessment.json)仅作为历史参考。

## 构建与验证

模型使用 SimRT 硬件目标、固定步长 0.001 s；Ctrl+B 在 Windows 本地生成并交叉编译 Linux ELF。串口采用 termios，DIO 采用 GPIO v2 ioctl，不引入目标机现场编译。GPIO 驱动可能在内核内等待，不能把一次读写成功等同于 1 ms 最坏执行时间保证。

```matlab
addpath('D:/05SimRT/tests/tools/scripts');
validate_ark_library;
```

该命令安装库，执行对象测试、桌面仿真、六模块集成代码生成与完整本地构建。生成的 `ark_io_codegen_check` 是验证模型，使用故意不存在的设备名，不是可直接操作外部接线的用户示例。主模型 `simrt_rt_single` 不被替换。

离线 C 驱动验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/drivers/dio/run_offline_tests.ps1
```

完整构建结果见[首次验收记录](../tests/validation/ark_io_20261005/README.md)；先前六个根目录的安装与 Linux 伪终端复验见[历史安装记录](../tests/validation/ark_serial_install_20261005/README.md)。这些历史记录保留当时的目录结构；当前统一入口的实际浏览器检查见[统一目录验收](../tests/validation/simrt_library_20261006/README.md)。实际串口线缆回环、端子映射及通信负载下的实时性仍需单独验收；板载 DIO 实际电平测试已取消。
