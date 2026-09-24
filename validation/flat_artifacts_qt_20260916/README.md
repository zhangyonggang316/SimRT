# 三文件结果与 Qt 源码合并

日期：2026-09-16。

## 最终布局

`qt_xcp_host/` 是唯一 APP 源码目录：`qt_host/` 为 Qt 界面，`pyxcp_host/` 为业务、XCP、DAQ 和 SSH 服务，`service_tests/` 为服务测试。根目录 `python_xcp_host/` 已移除，包名及业务接口保持不变。

每次 Ctrl+B 编译成功后，`x280_rt_single_local/<时间戳>/` 直接包含：

```text
x280_rt_single.elf
x280_rt_single.a2l
x280_rt_single.xcp-manifest.json
```

源码、SLX 快照、Makefile 和构建诊断在 `_ert_rtw/x280_build_evidence/<时间戳>/`，构建回执仍在 `_ert_rtw/x280_local_build.json`。结果先在中间目录完成检查，再发布至最终目录。

已有的三轮编译结果均已迁移到上述结构，ELF/A2L/manifest 内容与哈希保持不变。APP 默认预设修复为最近一轮 `20260915_170738_507`；后续新编译可直接在 APP 选择新的时间戳目录。

打包入口按 `demo.json` 选择结果，只复制一个 SLX 和该轮三个文件，不带入其它编译轮次或中间缓存。当前工程中的中间构建资料仍保留用于复现。

## 验证

- `matlab_tests.json`：11 项 MATLAB 测试通过，包含真实本地生成、交叉编译和 A2L 导出；验证默认及指定输出目录均只有三个文件，哈希一致。
- `../qt_merged_final_20260916/`：Qt 90 项、服务 135 项通过；另有 XCP 后端 27 项和相关工具 42 项通过。
- `artifact_checks.json`：三轮已有结果均为三个文件，APP 产物校验通过。
- `layout_migration.json`：结果文件与中间构建资料的新路径。
- `packaged_startup.json`：合并后 EXE 实际启动，Qt Widgets 与 C++ 核心加载成功，无启动错误日志。

本轮没有连接 SSH、修改目标机进程或自启配置。模型构建在临时副本上验证，测试用 MATLAB 会话已结束，原用户 MATLAB 会话未关闭。
当前预设 ELF 的 SHA-256 为 `05b65e22ccb50a10b12a9ceabeebcff52e0217004a8f30028de7c494367b8f5a`；本轮不把旧 ELF 的真机结果标为这一轮的新验收。
