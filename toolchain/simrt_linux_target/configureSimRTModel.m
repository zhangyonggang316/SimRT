function config = configureSimRTModel(model, options)
%CONFIGURESIMRTMODEL Configure Ctrl+B for local Linux code generation and build.

arguments
    model (1,1) string
    options.Address (1,1) string = ""
    options.Username (1,1) string = ""
    options.BuildDirectory (1,1) string = ""
    options.BuildAction (1,1) string {mustBeMember(options.BuildAction, "Build")} = "Build"
    options.EnableParallelBuild (1,1) logical = true
    options.Save (1,1) logical = true
end

setupSimRTLinuxTarget;
[modelName, loadedHere] = openModel(model);
cleanup = onCleanup(@() closeIfLoadedHere(modelName, loadedHere));

% Older SLX snapshots can retain a legacy board label beside current target data.
if ~strcmp(get_param(modelName, 'HardwareBoard'), 'SimRT')
    set_param(modelName, 'HardwareBoard', 'SimRT');
end
if ~strcmp(codertarget.target.getHardwareName(modelName), 'SimRT')
    codertarget.target.setTargetHardware(modelName, 'SimRT');
end

xcpConfig = simrtXCPConfiguration;
data = get_param(modelName, 'CoderTargetData');
data.BoardParameters = preserveOrSet(data.BoardParameters, 'DeviceAddress', options.Address, "192.168.219.86");
data.BoardParameters = preserveOrSet(data.BoardParameters, 'Username', options.Username, "");
data.BoardParameters = preserveOrSet(data.BoardParameters, 'BuildDir', options.BuildDirectory, "/tmp/matlab_simrt");
data.Runtime.BuildAction = char(options.BuildAction);
data.BuildTime.EnableParallelBuild = options.EnableParallelBuild;
% R2024b stores the shared Ethernet endpoint under its TCP registry label.
data.ConnectionInfo.XCPonTCPIP.Port = num2str(xcpConfig.Port);
set_param(modelName, 'CoderTargetData', data);

set_param(modelName, ...
    'SolverType', 'Fixed-step', ...
    'Solver', 'FixedStepDiscrete', ...
    'SystemTargetFile', 'ert.tlc', ...
    'TargetLang', 'C', ...
    'Toolchain', 'SimRT portable-linux-toolchain', ...
    'GenCodeOnly', 'off', ...
    'EnableMultiTasking', 'off', ...
    'ConcurrentTasks', 'off', ...
    'GenerateASAP2', 'off', ...
    'DefaultParameterBehavior', 'Tunable', ...
    'ExtMode', 'on');
coder.coverage.BuildHook.addHook(modelName, ...
    'codertarget.simrtlinuxssh.internal.LocalBuildHook', ...
    'IncludeReferencedModels', 'off');

if options.Save
    save_system(modelName);
end

config = struct( ...
    'Model', string(modelName), ...
    'HardwareBoard', "SimRT", ...
    'Address', string(data.BoardParameters.DeviceAddress), ...
    'Username', string(data.BoardParameters.Username), ...
    'BuildDirectory', string(data.BoardParameters.BuildDir), ...
    'BuildAction', options.BuildAction, ...
    'XCPTransport', xcpConfig.Transport, ...
    'XCPPort', xcpConfig.Port, ...
    'CredentialsStoredInModel', false);
clear cleanup;
end

function [modelName, loadedHere] = openModel(model)
modelPath = char(model);
[~, fileName, extension] = fileparts(modelPath);
if isempty(extension)
    modelName = modelPath;
else
    modelName = fileName;
end
loadedHere = ~bdIsLoaded(modelName);
if ~loadedHere && isfile(modelPath)
    assert(strcmpi(char(java.io.File(modelPath).getCanonicalPath()), ...
        char(java.io.File(get_param(modelName, 'FileName')).getCanonicalPath())), ...
        'simrtlinux:ModelNameConflict', 'Another model with the same name is open.');
end
if loadedHere
    load_system(modelPath);
end
end

function parameters = preserveOrSet(parameters, name, requested, fallback)
if requested ~= ""
    parameters.(name) = char(requested);
elseif ~isfield(parameters, name) || strlength(string(parameters.(name))) == 0
    parameters.(name) = char(fallback);
end
end

function closeIfLoadedHere(modelName, loadedHere)
if loadedHere && bdIsLoaded(modelName)
    close_system(modelName, 0);
end
end
