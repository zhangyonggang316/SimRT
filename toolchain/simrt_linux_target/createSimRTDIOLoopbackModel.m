function modelFile = createSimRTDIOLoopbackModel(options)
%CREATESIMRTDIOLOOPBACKMODEL ARK meter test with optional four-channel loopback.
arguments
    options.OutputFolder (1,1) string = fullfile(simrtProjectRoot, ...
        'demos', 'io', 'dio', 'simrt_dio_loopback')
    options.Device (1,1) string = "/dev/simrt-ark-dio-unconfigured"
    options.OutputLineOffsets (1,4) double {mustBeInteger, mustBeNonnegative} = 0:3
    options.InputLineOffsets (1,4) double {mustBeInteger, mustBeNonnegative} = 4:7
    options.Address (1,1) string = "192.168.193.195"
    options.Overwrite (1,1) logical = false
end
assert(numel(unique([options.OutputLineOffsets options.InputLineOffsets])) == 8, ...
    'simrt:dio:OverlappingLines', 'Input and output offsets must be distinct.');
assert(startsWith(options.Device, '/dev/'), 'simrt:dio:Device', 'Use a /dev/ GPIO device.');
model = 'simrt_dio_loopback';
assert(~bdIsLoaded(model), 'simrt:dio:ModelLoaded', 'Close the test model before recreating it.');
modelFile = fullfile(options.OutputFolder, model + ".slx");
assert(~isfile(modelFile) || options.Overwrite, 'simrt:dio:ModelExists', ...
    'The model already exists. Use Overwrite=true only to replace it.');
if ~isfolder(options.OutputFolder), mkdir(options.OutputFolder); end
setupSimRTDIOLibrary;
load_system('simrt_dio_library');
new_system(model);
cleanup = onCleanup(@() close_system(model, 0)); %#ok<NASGU>
set_param(model, 'SolverType', 'Fixed-step', 'Solver', 'FixedStepDiscrete', ...
    'FixedStep', '0.001', 'StopTime', 'inf', 'EnableMultiTasking', 'off', ...
    'SaveOutput', 'on', 'OutputSaveName', 'yout', 'SaveFormat', 'Dataset', ...
    'ReturnWorkspaceOutputs', 'on', 'Location', [80 80 1540 960]);
workspace = get_param(model, 'ModelWorkspace');
parameter(workspace, 'DIO_Enable', 0, 1, '0 drives all four outputs low; 1 enables the selected pattern.');
parameter(workspace, 'DIO_Automatic', 0, 1, '1: one active output per second; 0: hold the manual bit mask.');
parameter(workspace, 'DIO_ManualMask', 0, 15, 'Bit 0..3 control DIO0..3 in manual mode.');
parameter(workspace, 'DIO_CheckLoopback', 0, 1, 'Enable only with DIO0..3 wired to DIO4..7. Leave at 0 for meter tests.');
constant(model, 'Enable outputs', 'DIO_Enable', [35 75 155 110]);
constant(model, 'Automatic mode', 'DIO_Automatic', [35 145 155 180]);
constant(model, 'Manual mask', 'DIO_ManualMask', [35 215 155 250]);
constant(model, 'Check loopback', 'DIO_CheckLoopback', [35 285 155 320]);
functionBlock(model, 'Output pattern', ...
    ['function [values, mask, writeEnable] = pattern(enable, automatic, manualMask)' newline ...
     '[values, mask] = simrtlinux.dio.loopbackPattern(enable, automatic, manualMask);' newline ...
     'writeEnable = true;' newline 'end'], ...
    [235 80 415 245]);
setup(model, 'DIO Output Setup', options.Device, options.OutputLineOffsets, 'Output', [235 305 430 405]);
add_block('simrt_dio_library/DIO Write', [model '/DIO Write'], ...
    'Position', [520 105 695 235]);
setup(model, 'DIO Input Setup', options.Device, options.InputLineOffsets, 'Input', [235 555 430 655]);
add_block('simrt_dio_library/DIO Read', [model '/DIO Read'], ...
    'LineCount', '4', 'Position', [520 555 695 655]);
add_block('simulink/Signal Routing/Mux', [model '/Driver status'], ...
    'Inputs', '4', 'Position', [765 345 770 455]);
