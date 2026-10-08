# 官方 Linux SDK 安装与初始化验证

2026-09-19 已在 `192.168.219.86` 完成安装和初始化验证，详细数据见 `install_vendor.json`，复现脚本为 `install_vendor.py`。

- 安装目录：`/home/zh/.local/lib/tscan`，包含 `libTSCANApiOnLinux.so`、`libTSH.so`、`LICENSE`、来源记录及 SHA256 清单。上传后逐文件核对 SHA256，未修改厂商二进制。
- 两项动态库的系统依赖均可解析。这个官方版本不需要单独的 `blf.so`。
- 修改权限前重新核对 USB VID `5453`、PID `0001`、序列号 `37AFCA2612ADBF35`，仅将对应 `/dev/bus/usb/001/002` 的组从 `root` 改为 `plugdev`，保留原 `0664` 模式和 root 所有者。SSH 用户 `zh` 已在 plugdev 组，实测可读写此节点。此调整针对当前设备节点，重新插拔/重启后需要重新验证或设置同等范围的持久 udev 规则。
- SDK 初始化后扫描到 1 台设备：`TOSUN HS CANFD2`，序列号匹配。扫描、连接、断开返回值均为 `0`，句柄非零，最后已调用 finalize。
- 没有调用任何 CAN/CAN FD 发送接口，也没有改变通道速率、终端电阻或启动模型。

## 已确认的 SDK 路径约束

首次从 SSH 默认目录运行时，即使提前绝对路径加载 `libTSH.so` 并设置 `LD_LIBRARY_PATH`，SDK 扫描仍返回 `0` 台设备。仅把 SDK 探针的工作目录改为驱动目录后，立刻能够扫描、连接硬件。

该厂商库包含 `libTSH.so`、`./libTSH.so` 和 `../lib/libTSH.so` 路径字符串，其内部初始化存在依赖工作目录的查找行为。模型运行时的驱动初始化必须处理这一约束；不能只以 `dlopen` 成功或 SDK 扫描返回码为 `0` 判定设备已就绪。
