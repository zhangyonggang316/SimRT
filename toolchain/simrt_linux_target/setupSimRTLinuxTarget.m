function targetRoot = setupSimRTLinuxTarget(options)
%SETUPSIMRTLINUXTARGET Register the SimRT target in MATLAB R2024b.

arguments
    options.Persist (1,1) logical = false
    options.Refresh (1,1) logical = false
end

assertR2024b;
assertDependency('Simulink', 'Simulink');
assertFunction('slbuild', 'Simulink Coder');
assertFunction('coder.asap2.export', 'Embedded Coder');

targetRoot = fileparts(mfilename('fullpath'));
previousPath = path;
% A saved path from an older checkout can register the same board twice.
entries = strsplit(path, pathsep);
for index = 1:numel(entries)
    candidate = entries{index};
    if ~strcmpi(candidate, targetRoot) && isfile(fullfile(candidate, ...
            'registry', 'targethardware', 'simrt_linux_ssh.xml'))
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
setupSimRTARKLibrary(Refresh=false);
definitionFiles = {'simrtPortableToolchain.m', 'rtwTargetInfo.m', ...
    fullfile('registry','targethardware','simrt_linux_ssh.xml'), ...
    fullfile('registry','attributes','simrt_linux_ssh_attributes.xml'), ...
    fullfile('registry','parameters','simrt_linux_ssh_parameters.xml'), ...
    fullfile('drivers','ark','slblocks.m'), fullfile('drivers','ark','sl_customization.m')};
registration = struct('Root', targetRoot, 'ToolchainRoot', simrtToolchainRoot, ...
    'Release', version('-release'), 'Definitions', {cellfun(@(name) ...
    char(simrtFileSHA256(fullfile(targetRoot,name))), definitionFiles, 'UniformOutput', false)});
registration.Definitions = registration.Definitions(:);
registryFile = fullfile(targetRoot, 'registry', 'simrt_portable_toolchain.mat');
signatureFile = fullfile(targetRoot, 'registry', 'simrt_portable_toolchain_signature.json');
changed = true;
if isfile(registryFile) && isfile(signatureFile)
    try
        variables = whos('-file', registryFile);
        if numel(variables) == 1 && strcmp(variables.name, 'tc')
            previous = jsondecode(fileread(signatureFile));
            changed = ~isequal(previous, registration);
        end
    catch
        % Derived cache files can be incomplete after an interrupted setup.
        changed = true;
    end
end
if changed
    tc = simrtPortableToolchain;
    save(registryFile, 'tc');
    stream = fopen(signatureFile, 'w', 'n', 'UTF-8');
    assert(stream >= 0, 'simrtlinux:RegistrationWrite', 'Cannot write registration signature.');
    cleanup = onCleanup(@() fclose(stream));
    fprintf(stream, '%s', jsonencode(registration));
    clear cleanup;
end
if options.Refresh || changed || ~strcmp(previousPath, path) || ...
        ~codertarget.target.isTargetRegistered('simrtlinux')
    rehash toolboxcache;
    sl_refresh_customizations;
end

if ~codertarget.target.isTargetRegistered('simrtlinux')
    error('simrtlinux:RegistrationFailed', ...
        'MATLAB did not register the simrtlinux target from %s.', targetRoot);
end
boards = codertarget.target.getAllHardwareBoards('simrtlinux');
if ~any(strcmp({boards.Name}, 'SimRT'))
    error('simrtlinux:BoardRegistrationFailed', ...
        'The SimRT hardware board was not registered.');
end

if options.Persist && savepath ~= 0
    error('simrtlinux:SavePathFailed', ...
        'The target is active for this MATLAB session, but savepath failed.');
end
end

function assertR2024b
releaseName = version('-release');
if ~strcmp(releaseName, '2024b')
    error('simrtlinux:UnsupportedRelease', ...
        'This target is validated only with MATLAB R2024b; found %s.', releaseName);
end
end

function assertDependency(productName, displayName)
if isempty(ver(productName))
    error('simrtlinux:MissingProduct', '%s is required.', displayName);
end
end

function assertFunction(functionName, displayName)
if isempty(which(functionName))
    error('simrtlinux:MissingProduct', '%s is required.', displayName);
end
end
