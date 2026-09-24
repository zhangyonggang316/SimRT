function x280ToolchainEnvironment(action)
%X280TOOLCHAINENVIRONMENT Isolate GCC search paths for the build lifetime.
persistent saved
names = {'PATH', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', ...
    'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH'};
switch action
    case 'setup'
        if ~isempty(saved), return; end
        root = x280ToolchainRoot;
        saved = cellfun(@getenv, names, 'UniformOutput', false);
        for index = 2:numel(names), setenv(names{index}, ''); end
        setenv('PATH', strjoin({fullfile(root, 'toolchain', 'bin'), ...
            fullfile(root, 'host-bin'), fullfile(getenv('SystemRoot'), 'System32'), ...
            getenv('SystemRoot'), saved{1}}, pathsep));
    case 'restore'
        if isempty(saved), return; end
        for index = 1:numel(names), setenv(names{index}, saved{index}); end
        saved = [];
    otherwise
        error('x280linux:EnvironmentAction', 'Unknown environment action.');
end
end
