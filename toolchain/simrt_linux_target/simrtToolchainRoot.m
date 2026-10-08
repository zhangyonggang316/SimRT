function root = simrtToolchainRoot(options)
%SIMRTTOOLCHAINROOT Locate the relocatable local Linux cross compiler package.
arguments
    options.Validate (1,1) logical = true
end
root = getenv('SIMRT_TOOLCHAIN_ROOT');
if isempty(root)
    root = fullfile(simrtProjectRoot, 'toolchain', 'portable-linux-toolchain');
end
root = char(java.io.File(root).getCanonicalPath());
assert(~options.Validate || isfile(fullfile(root, 'toolchain', 'bin', 'linux-gcc.exe')), ...
    'simrtlinux:ToolchainMissing', ...
    'Set SIMRT_TOOLCHAIN_ROOT to the portable-linux-toolchain package: %s', root);
end
