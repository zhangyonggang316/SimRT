function root = x280ToolchainRoot
%X280TOOLCHAINROOT Locate the relocatable local Linux cross compiler package.
root = getenv('X280_TOOLCHAIN_ROOT');
if isempty(root)
    projectRoot = fileparts(fileparts(mfilename('fullpath')));
    root = fullfile(projectRoot, 'portable-linux-toolchain', 'portable-linux-toolchain');
end
root = char(java.io.File(root).getCanonicalPath());
assert(isfile(fullfile(root, 'toolchain', 'bin', 'linux-gcc.exe')), ...
    'x280linux:ToolchainMissing', ...
    'Set X280_TOOLCHAIN_ROOT to the portable-linux-toolchain package: %s', root);
end
