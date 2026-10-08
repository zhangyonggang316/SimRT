# SimRT 1 ms 模型构建

交付模型为 `models/simrt_rt_single/simrt_rt_single.slx`。在完整工程的 Windows MATLAB R2024b 中运行 `setupSimRTLinuxTarget`，打开模型后按 Ctrl+B；也可以使用 `buildSimRTLocal`。

成功后 `simrt_rt_single_local` 内生成仅含配套 ELF/A2L/manifest 的 ZIP。APP 选择该 ZIP，完成哈希校验后通过 SSH 上传和启停。详见 [工具链](TOOLCHAIN.md)。

模型基本周期为 1 ms，UDP 5555，TCP 默认 17725。编译、文件配套、XCP 收发和硬件周期稳定性分别验收。重命名后的构建检查见 `validation/simrt_migration_20261007/`。
