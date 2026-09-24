function config = configureX280Model(model, options)
%CONFIGUREX280MODEL Configure Ctrl+B for local Linux code generation and build.

arguments
    model (1,1) string
    options.Address (1,1) string = "192.168.219.86"
    options.Username (1,1) string = ""
    options.BuildDirectory (1,1) string = "/tmp/matlab_x280"
    options.BuildAction (1,1) string {mustBeMember(options.BuildAction, "Build")} = "Build"
    options.EnableParallelBuild (1,1) logical = true
    options.Save (1,1) logical = true
end

setupX280LinuxTarget;
[modelName, loadedHere] = openModel(model);
cleanup = onCleanup(@() closeIfLoadedHere(modelName, loadedHere));

if ~strcmp(codertarget.target.getHardwareName(modelName), 'SimRT')
    codertarget.target.setTargetHardware(modelName, 'SimRT');
end

data = get_param(modelName, 'CoderTargetData');
data.BoardParameters.DeviceAddress = char(options.Address);
data.BoardParameters.Username = char(options.Username);
data.BoardParameters.BuildDir = char(options.BuildDirectory);
data.Runtime.BuildAction = char(options.BuildAction);
data.BuildTime.EnableParallelBuild = options.EnableParallelBuild;
set_param(modelName, 'CoderTargetData', data);

set_param(modelName, ...
    'SolverType', 'Fixed-step', ...
    'Solver', 'FixedStepDiscrete', ...
    'SystemTargetFile', 'ert.tlc', ...
    'Toolchain', 'X280 portable-linux-toolchain', ...
    'GenCodeOnly', 'off', ...
    'EnableMultiTasking', 'off', ...
    'ConcurrentTasks', 'off', ...
    'GenerateASAP2', 'off', ...
    'DefaultParameterBehavior', 'Tunable', ...
    'ExtMode', 'on');
coder.coverage.BuildHook.addHook(modelName, ...
    'codertarget.x280linuxssh.internal.LocalBuildHook', ...
    'IncludeReferencedModels', 'off');

if options.Save
    save_system(modelName);
end

config = struct( ...
    'Model', string(modelName), ...
    'HardwareBoard', "SimRT", ...
    'Address', options.Address, ...
    'Username', options.Username, ...
    'BuildDirectory', options.BuildDirectory, ...
    'BuildAction', options.BuildAction, ...
    'XCPTransport', x280XCPConfiguration().Transport, ...
    'XCPPort', x280XCPConfiguration().Port, ...
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
if loadedHere
    load_system(modelPath);
end
end

function closeIfLoadedHere(modelName, loadedHere)
if loadedHere && bdIsLoaded(modelName)
    close_system(modelName, 0);
end
end
