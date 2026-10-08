function report = validateSerialDuplex(options)
%VALIDATESERIALDUPLEX Test framing, driver feedback, desktop behavior and ELF.
arguments
    options.Overwrite (1,1) logical = false
    options.Build (1,1) logical = true
    options.Recreate (1,1) logical = true
end
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
addpath(fullfile(root, 'simrt_linux_target'));
diary(fullfile(folder, 'matlab_validation.log'));
cleanupDiary = onCleanup(@() diary('off')); %#ok<NASGU>
checkLogic;
disp('Serial framing, sequence, partial-write and scheduling checks passed.');
model = 'simrt_serial_com56';
if options.Recreate
    modelFile = createSimRTSerialDuplexModel(Overwrite=options.Overwrite);
else
    modelFile = fullfile(root, 'simrt_linux_target', 'drivers', 'serial', 'models', model, [model '.slx']);
end
open_system(modelFile);
modelFolder = fileparts(modelFile);
previous = cd(modelFolder);
cleanupFolder = onCleanup(@() cd(previous)); %#ok<NASGU>
settings = Simulink.fileGenControl('getConfig');
cleanupSettings = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', settings)); %#ok<NASGU>
Simulink.fileGenControl('set', 'CacheFolder', modelFolder, 'CodeGenFolder', modelFolder, 'createDir', true);
for enabled = [0 1]
    input = Simulink.SimulationInput(model);
    input = input.setVariable('Serial_Enable', uint8(enabled), 'Workspace', model);
    input = input.setModelParameter('StopTime', '0.22');
    simulation = sim(input);
    for name = {'Serial_Ready', 'Serial_Healthy', 'COM5_RxFrames', 'COM6_RxFrames', 'COM5_TxFrames', 'COM6_TxFrames'}
        values = simulation.logsout.getElement(name{1}).Values.Data;
        assert(all(values(:) == 0), 'Desktop simulation must not claim successful hardware traffic.');
    end
    for name = {'COM5_SetupStatus', 'COM6_SetupStatus', 'COM5_ReadStatus', 'COM6_ReadStatus'}
        values = simulation.logsout.getElement(name{1}).Values.Data;
        assert(all(values(:) == -38), 'Desktop setup/read must report unavailable transport.');
    end
end
validateSimRTRealtimeModel(model);
print(['-s' model], '-dpng', '-r100', fullfile(folder, 'model.png'));
receipt = struct;
if options.Build
    slbuild(model);
    build = RTW.getBuildDir(model);
    receipt = jsondecode(fileread(fullfile(build.BuildDirectory, 'simrt_local_build.json')));
    assert(receipt.success && ~receipt.remote_operations_performed);
    assert(strcmpi(simrtFileSHA256(receipt.archive), receipt.archive_sha256));
    generated = fileread(fullfile(build.BuildDirectory, [model '.c']));
    for symbol = {'simrt_serial_open', 'simrt_serial_send', 'simrt_serial_receive', 'simrt_serial_close'}
        assert(contains(generated, symbol{1}), 'Missing generated hardware call.');
    end
    a2l = fileread(receipt.a2l);
    for symbol = {'Serial_Enable', 'Serial_Ready', 'Serial_Healthy', 'COM5_TxFrames', ...
            'COM6_TxFrames', 'COM5_RxFrames', 'COM6_RxFrames', 'COM5_SequenceGaps', 'COM6_CrcErrors'}
        assert(contains(a2l, symbol{1}), 'Missing XCP control or measurement.');
    end
end
workspace = get_param(model, 'ModelWorkspace');
control = getVariable(workspace, 'Serial_Enable');
assert(control.Value == 0, 'Saved model must start with transmission disabled.');
if options.Build
    assert(strcmpi(simrtFileSHA256(modelFile), receipt.model_sha256), 'The model changed after its build snapshot.');
end
report = struct('model', modelFile, 'logic_checks_passed', true, 'desktop_simulation_passed', true, ...
    'physical_serial_test', false, 'device5', get_param([model '/COM5 Setup'], 'Device'), ...
    'device6', get_param([model '/COM6 Setup'], 'Device'), 'build', receipt);
file = fopen(fullfile(folder, 'matlab_validation.json'), 'w', 'n', 'UTF-8');
cleanupFile = onCleanup(@() fclose(file)); %#ok<NASGU>
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
set_param(model, 'ZoomFactor', 'FitSystem');
disp(report);
end

