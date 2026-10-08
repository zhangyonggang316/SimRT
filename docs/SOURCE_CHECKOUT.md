# 从 GitHub 获取源码

克隆仓库并恢复所需组件的方法见 [GitHub 源码与发布附件](GITHUB_DELIVERY.md)。

当前布局为 `app`、`shared`、`toolchain`、`linux`、`demos`、`tests` 和 `docs`。界面、工具链和模型均已统一为 SimRT；MATLAB 入口为 `setupSimRTLinuxTarget`，工具链环境变量为 `SIMRT_TOOLCHAIN_ROOT`。

源码运行 APP：

```powershell
& 'C:/Path/To/Python3910/python.exe' -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r ./requirements.txt
& ./app/qt_xcp_host/run.ps1
```

也可从 Release 恢复正式 APP 后运行 `app/START_APP.cmd`。模型开发与系统准备见 [新机部署指南](NEW_MACHINE_DEPLOYMENT.md)，模块依赖见 [目录说明](PROJECT_LAYOUT.md)。
