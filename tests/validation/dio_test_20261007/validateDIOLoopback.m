function report = validateDIOLoopback(options)
%VALIDATEDIOLOOPBACK Exercise the bench logic, desktop model and local build.
arguments
    options.Overwrite (1,1) logical = false
end
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
addpath(fullfile(root, 'simrt_linux_target'));
diary(fullfile(folder, 'matlab_validation.log'));
diaryCleanup = onCleanup(@() diary('off')); %#ok<NASGU>
checkLogic;
modelFile = createSimRTDIOLoopbackModel(Overwrite=options.Overwrite);
model = 'simrt_dio_loopback';
open_system(modelFile);
workspace = get_param(model, 'ModelWorkspace');
for name = {'DIO_Enable', 'DIO_Automatic', 'DIO_ManualMask', 'DIO_CheckLoopback'}
    control = getVariable(workspace, name{1});
    assert(control.Value == 0, 'Default meter mode must hold zero with loopback checking disabled.');
end
modelFolder = fileparts(modelFile);
previousFolder = cd(modelFolder);
folderCleanup = onCleanup(@() cd(previousFolder)); %#ok<NASGU>
settings = Simulink.fileGenControl('getConfig');
settingsCleanup = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', settings)); %#ok<NASGU>
Simulink.fileGenControl('set', 'CacheFolder', modelFolder, ...
    'CodeGenFolder', modelFolder, 'createDir', true);
simulation = sim(model, 'StopTime', '0.025');
for index = [1 2 3 4 5 6]
    values = simulation.yout.getElement(index).Values.Data;
    assert(all(values(:) == 0), 'Desktop model must not claim a hardware pass.');
end
for index = 7:10
    values = simulation.yout.getElement(index).Values.Data;
    assert(all(values(:) == -38), 'Desktop driver status must be unavailable.');
end
validateSimRTRealtimeModel(model);
print(['-s' model], '-dpng', '-r120', fullfile(folder, 'model.png'));
slbuild(model);
build = RTW.getBuildDir(model);
receipt = jsondecode(fileread(fullfile(build.BuildDirectory, 'simrt_local_build.json')));
assert(receipt.success && ~receipt.remote_operations_performed);
assert(strcmpi(simrtFileSHA256(receipt.archive), receipt.archive_sha256));
generated = fileread(fullfile(build.BuildDirectory, [model '.c']));
for symbol = {'simrt_dio_open', 'simrt_dio_read', 'simrt_dio_write', 'simrt_dio_close'}
    assert(contains(generated, symbol{1}), 'Generated hardware call is missing.');
end
a2l = fileread(receipt.a2l);
for symbol = {'DIO_Enable', 'DIO_Automatic', 'DIO_ManualMask', 'DIO_CheckLoopback', 'DIO_Ready', ...
        'DIO_InputMask', 'DIO_CommandMask', 'DIO_MismatchSamples'}
    assert(contains(a2l, symbol{1}), 'XCP test control or measurement is missing.');
end
report = struct('model', modelFile, 'logic_checks_passed', true, ...
    'desktop_simulation_passed', true, 'physical_io_test', false, ...
    'default_mode', 'manual_meter', 'loopback_check_default', false, ...
    'gpio_device', get_param([model '/DIO Output Setup'], 'Device'), 'build', receipt);
file = fopen(fullfile(folder, 'matlab_validation.json'), 'w', 'n', 'UTF-8');
fileCleanup = onCleanup(@() fclose(file)); %#ok<NASGU>
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
set_param(model, 'ZoomFactor', 'FitSystem');
disp(report);
end

function checkLogic
clear simrtlinux.dio.loopbackPattern simrtlinux.dio.loopbackMonitor
[values, mask] = simrtlinux.dio.loopbackPattern(uint8(0), uint8(1), uint8(15));
assert(mask == 0 && ~any(values));
for channel = 0:3
    for tick = 1:1000
        [values, mask] = simrtlinux.dio.loopbackPattern(uint8(1), uint8(1), uint8(0));
        assert(mask == bitshift(uint8(1), channel) && sum(values) == 1);
    end
end
for requested = 0:15
    [values, mask] = simrtlinux.dio.loopbackPattern(uint8(1), uint8(0), uint8(requested));
    assert(mask == requested && isequal(values, logical(bitget(uint8(requested), (1:4)'))));
end
[values, mask] = simrtlinux.dio.loopbackPattern(uint8(0), uint8(1), uint8(15));
assert(mask == 0 && ~any(values));
[~, ready, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
    false(4,1), uint8(0), uint8(1), repmat(int32(-38), 4, 1), true);
assert(~ready && ~valid && ~matched && count == 0);
for tick = 1:20
    [~, ready, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
        [true;false;false;false], uint8(1), uint8(1), zeros(4,1,'int32'), true);
    assert(ready && ~valid && ~matched && count == 0);
end
[inputMask, ready, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
    [true;false;false;false], uint8(1), uint8(1), zeros(4,1,'int32'), true);
assert(inputMask == 1 && ready && valid && matched && count == 0);
[~, ~, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
    false(4,1), uint8(1), uint8(1), zeros(4,1,'int32'), true);
assert(valid && ~matched && count == 1);
[~, ready, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
    false(4,1), uint8(1), uint8(1), int32([0;0;-9;0]), true);
assert(~ready && ~valid && ~matched && count == 1);
[~, ~, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
    false(4,1), uint8(0), uint8(0), zeros(4,1,'int32'), true);
assert(~valid && ~matched && count == 0);
% Unconnected inputs cannot fail the meter test while an output is held high.
for tick = 1:2100
    [values, mask] = simrtlinux.dio.loopbackPattern(uint8(1), uint8(0), uint8(8));
    assert(mask == 8 && isequal(values, [false; false; false; true]));
    [~, ready, valid, matched, count] = simrtlinux.dio.loopbackMonitor( ...
        false(4,1), mask, uint8(1), zeros(4,1,'int32'), false);
    assert(ready && ~valid && ~matched && count == 0);
end
clear simrtlinux.dio.loopbackPattern simrtlinux.dio.loopbackMonitor
end
