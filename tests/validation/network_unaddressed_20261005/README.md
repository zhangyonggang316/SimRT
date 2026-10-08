# 无 IPv4 网口配置修复

日期：2026-10-05。

## 根因与修改

用户对 `enp1s0` 设置 `192.168.7.1/24` 时收到 `Network interface no longer exists`。实机只读查询确认：网口存在，处于无载波状态，没有 IPv4；`ip -j address show dev enp1s0` 返回完整网口，而 `ip -j -4 address show dev enp1s0` 返回空数组。旧代码把地址族过滤后的空结果当成网口消失。

配置前的存在性、MAC 和原始网口状态改用完整查询；用于 IPv4 修改和回滚的快照仍严格只收集 `family=inet`、`scope=global` 地址，避免 IPv6 进入 IPv4 删除或恢复命令。没有改动模型与 UDP 5555/TCP 17725 端口。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 新回归用例运行于修复前代码 | 三个场景均复现原错误 | [失败复现](regression_before.log) |
| 网络配置与持久化单元测试 | 31 项通过 | [网络测试](network_tests.log) |
| Qt 与共享服务回归 | 148 + 189 项全部通过，无跳过 | [回归报告](host_tests/test_report.json) |
| 实机隔离网口首次设置 IPv4 | 管理状态 DOWN、无载波、仅 IPv6 三个场景均通过 | [目标测试](target_result.json) |
| Netplan 持久保存 | MAC 匹配成功，新的生成进程读回 `192.168.7.1/24` | [目标测试](target_result.json) |
| 自动回滚 | 45 秒后恢复无 IPv4、原 DOWN 状态和原配置文件 | [目标测试](target_result.json) |
| Windows 程序 | 构建、启动与正常退出检查 | [构建报告](app_build_report.json)、[启动记录](app_smoke.json) |

实机测试在 `192.168.193.195` 的独立网络命名空间和隔离 Netplan 根目录内进行，使用真实 `ip`、Netplan 和回滚进程。物理网口仅做只读查询，没有代用户更改当前 IP，也没有重启目标机。

## 交付

- 启动入口：`demos/Demo_XCP_Qt/START_DEMO.cmd`。
- 新 EXE SHA256：`d6a5bd147eb70857cd43c630fa5696b335bb4c3cf14c14d294a69c6497aac516`。
- 旧程序备份：工作区 `tests/validation/network_unaddressed_20261005_previous_app/app`。
- 本次未重新编译模型，继续使用已验证的 `20261005_052620_728.zip`。
- 复现脚本：[verify_target.py](verify_target.py)。SSH 与 sudo 密码交互输入，脚本不写入密码。

在新版中连接 SSH，重新打开“网络接口 / IPv4”，选择 `enp1s0` 后即可重新应用原设置。配置静态地址不要求网口已有 IPv4；实际以太网通信仍需要网线和对端链路正常。
