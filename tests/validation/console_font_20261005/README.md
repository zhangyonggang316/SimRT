# 实时机屏幕字体调整

日期：2026-10-05。目标机：`192.168.193.195`。

字体由 Fixed 8x16 调整为 Terminus 12x24，字宽、字高均增加 50%。1920x1080 屏幕的文本区域从 240 列、67 行变为 160 列、45 行。

已在线应用到 `/dev/tty1`，并保存 `/etc/default/console-setup` 中的 `FONTFACE="Terminus"`、`FONTSIZE="12x24"`。已刷新系统开机字体缓存，`console-setup.service` 为 enabled；未重启目标机。

验证结果见 [font_result.json](font_result.json)：字体加载成功，终端和 tmux 尺寸一致；显示进程 PID 1591 保持不变，状态页继续刷新，网络、模型状态和日志区均存在。抓取内容见 [console_after.txt](console_after.txt)。这是实际 tty1 设置和终端内容验证，没有拍摄物理显示器照片。

目标机备份目录：`/var/backups/simrt-console-font-20261005-063422`，包含原控制台配置、开机字体脚本及实际旧字体 `previous.psf`。

调整脚本：[apply_font.py](apply_font.py)。本次没有修改模型或 Windows 上位机程序。
