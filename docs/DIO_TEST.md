# ARK DIO 万用表测试

**状态：2026-10-07 按用户决定停止 GPIO/DIO 适配及硬件测试。本文和模型仅保留作学习参考，以下步骤不再作为待执行任务。**

模型：[simrt_dio_loopback.slx](../demos/io/dio/simrt_dio_loopback/simrt_dio_loopback.slx)。使用 `SimRT / Digital IO` 中的 DIO Setup、DIO Write、DIO Read，固定 1 ms 单任务运行。沿用原文件名，默认采用手动输出，适合不接回环线、用万用表逐路测量；设置的电平持续保持到下一次修改。

**2026-10-07 复查：当前 ARK 仍没有 GPIO chip 设备和匹配的板载 DIO 驱动，暂不能通过此模型控制实际引脚。** 模型可以在 R2024b 打开、仿真和本地构建；板载驱动接通后填写真实设备和线路映射，再进行以下测试。此状态不能说明 DIO 硬件损坏。

## 万用表测量点

本次不连接 DIO 输出与输入。依据[研华 ARK-2120 手册](https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf)表 2.6（印刷页 17），标准 **ARK-2120F 的 10 针接口**对应：

| 测量点 | 接口针号 | 表笔 |
| --- | ---: | --- |
| GND | 10 | 黑表笔固定接此处 |
| DIO0 | 2 | 红表笔 |
| DIO1 | 3 | 红表笔 |
| DIO2 | 4 | 红表笔 |
| DIO3 | 5 | 红表笔 |

万用表使用直流电压档，按连接器上的针号核对，不按线色推断。针 1 是 +5 V，本次不连接；不要用导线将引脚相互短接，测量时避免表笔同时接触相邻针脚。本表不适用于 ARK-2120L 的 DB9 接口。记录各路高、低状态下的实际电压，不把针 1 的 +5 V 标注当成 DIO 高电平电压保证。

