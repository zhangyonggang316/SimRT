# 从 GitHub 获取源码

仓库地址：<https://github.com/zhangyonggang316/SimRT>。

```powershell
git clone https://github.com/zhangyonggang316/SimRT.git
Set-Location SimRT
```

## 仓库内容与本机交付包

仓库包含 MATLAB 目标适配、Simulink 模型和 CAN 模块库、Python/Qt/C++ APP 源码、测试、构建脚本、技术文档、示例模型 ZIP，以及验证说明和必要夹具。示例 ZIP 是历史构建产物，不能代替修改模型后的重新构建和验收。

以下内容保留在原开发机，通过 `.gitignore` 排除，克隆后需另行准备：

| 内容 | 准备方式 |
| --- | --- |
| `.python/`、`.venv/` | 安装 Python 3.9.10 x64，在克隆目录重新创建虚拟环境并安装固定依赖 |
| `Demo_XCP_Qt/app/` | 从源码构建，或取得包含 EXE 和全部 `_internal` 文件的完整 APP 交付包 |
| `tools/qt_toolchain/` | 按部署指南下载 LLVM-MinGW 20250709 官方包并核验 SHA-256 |
| Linux 交叉编译器及 sysroot | 准备有权使用的完整 GCC 7.5.0 / x86_64-linux 工具链；仓库保留调用脚本、CMake 配置、示例及来源清单 |
| MATLAB 与工具箱 | 自行安装并激活 R2024b 及对应产品；仓库不包含 MATLAB 软件或复制的运行时源码 |
| `_ert_rtw/`、构建源码包、注册缓存 | 在当前机器重新注册、生成代码和构建；旧 ELF 不能与其他轮次的元数据混用 |
| `.vscode/`、MCP 服务、辅助技能工具 | 可选本机开发工具，不是 APP 或模型运行依赖 |

原开发机的文件不会因 Git 忽略规则而被删除。已有部署和历史验证文档中的“完整工程”“已准备工具链”“正式 APP”指完整本机工作区；仅克隆 Git 仓库时，以本页的依赖准备步骤为准。历史报告可能引用未提交的构建目录、日志绝对路径或本机产物，其验证结论不自动适用于新机器。

## 启动 Qt APP

先按[新机部署指南](NEW_MACHINE_DEPLOYMENT.md#6-新-windows-机器app-使用与源码环境)准备 Python 环境与固定依赖。若使用其他安装位置的 Python，可在工程根目录运行：

```powershell
& 'C:/Path/To/Python3910/python.exe' -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r ./qt_xcp_host/requirements.txt
& ./.venv/Scripts/python.exe -m pip check
& ./qt_xcp_host/run.ps1
```

仓库保留当前 Windows x64 `xcp_core.dll` 及其 C++ 源码；修改 C++ 时先准备 LLVM-MinGW，再运行 `qt_xcp_host/build_native.ps1`。重新生成 EXE 使用 `qt_xcp_host/build.ps1`，打包方法见 [Qt APP 说明](../qt_xcp_host/README.md#构建与打包)。`Demo_XCP_Qt/START_DEMO.cmd` 仅适用于已经补齐 `app/` 的完整交付目录。

## 构建 Simulink 模型

按[新机部署指南](NEW_MACHINE_DEPLOYMENT.md#4-新-windows-机器matlab-和本地工具链)安装 MATLAB 和完整 Linux 交叉工具链，然后运行 `setupX280LinuxTarget`。硬件名称为 `SimRT`，工具链名称仍为 `X280 portable-linux-toolchain`。工具链不在默认位置时，通过 `X280_TOOLCHAIN_ROOT` 指定包含 `toolchain/bin/linux-gcc.exe` 的包根目录。

执行 Ctrl+B 后，本地生成代码并交叉编译，新的时间戳 ZIP 内只包含 ELF、A2L 和 JSON。Qt APP 加载该 ZIP，通过 SSH 部署；Linux 目标机不编译模型。首次部署前按指南核对地址、实时权限、依赖及可选 CAN 驱动。

## 凭据

仓库不保存真实 SSH 密码、令牌、私钥或用户凭据缓存。APP 连接时输入本机凭据；CAN 验证脚本使用 `SIMRT_SSH_PASSWORD` 环境变量提供密码。不要把真实凭据写回需求文档或提交到 Git。
