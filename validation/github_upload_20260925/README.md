# GitHub 源码发布检查

日期：2026-09-25。目标仓库：<https://github.com/zhangyonggang316/SimRT>，分支 `main`。

本次将本机工程整理为源码仓库，保留原仓库提交记录。上传内容约 40 MB，包括 MATLAB/Simulink 目标适配、主模型及 CAN 示例、Qt/Python/C++ 源码、11 个历史模型 ZIP、文档、测试和验证记录。依赖准备与排除项见[源码获取说明](../../docs/SOURCE_CHECKOUT.md)。本机原有工具链、APP、虚拟环境和构建产物没有被删除。

## 验证

从 Git 暂存内容导出独立副本，使用已有 Python 3.9.10 环境运行离线测试；副本不包含本机编译器、已打包 APP 或生成代码目录。

| 测试目录 | 通过数量 |
| --- | ---: |
| `qt_xcp_host/tests` | 130 |
| `qt_xcp_host/service_tests` | 172 |
| `tools/tests` | 94 |
| `x280_linux_target/tests` | 38 |
| `validation/tc1013_can_20260919/test_credentials.py` | 7 |
| 合计 | 441 |

全部通过，无跳过。另检查了 9 份当前入口文档的 83 个本地链接，目标均在上传文件集合中；11 个模型 ZIP 均只有 ELF、A2L、JSON 三个文件，ELF/A2L 哈希与 manifest 一致；没有超过 100 MiB 的上传文件。

本次未启动 MATLAB、未重新编译模型、未连接或部署 Linux 目标机。历史真机报告的结论范围保持不变。

## 凭据处理

需求文档中的明文 SSH 密码已移除。CAN 硬件验证脚本改从 `SIMRT_SSH_PASSWORD` 读取，缺失时拒绝连接；主机和用户名可以通过环境变量覆盖。7 项离线测试覆盖默认值、覆盖值、空凭据拒绝及禁止从文档读取密码。

提交内容经过 GitHub 令牌、私钥标记和硬编码密码检查。此前已经公开的凭据应更换；删除当前文件中的明文不能清除 Git 历史或已有副本。