function checkLogic
clear simrtlinux.serial.duplexTransmit simrtlinux.serial.duplexReceive
assert(simrtlinux.serial.duplexCRC(uint8('123456789'), uint32(9)) == hex2dec('29B1'));
zero = zeros(2, 1, 'uint32'); status = zeros(2, 1, 'int32');
[~, n5, s5, ~, n6, s6, completed, failed] = simrtlinux.serial.duplexTransmit(0, status, zero, status);
assert(~s5 && ~s6 && n5 == 0 && n6 == 0 && ~any(completed) && ~any(failed));
[frame, n5, s5, ~, ~, s6] = simrtlinux.serial.duplexTransmit(1, status, zero, status);
assert(s5 && ~s6 && n5 == 12 && isequal(frame, simrtlinux.serial.duplexFrame(uint8(5), uint32(0))));
[suffix, n5, s5, ~, ~, ~, completed] = simrtlinux.serial.duplexTransmit(1, status, uint32([5;0]), int32([-11;0]));
assert(s5 && n5 == 7 && isequal(suffix(1:7), frame(6:12)) && ~any(completed));
[~, ~, s5, ~, ~, ~, completed, failed] = simrtlinux.serial.duplexTransmit(1, status, uint32([7;0]), status);
assert(~s5 && completed(1) == 1 && ~any(failed));
% Ten unsuccessful sample hits exhaust the COM5 window without overlapping COM6.
clear simrtlinux.serial.duplexTransmit
simrtlinux.serial.duplexTransmit(0, status, zero, status);
for tick = 0:100
    [~, ~, send5, ~, ~, send6, ~, failed] = simrtlinux.serial.duplexTransmit(1, status, zero, int32([-11;-11]));
    assert(~(send5 && send6));
    assert(~send5 || mod(tick,100) < 10);
    assert(~send6 || (mod(tick,100) >= 50 && mod(tick,100) < 60));
    if tick == 10, assert(failed(1) == 1); end
    if tick == 60, assert(failed(2) == 1); end
end
clear simrtlinux.serial.duplexTransmit
simrtlinux.serial.duplexTransmit(0, status, zero, status);
simrtlinux.serial.duplexTransmit(1, status, zero, status);
[~,~,send5,~,~,~,completed,failed] = simrtlinux.serial.duplexTransmit(1, status, zero, int32([-5;0]));
assert(~send5 && completed(1) == 0 && failed(1) == 1);
clear simrtlinux.serial.duplexTransmit
simrtlinux.serial.duplexTransmit(0, status, zero, status);
[~,~,send5,~,~,send6,completed,failed] = simrtlinux.serial.duplexTransmit(1, int32([-38;-38]), zero, status);
assert(~send5 && ~send6 && ~any(completed) && failed(1) == 1);
% Streaming receive: noise, split frame, multiple frames, corruption and gaps.
empty = zeros(64, 1, 'uint8');
simrtlinux.serial.duplexReceive(0, empty, uint32(0), empty, uint32(0), status);
frame6 = simrtlinux.serial.duplexFrame(uint8(6), uint32(0));
frame5 = simrtlinux.serial.duplexFrame(uint8(5), uint32(0));
[a,b,healthy] = receive([uint8(99);frame6(1:5)], frame5);
assert(a(1) == 0 && b(1) == 1 && ~healthy);
[a,b,healthy] = receive(frame6(6:12), []);
assert(a(1) == 1 && b(1) == 1 && healthy);
[a,~,~] = receive([simrtlinux.serial.duplexFrame(uint8(6), uint32(1)); ...
    simrtlinux.serial.duplexFrame(uint8(6), uint32(2))], []);
assert(a(1) == 3 && a(6) == 2 && a(3) == 0);
[a,~,healthy] = receive(simrtlinux.serial.duplexFrame(uint8(6), uint32(2)), []);
assert(a(1) == 3 && a(4) == 1 && ~healthy);
[a,~,~] = receive(simrtlinux.serial.duplexFrame(uint8(6), uint32(5)), []);
assert(a(1) == 4 && a(3) == 2);
bad = simrtlinux.serial.duplexFrame(uint8(6), uint32(6)); bad(9) = bitxor(bad(9), uint8(1));
[a,~,~] = receive([bad; simrtlinux.serial.duplexFrame(uint8(6), uint32(6))], []);
assert(a(1) == 5 && a(2) == 1);
[a,~,~] = receive(simrtlinux.serial.duplexFrame(uint8(6), uint32(4)), []);
assert(a(1) == 5 && a(4) == 2 && a(6) == 6);
[a,b,healthy] = simrtlinux.serial.duplexReceive(0, empty, uint32(0), empty, uint32(0), status);
assert(~any(a) && ~any(b) && ~healthy);
[a,b,healthy] = simrtlinux.serial.duplexReceive(1, empty, uint32(0), empty, uint32(0), int32([-38;-38]));
assert(a(1) == 0 && b(1) == 0 && ~healthy);
clear simrtlinux.serial.duplexTransmit simrtlinux.serial.duplexReceive
end

function [a,b,healthy] = receive(bytes5, bytes6)
data5 = zeros(64, 1, 'uint8'); data6 = data5;
data5(1:numel(bytes5)) = bytes5; data6(1:numel(bytes6)) = bytes6;
[a,b,healthy] = simrtlinux.serial.duplexReceive(1, data5, uint32(numel(bytes5)), ...
    data6, uint32(numel(bytes6)), zeros(2, 1, 'int32'));
end