functionBlock(model, 'Loopback monitor', ...
    ['function [inputMask, ready, valid, matched, mismatches] = monitor(values, mask, enable, status, checkLoopback)' newline ...
     '[inputMask, ready, valid, matched, mismatches] = simrtlinux.dio.loopbackMonitor(values, mask, enable, status, checkLoopback);' newline 'end'], ...
    [865 355 1080 555]);
wire(model, 'Enable outputs/1', 'Output pattern/1');
wire(model, 'Automatic mode/1', 'Output pattern/2');
wire(model, 'Manual mask/1', 'Output pattern/3');
wire(model, 'DIO Output Setup/1', 'DIO Write/1');
wire(model, 'Output pattern/1', 'DIO Write/2');
wire(model, 'Output pattern/3', 'DIO Write/3');
wire(model, 'DIO Input Setup/1', 'DIO Read/1');
wire(model, 'DIO Output Setup/2', 'Driver status/1');
wire(model, 'DIO Input Setup/2', 'Driver status/2');
wire(model, 'DIO Read/2', 'Driver status/3');
wire(model, 'DIO Write/1', 'Driver status/4');
wire(model, 'DIO Read/1', 'Loopback monitor/1');
wire(model, 'Output pattern/2', 'Loopback monitor/2');
wire(model, 'Enable outputs/1', 'Loopback monitor/3');
wire(model, 'Driver status/1', 'Loopback monitor/4');
wire(model, 'Check loopback/1', 'Loopback monitor/5');
signals = {
    'Output pattern', 2, 'DIO_CommandMask';
    'Loopback monitor', 1, 'DIO_InputMask';
    'Loopback monitor', 2, 'DIO_Ready';
    'Loopback monitor', 3, 'DIO_Valid';
    'Loopback monitor', 4, 'DIO_Matched';
    'Loopback monitor', 5, 'DIO_MismatchSamples';
    'DIO Output Setup', 2, 'DIO_OutputSetupStatus';
    'DIO Input Setup', 2, 'DIO_InputSetupStatus';
    'DIO Read', 2, 'DIO_ReadStatus';
    'DIO Write', 1, 'DIO_WriteStatus'};
for index = 1:size(signals,1)
    block = signals{index,1}; port = signals{index,2}; name = signals{index,3};
    ports = get_param([model '/' block], 'PortHandles');
    set_param(ports.Outport(port), 'TestPoint', 'on');
    line = get_param(ports.Outport(port), 'Line');
    if line ~= -1, set_param(line, 'Name', name); end
    add_block('simulink/Sinks/Out1', [model '/' name], 'Port', num2str(index), ...
        'Position', [1220 70+index*60 1250 84+index*60]);
    line = wire(model, sprintf('%s/%d', block, port), [name '/1']);
    set_param(line, 'Name', name);
end
note = Simulink.Annotation(model, sprintf([ ...
    'SimRT ARK DIO meter test: measure DIO0..3 relative to GND. No loopback wires required.\n' ...
    'Defaults: outputs disabled, manual mask 0, loopback check off. Hold masks 1, 2, 4, 8 or 15.\n' ...
    'Set a verified GPIO chip and offsets in both Setup blocks before hardware use.']));
note.Position = [35 10];
note.FontSize = 11;
save_system(model, modelFile);
configureSimRTModel(model, Address=options.Address, Save=true);
set_param(model, 'SimulationCommand', 'update');
save_system(model, modelFile);
end

function parameter(workspace, name, value, maximum, description)
item = Simulink.Parameter(uint8(value));
item.DataType = 'uint8'; item.Min = 0; item.Max = maximum;
item.Description = description;
item.CoderInfo.StorageClass = 'ExportedGlobal';
assignin(workspace, name, item);
end

function constant(model, name, value, position)
add_block('simulink/Sources/Constant', [model '/' name], ...
    'Value', value, 'SampleTime', '0.001', 'Position', position);
end

function setup(model, name, device, offsets, direction, position)
add_block('simrt_dio_library/DIO Setup', [model '/' name], ...
    'Device', char(device), 'LineOffsets', mat2str(offsets), 'Direction', direction, ...
    'InitialValues', 'false', 'SampleTime', '0.001', 'Position', position);
end

function functionBlock(model, name, script, position)
block = [model '/' name];
add_block('simulink/User-Defined Functions/MATLAB Function', block, 'Position', position);
chart = find(sfroot, '-isa', 'Stateflow.EMChart', 'Path', block);
chart.Script = script;
end

function line = wire(model, source, destination)
line = add_line(model, source, destination, 'autorouting', 'on');
end
