function tc = simrtPortableToolchain
%SIMRTPORTABLETOOLCHAIN Windows-hosted GCC producing x86-64 Linux executables.
tc = coder.make.ToolchainInfo('BuildArtifact', 'gmake makefile', ...
    'Platform', 'win64', 'SupportedLanguages', 'C/C++');
tc.Name = 'SimRT portable-linux-toolchain';
tc.addAttribute('RequiresBatchFile', true);
tc.addAttribute('SupportsDoubleQuotes', true);
tc.addAttribute('TransformPathsWithSpaces', true);
tc.MATLABSetup = {'simrtToolchainEnvironment(''setup'');'};
tc.MATLABCleanup = {'simrtToolchainEnvironment(''restore'');'};
tc.addMacro('SIMRT_TOOLCHAIN', strrep(simrtToolchainRoot, '\', '/'));
tc.addMacro('SIMRT_SYSROOT', '$(SIMRT_TOOLCHAIN)/toolchain/x86_64-linux');
binFolder = '$(SIMRT_TOOLCHAIN)/toolchain/bin';
for names = {{'C Compiler', 'linux-gcc.exe', '.c'}, ...
        {'C++ Compiler', 'linux-g++.exe', '.cpp'}}
    entry = names{1};
    tool = tc.getBuildTool(entry{1});
    tool.setCommand(entry{2});
    tool.setPath(binFolder);
    tool.setDirective('CompileFlag', '-c');
    tool.setDirective('IncludeSearchPath', '-I');
    tool.setDirective('PreprocessorDefine', '-D');
    tool.setDirective('OutputFlag', '-o');
    tool.setDirective('Debug', '-g');
    tool.setFileExtension('Object', [entry{3} '.o']);
end
for name = {'Linker', 'C++ Linker'}
    tool = tc.getBuildTool(name{1});
    tool.setCommand('linux-g++.exe');
    tool.setPath(binFolder);
    tool.setDirective('OutputFlag', '-o');
    tool.setDirective('Library', '-l');
    tool.setDirective('LibrarySearchPath', '-L');
    tool.setFileExtension('Executable', '.elf');
    tool.setFileExtension('Shared Library', '.so');
end
tool = tc.getBuildTool('Archiver');
tool.setCommand('linux-ar.exe');
tool.setPath(binFolder);
tool.setFileExtension('Static Library', '.a');
tool.setDirective('OutputFlag', '');
tc.removePostbuildTool('Download');
tc.removePostbuildTool('Execute');
compile = '--sysroot="$(SIMRT_SYSROOT)" -c -g -gdwarf-4 -O2 -fno-pie -pthread';
link = ['--sysroot="$(SIMRT_SYSROOT)" -g -gdwarf-4 -O2 -fno-pie -no-pie ' ...
    '-pthread -Wl,--wrap=sem_wait -Wl,--wrap=sem_post'];
tc.setBuildConfigurationOption('all', 'C Compiler', [compile ' -std=c11']);
tc.setBuildConfigurationOption('all', 'C++ Compiler', compile);
tc.setBuildConfigurationOption('all', 'Linker', link);
tc.setBuildConfigurationOption('all', 'C++ Linker', link);
tc.setBuildConfigurationOption('all', 'Archiver', 'rcs');
tc.setBuildConfigurationOption('all', 'Make Tool', '-f $(MAKEFILE) -j2');
end
