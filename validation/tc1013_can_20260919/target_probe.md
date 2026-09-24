# TC1013 目标机只读检查

检查时间：2026-09-19 00:38（Asia/Shanghai）。详细证据见 `target_probe.json`，复现脚本为 `target_probe.py`。脚本从需求文档 ENV-03 读取 SSH 凭据，不把密码写入报告。

## 已确认

- SSH 可连接 `192.168.219.86`，用户 `zh`。
- Ubuntu 22.04.5 LTS，x86-64，内核 `5.15.129-rt67-intel-ese-standard-lts-rt`，`/sys/kernel/realtime = 1`。
- USB 已识别同星设备：`5453:0001`，厂商 `TOSUN`，产品字符串 `TOSUN HS CANFD2`，序列号 `37AFCA2612ADBF35`，节点 `/dev/bus/usb/001/002`。仅凭 USB 产品字符串不额外推断具体型号或 CAN 接线正确性。
- 系统已经安装 `libusb-1.0.so.0`。
- 检查时没有发现路径包含 X280、TSCAN、TC1013、TSMaster 或以 `.elf` 结尾的运行进程。此检查不代表任意名称的进程均未使用设备。

## 实机通信前仍需满足

1. 厂商 Linux SDK 缺失。本地 `C:/DataSave/06同星二次开发库` 的展开目录和 ZIP 只有 Windows DLL；没有 Linux `.so`。目标机 `/home/zh`、`/opt`、`/usr/local` 的有界目录扫描也没有发现 TSCAN、libTSH 或 blf 动态库，默认 `/home/zh/.local/lib/tscan` 目录不存在。`/opt/containerd` 无读取权限，其余扫描未触及数量或时间上限。
2. 当前用户缺少 USB 写权限。设备节点权限为 `crw-rw-r-- root:root`，`zh` 可读但不可写。正常用户运行 SDK 前需要限定到该设备的 udev 规则或等效权限配置。

本次没有安装驱动、修改目标机、停止进程、修改 CAN 参数或发送 CAN 报文。SDK 与权限未就绪，因此未执行硬件回环，不能把 USB 枚举成功当作 CAN 通信验证通过。
