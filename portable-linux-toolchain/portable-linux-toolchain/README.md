# Windows 到 Linux x86-64 独立交叉编译工具链

此目录可整体复制到其他 Windows 项目使用。它从本机 PolarDriver R2023b 安装中提取通用 GCC、binutils 和 Linux sysroot；不包含 MATLAB、Simulink、Xenomai 包、`xeno-*` 包装器或 YISU 运行库。编译器运行在 Windows，输出运行于 Linux x86-64 的 ELF 文件。原安装的可选 `linux-gdb.exe` 需要额外 MinGW DLL，因此本编译专用包不附带 GDB。

## 包内容与环境

- `toolchain/bin/linux-gcc.exe`、`linux-g++.exe`：GCC 7.5.0，目标 `x86_64-linux`。
- `toolchain/lib/`、`toolchain/lib64/`：编译器内部程序和 GCC 支持库。
- `toolchain/x86_64-linux/`：保持原布局的 Linux 头文件、C++ 标准库、glibc 2.27 sysroot。
- `scripts/invoke-tool.ps1`：可重定位调用入口。
- `cmake/linux-x86_64.cmake`：可选的 CMake 工具链配置。
- `examples/`：C/C++ 编译测试源码；不包含构建产物。
- `manifest.json`：来源、版本、逐文件 SHA-256、排除文件和 Windows PE DLL 导入表。

需要 Windows x64 和 PowerShell 5.1 或更新版本。推荐使用 ASCII 路径，含空格路径已验证。无需安装 PolarDriver、MATLAB 或 MSYS 来编译普通 C/C++。CMake 和 Ninja 属于可选构建工具，需项目自行提供。`host-bin/` 只在发现非 Windows 系统 DLL 依赖时生成；具体依赖以清单为准。

## PowerShell 调用

以下命令在解压后的包根目录执行。`-Tool` 为不带 `linux-` 前缀及 `.exe` 后缀的工具名；所有原生参数必须通过 `-ToolArguments` 字符串数组传递，每个参数占一个数组元素。此写法避免 PowerShell 将 `-O2`、`-o` 等误解析为脚本参数。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\scripts\invoke-tool.ps1 -Tool gcc -ToolArguments @('--version')
New-Item -ItemType Directory -Force build | Out-Null
& .\scripts\invoke-tool.ps1 -Tool gcc -ToolArguments @('-O2', '-Wall', '-Wextra', '.\examples\smoke.c', '-lm', '-o', '.\build\smoke_c.elf')
& .\scripts\invoke-tool.ps1 -Tool 'g++' -ToolArguments @('-std=c++11', '-O2', '-Wall', '-Wextra', '.\examples\smoke.cpp', '-o', '.\build\smoke_cpp.elf')
& .\scripts\invoke-tool.ps1 -Tool readelf -ToolArguments @('-h', '.\build\smoke_c.elf')
& .\scripts\invoke-tool.ps1 -Tool readelf -ToolArguments @('-d', '.\build\smoke_cpp.elf')
```

从其他项目调用时，将入口改成包的绝对路径即可；源码及输出文件相对路径仍以当前工作目录为基准。脚本使用自身位置寻找编译器及 sysroot，临时清理影响 GCC 搜索路径的环境变量，并在结束时恢复环境。失败时抛出错误，成功时原样输出工具结果。

调用工具支持 `gcc`、`g++`、`cpp`、`ar`、`as`、`ld`、`nm`、`objcopy`、`objdump`、`ranlib`、`readelf`、`size`、`strings`、`strip`、`addr2line`、`c++filt`、`elfedit`、`gcc-ar`、`gcc-nm`、`gcc-ranlib`、`gcov`、`gcov-dump`、`gcov-tool`。优先通过 GCC/G++ 驱动程序链接，它们会自动选取启动对象与标准库。

## CMake 项目

在 Windows PowerShell 中运行，选择 Ninja 而非 Visual Studio 生成器：

```powershell
cmake -S .\examples -B .\build-cmake -G Ninja "-DCMAKE_TOOLCHAIN_FILE=$PWD/cmake/linux-x86_64.cmake" -DCMAKE_BUILD_TYPE=Release
cmake --build .\build-cmake
```

其他项目只需换掉 `-S` 路径。首次配置必须使用空构建目录；迁移包后应重新配置构建目录，因为 CMake 缓存会记录绝对路径。CMake 文件设置 `CMAKE_SYSROOT`、交叉编译器及搜索根目录；运行时仍应避免在父环境中设置指向其他 GCC 的搜索变量。

## 在 WSL / Linux 中运行

仅将生成的 ELF 和项目所需运行时文件部署到 Linux。不要把 Windows 编译器复制到 WSL 内当作 Linux 编译器运行。将下面路径替换为实际构建目录对应的 `/mnt/<盘符>/...` 路径：

```powershell
wsl -d Debian -- /mnt/d/project/build/smoke_c.elf
wsl -d Debian -- /mnt/d/project/build/smoke_cpp.elf
```

预期分别输出 `portable C: sqrt(2)=1.414213562` 和 `portable C++: sum=10`，退出码为 0。

动态 ELF 使用 Linux 的 `/lib64/ld-linux-x86-64.so.2`，运行目标需提供兼容的 glibc；C++ 程序还需兼容的 `libstdc++.so.6` 和 `libgcc_s.so.1`。普通 C 示例只依赖系统数学库及 C 库，不需要 Xenomai。可使用 `readelf -d`、`readelf -V` 和 Linux `ldd` 检查具体产物。包内的 glibc 2.27 是编译基线，不能仅凭版本号保证所有第三方库都兼容。

不具备 glibc 环境的 musl/Alpine、ARM64 目标及 Windows 本机均不是该工具链输出的直接运行平台。本包解决通用 Linux 用户态程序交叉编译，不提供实时调度或 HIL I/O 驱动。

## 完整性与重新提取

`manifest.json` 的 `files` 列出除清单自身之外的全部交付文件及 SHA-256，可逐项使用 `Get-FileHash -Algorithm SHA256` 校验。二进制和 sysroot 文件直接复制，没有修改厂商安装。

项目源码目录提供 `Extract-PortableToolchain.ps1`，通过 `-SourceRoot` 指定原始 `env/x86_64-linux`，通过 `-OutputDirectory` 指定一个尚不存在的新目录，即可重新提取。该脚本只读取原安装、拒绝覆盖现有目标，并枚举所有 Windows PE 文件的 DLL 导入，只有必需非系统依赖才从相邻 `env/usr/bin` 补齐。

编译器和 sysroot 保留各上游组件的版权及许可证信息。此提取用于本机已有安装的项目复用；对外分发工具链时，应另行核对上游和原安装的许可材料。本包不包含工具链对应源代码。
