# SimRT 名称与图标更新

- 窗口标题、应用名称、页眉、启动错误提示统一为 SimRT。
- Windows 程序为 `app/distribution/SimRT.exe`，继续通过 `demos/Demo_XCP_Qt/START_DEMO.cmd` 加载原有模型预设。
- 原创波形图标源文件为 `app/qt_xcp_host/qt_host/assets/simrt.svg`，由 `generate_icon.py` 生成 PNG 和 ICO。ICO 包含 16、20、24、32、48、64、128、256 像素版本。
- 窗口图标、页眉图标、Windows 任务栏身份及 EXE 图标资源已配置，EXE 产品名称、说明和原始文件名分别为 SimRT、SimRT、SimRT.exe。

## 验证

- `test_report.json`：Qt 136 项、共享服务 190 项全部通过。
- `build.log`：PyInstaller 完成 SimRT 打包；保留已有可选 pyxcp recorder converter 导入警告。
- 使用 PE 资源解析确认 EXE 包含 8 个图标图像，打包内 ICO 与源码 ICO 字节一致；Windows VersionInfo 名称检查通过。
- 实际启动打包 EXE，使用 computer-use 查看真实窗口：标题和页眉均为 SimRT，标题栏及页眉图标正常，无启动报错。
- `app_promotion/promotion.json`：已更新正式 APP 的 7 个文件；旧版 QtXCPHost.exe 及被替换文件存入 `app_promotion/previous_files`。

本轮不连接实时机、不修改模型、已保存凭据或通信配置。
