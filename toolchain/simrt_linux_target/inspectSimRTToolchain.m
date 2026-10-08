function report = inspectSimRTToolchain(options)
%INSPECTSIMRTTOOLCHAIN Report missing build tools before starting codegen.
arguments
    options.Root (1,1) string = string(simrtToolchainRoot(Validate=false))
    options.ProbeCompiler (1,1) logical = true
    options.Strict (1,1) logical = false
end
root = char(options.Root);
bin = fullfile(root, 'toolchain', 'bin');
names = {'linux-gcc.exe', 'linux-g++.exe', 'linux-ar.exe', 'linux-as.exe', ...
    'linux-ld.exe', 'linux-nm.exe', 'linux-readelf.exe'};
files = repmat(struct('Name', '', 'Path', '', 'Present', false), 1, numel(names)+4);
for index = 1:numel(names)
    files(index) = entry(names{index}, fullfile(bin, names{index}));
end
files(end-3) = entry('MATLAB GNU Make', fullfile(matlabroot, 'bin', 'win64', 'gmake.exe'));
sysroot = fullfile(root, 'toolchain', 'x86_64-linux');
files(end-2) = entry('sysroot stdio.h', fullfile(sysroot, 'usr', 'include', 'stdio.h'));
files(end-1) = entry('sysroot crt1.o', fullfile(sysroot, 'usr', 'lib', 'crt1.o'));
files(end) = entry('sysroot libc.so', fullfile(sysroot, 'usr', 'lib', 'libc.so'));
report = struct('Root', string(root), 'Files', files, ...
    'Missing', string({files(~[files.Present]).Path}), ...
    'CompilerProbeRequested', options.ProbeCompiler, ...
    'CompilerTarget', "", 'CompilerMessage', "", 'CompilerValid', false);
if options.ProbeCompiler && files(1).Present
    command = sprintf('"%s" -dumpmachine', files(1).Path);
    [status, output] = system(command);
    report.CompilerTarget = string(strtrim(output));
    report.CompilerValid = status == 0 && ~isempty(regexp(char(report.CompilerTarget), ...
        '^x86_64-[A-Za-z0-9_.-]*linux[A-Za-z0-9_.-]*$', 'once'));
    if ~report.CompilerValid
        report.CompilerMessage = "Expected x86-64 Linux GCC; received: " + report.CompilerTarget;
    end
end
report.Passed = isempty(report.Missing) && (~options.ProbeCompiler || report.CompilerValid);
if options.Strict && ~report.Passed
    details = [report.Missing, report.CompilerMessage];
    error('simrtlinux:ToolchainPreflight', 'Local toolchain check failed:\n%s', ...
        strjoin(details(strlength(details)>0), newline));
end
end

function item = entry(name, file)
item = struct('Name', name, 'Path', file, 'Present', isfile(file));
end
