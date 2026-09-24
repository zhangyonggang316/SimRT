# SSH 部署验证示例

这是 `../../validate_ssh.py` 使用的底层服务诊断夹具，不是 XCP Slave、Simulink 模型或额外 APP。
它保留历史原生编译服务的上传、编译、下载和进程管理检查；当前 Qt APP 的模型部署流程不使用此夹具。

只有显式执行诊断脚本并提供目标地址才会连接。诊断目标需启用 SSH，并安装 `make` 和 C 编译器。
脚本在用户家目录下创建独立目录，运行日志包含 PID、递增的 `tick` 和停止时的 `stopped cleanly`。
当前模型的本地交叉编译与成套产物部署流程见工程根目录 `docs/TOOLCHAIN.md`。
