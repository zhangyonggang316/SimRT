# GitHub 源码与发布附件

仓库：[zhangyonggang316/SimRT](https://github.com/zhangyonggang316/SimRT)。本轮版本标签为 `v2026.10.08`。

## 获取完整工程

```powershell
git clone https://github.com/zhangyonggang316/SimRT.git
Set-Location SimRT
git checkout v2026.10.08
```

Git 保存源码、Simulink 库与模型、配套历史部署 ZIP、文档及验证记录。APP、编译器及可选开发工具从[同版本 Release](https://github.com/zhangyonggang316/SimRT/releases/tag/v2026.10.08)下载。

| 附件 | 解压到工程根目录后恢复 | 何时需要 |
| --- | --- | --- |
| `SimRT-app-win64-2026.10.08.zip` | `app/distribution/` | 直接运行正式 APP |
| `SimRT-linux-toolchain-2026.10.08.zip` | `toolchain/portable-linux-toolchain/` | MATLAB 本地交叉编译模型 |
| `SimRT-qt-toolchain-2026.10.08.zip` | `toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/` | 重建 APP 的 C++ DLL |
| `SimRT-development-optional-2026.10.08.zip` | `toolchain/development/` | 使用可选 MATLAB 自动化工具 |
| `assets.json`、`SHA256SUMS.txt` | 附件文件数、大小、SHA-256 | 下载完整性核对 |

每个 ZIP 都包含从工程根目录开始的相对路径，统一解压到克隆后的 `SimRT` 根目录，不要再嵌套一层 `app` 或 `toolchain`。例如：

```powershell
Get-FileHash ./SimRT-app-win64-2026.10.08.zip -Algorithm SHA256
Expand-Archive ./SimRT-app-win64-2026.10.08.zip -DestinationPath .
./app/START_APP.cmd
```

下载文件的 SHA-256 应与 `SHA256SUMS.txt` 一致。归档中 `.simrt-release-manifests/` 保存逐文件校验信息；许可证随对应组件保留。

## 本机环境

`startup_network_time_20261005` 及其 `demo_release` 副本中的 `before.json`、`probe_followup.json` 含历史 Wi-Fi 凭据，按精确路径排除；它们仍保留在原开发机，不在公开仓库中提供。

`.python`、`.venv`、凭据、缓存和本机 IDE 配置不上传。在新机器重建 Python 环境，按 [新机部署](NEW_MACHINE_DEPLOYMENT.md) 安装并激活 MATLAB R2024b。恢复 Linux 工具链后执行：

```matlab
addpath('D:/SimRT/toolchain/simrt_linux_target'); % 替换为实际克隆路径
setupSimRTLinuxTarget(Persist=true);
verifySimRTEnvironment(Strict=true);
```

生成目录可能包含复制的 MATLAB 运行库源码，沿用仓库原有策略不纳入 Git；原开发机文件继续保留供学习。应在新机器从 SLX 重新生成。历史报告中的旧绝对路径按 [目录映射](../tests/layout/README.md) 查阅，不能直接作为新机器的构建路径。

## 维护发布

`tests/maintenance/prepare_github_release.py --version 2026.10.08` 将附件生成到被忽略的 `.release/2026.10.08`，拒绝覆盖已有目录，并逐文件核对 ZIP 内容。该脚本只准备文件，不执行 GitHub 上传。第三方开发工具的嵌套 `.git` 和缓存不打包。