## 配置模型

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
setupSimRTLinuxTarget;
open_system('D:/05SimRT/demos/io/dio/simrt_dio_loopback/simrt_dio_loopback.slx');
```

打开两个 `DIO Setup` 模块：

- `Device`：填写已经确认属于板载 iManager DIO 的 GPIO chip 路径。
- `DIO Output Setup`：Direction 为 Output，LineOffsets 按物理 DIO0、DIO1、DIO2、DIO3 的顺序填写，InitialValues 为 false。下面的高低状态表按 `ActiveLow=false` 使用。
- `DIO Input Setup`：Direction 为 Input，LineOffsets 按物理 DIO4、DIO5、DIO6、DIO7 的顺序填写。万用表测试无需连接这些输入。

默认设备 `/dev/simrt-ark-dio-unconfigured` 故意不存在，避免误操作其他控制器。示例 offsets `[0 1 2 3]` 和 `[4 5 6 7]` **不是已验证的板载映射**；GPIO offset 不等于连接器针号。输入、输出不能申请相同线路。当前后端要求 GPIO character-device v2，单独安装厂商 SUSI 用户库不能直接替代该接口。

保存模型后按 Ctrl+B，在模型旁的 `simrt_dio_loopback_local/` 取得新 ZIP。通过 SimRT APP 上传并启动此测试模型，再加载同轮 A2L；使用 UDP 5555 上线。

## 手动测量步骤

在 APP 的标定页修改以下 `uint8` 参数并回读确认：

| 参数 | 默认值 | 含义 |
| --- | ---: | --- |
| `DIO_Enable` | 0 | 0 持续写入全低；1 开启所选输出模式 |
| `DIO_Automatic` | 0 | 0 使用手动掩码，保持不变；1 自动按 1、2、4、8 循环，每种保持 1 秒 |
| `DIO_ManualMask` | 0 | 手动模式下取 0–15，bit0–3 分别控制 DIO0–3 |
| `DIO_CheckLoopback` | 0 | 0 关闭回环判定及错误计数；接好回环线后才设置为 1 |

1. 保持 `DIO_Automatic=0`、`DIO_CheckLoopback=0`、`DIO_ManualMask=0`。
2. 确认 `DIO_OutputSetupStatus=0`、`DIO_WriteStatus=0`，再把 `DIO_Enable` 改为 1。
3. 依次设置下表的 `DIO_ManualMask`，回读 `DIO_CommandMask` 确认命令生效，待万用表读数稳定后记录四路电压。每个掩码会一直保持，无需追踪一秒切换的波形。

| 掩码 | DIO0 | DIO1 | DIO2 | DIO3 |
| ---: | --- | --- | --- | --- |
| 0 | 低 | 低 | 低 | 低 |
| 1 | 高 | 低 | 低 | 低 |
| 2 | 低 | 高 | 低 | 低 |
| 4 | 低 | 低 | 高 | 低 |
| 8 | 低 | 低 | 低 | 高 |
| 15 | 高 | 高 | 高 | 高 |

**本次以输出 Setup/Write 状态和万用表实际读数判断输出。** `DIO_Ready` 汇总输入与输出四个驱动状态，不是万用表测试的输出就绪条件。DIO4–7 未接线时，`DIO_InputMask` 没有回环意义；不能用输入读数、`DIO_Valid`、`DIO_Matched` 判断输出硬件好坏。默认关闭回环后，Valid、Matched 和 MismatchSamples 为 0 是正常状态。

结束前将 `DIO_Enable=0`，回读 `DIO_CommandMask=0`，确认 `DIO_WriteStatus=0` 并测量输出已回到低状态后停止模型。关闭模型会释放 GPIO 线路，释放后的电平由硬件和驱动决定，不能将停止本身当作置零操作。

## 可选回环测试

以后需要同时检查输入功能时，可按已核对的接口针号断电连接以下四组，避免与本次万用表流程混用：

| 回环 | 输出端针号 | 输入端针号 |
| --- | ---: | ---: |
| DIO0 → DIO4 | 2 | 6 |
| DIO1 → DIO5 | 3 | 7 |
| DIO2 → DIO6 | 4 | 8 |
| DIO3 → DIO7 | 5 | 9 |

接好线后，确认四个 `DIO_*Status` 都为 0 且 `DIO_Ready=1`，设置 `DIO_CheckLoopback=1`、`DIO_Enable=1`。可以保持手动模式，也可以设置 `DIO_Automatic=1`，每秒依次输出 1、2、4、8。输入掩码 bit0–3 对应 DIO4–7，正确回环时与命令掩码相等。

| 观测量 | 回环判定方式 |
| --- | --- |
| `DIO_OutputSetupStatus`、`DIO_InputSetupStatus` | 方向与线路申请状态，0 为成功 |
| `DIO_ReadStatus`、`DIO_WriteStatus` | 当前读写调用状态，0 为成功 |
| `DIO_Ready` | 四个驱动状态均成功才为 1 |
| `DIO_Valid` | 回环已启用、Ready、输出已启用、输出变化后稳定 20 ms 才为 1 |
| `DIO_Matched` | 仅 Valid=1 且输入掩码等于命令掩码时为 1 |
| `DIO_MismatchSamples` | 累计有效比较中的不一致采样数；关闭输出或回环判定时清零 |

每次切换输出后保留 20 ms 稳定时间，此时 Valid 和 Matched 为 0，属于正常状态。无驱动或读写失败时，不会将输入零值认作回环成功。

## 常见结果

- Windows 普通仿真：状态 `-38`（无硬件访问），Ready/Valid/Matched 均为 0。
- Linux 状态 `-2`：设备路径不存在；本轮未配置设备的模型属于这种情况。
- `-13`：访问权限不足；`-16`：线路已被其他进程占用；`-25`：驱动不支持 GPIO v2。
- 输出状态均为 0，但万用表测得电平不随命令变化：核对物理针号、输出方向、offset 映射和实际电气条件；软件调用成功不等于硬件电压已验证。
- 仅在接好回环线并启用回环判定后，Ready=1 但稳定后 Matched=0 才需要检查回环接线、方向、offset 顺序及实际电平。

可复现生成入口为 `createSimRTDIOLoopbackModel`，已有模型不会被默认覆盖。控制逻辑源码位于 `+simrtlinux/+dio/loopbackPattern.m` 和 `loopbackMonitor.m`。构建与仿真证据见 [DIO 测试模型验证](../tests/validation/dio_test_20261007/README.md)，不代表实际引脚已通过测量。
