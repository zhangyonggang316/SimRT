function targetRoot = setupX280LinuxTarget(options)
%SETUPX280LINUXTARGET Register the SimRT target in MATLAB R2024b.

arguments
    options.Persist (1,1) logical = false
end

assertR2024b;
assertDependency('Simulink', 'Simulink');
assertFunction('slbuild', 'Simulink Coder');
assertFunction('coder.asap2.export', 'Embedded Coder');

targetRoot = fileparts(mfilename('fullpath'));
% A saved path from an older checkout can register the same board twice.
entries = strsplit(path, pathsep);
for index = 1:numel(entries)
    candidate = entries{index};
    if ~strcmpi(candidate, targetRoot) && isfile(fullfile(candidate, ...
            'registry', 'targethardware', 'x280_linux_ssh.xml'))
        rmpath(candidate);
    end
end
if ~contains([path pathsep], [targetRoot pathsep])
    addpath(targetRoot);
end
driverRoot = fullfile(targetRoot, 'drivers', 'tc1013');
if isfolder(driverRoot)
    addpath(driverRoot);
end
rehash toolboxcache;
tc = x280PortableToolchain;
save(fullfile(targetRoot, 'registry', 'x280_portable_toolchain.mat'), 'tc');
sl_refresh_customizations;

if ~codertarget.target.isTargetRegistered('x280linux')
    error('x280linux:RegistrationFailed', ...
        'MATLAB did not register the x280linux target from %s.', targetRoot);
end
boards = codertarget.target.getAllHardwareBoards('x280linux');
if ~any(strcmp({boards.Name}, 'SimRT'))
    error('x280linux:BoardRegistrationFailed', ...
        'The SimRT hardware board was not registered.');
end

if options.Persist && savepath ~= 0
    error('x280linux:SavePathFailed', ...
        'The target is active for this MATLAB session, but savepath failed.');
end
end

function assertR2024b
releaseName = version('-release');
if ~strcmp(releaseName, '2024b')
    error('x280linux:UnsupportedRelease', ...
        'This target is validated only with MATLAB R2024b; found %s.', releaseName);
end
end

function assertDependency(productName, displayName)
if isempty(ver(productName))
    error('x280linux:MissingProduct', '%s is required.', displayName);
end
end

function assertFunction(functionName, displayName)
if isempty(which(functionName))
    error('x280linux:MissingProduct', '%s is required.', displayName);
end
end
