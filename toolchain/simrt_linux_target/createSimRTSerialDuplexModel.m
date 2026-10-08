function modelFile = createSimRTSerialDuplexModel(options)
%CREATESIMRTSERIALDUPLEXMODEL Two-port, half-duplex RS485 bench test.
arguments
    options.OutputFolder (1,1) string = fullfile(simrtProjectRoot, ...
        'demos', 'io', 'serial', 'simrt_serial_com56')
    options.Device5 (1,1) string = "/dev/ttyS6"
    options.Device6 (1,1) string = "/dev/ttyS7"
    options.Address (1,1) string = "192.168.193.195"
    options.Overwrite (1,1) logical = false
end
assert(options.Device5 ~= options.Device6, 'simrt:serial:DuplicateDevice', 'Use two different serial devices.');
for device = [options.Device5 options.Device6]
    assert(startsWith(device, '/dev/'), 'simrt:serial:Device', 'Use a Linux /dev/ serial device.');
end
model = 'simrt_serial_com56';
assert(~bdIsLoaded(model), 'simrt:serial:ModelLoaded', 'Close the test model before recreating it.');
modelFile = fullfile(options.OutputFolder, model + ".slx");
assert(~isfile(modelFile) || options.Overwrite, 'simrt:serial:ModelExists', 'Use Overwrite=true to replace the model.');
if ~isfolder(options.OutputFolder), mkdir(options.OutputFolder); end
setupSimRTSerialLibrary;
load_system('simrt_serial_library');
new_system(model);
cleanup = onCleanup(@() close_system(model, 0)); %#ok<NASGU>
set_param(model, 'SolverType', 'Fixed-step', 'Solver', 'FixedStepDiscrete', ...
    'FixedStep', '0.001', 'StopTime', 'inf', 'EnableMultiTasking', 'off', ...
    'SignalLogging', 'on', 'SignalLoggingName', 'logsout', ...
    'ReturnWorkspaceOutputs', 'on', 'Location', [70 70 1610 980]);
workspace = get_param(model, 'ModelWorkspace');
control = Simulink.Parameter(uint8(0));
control.DataType = 'uint8'; control.Min = 0; control.Max = 1;
control.Description = '0 stops transmission and clears bench counters; 1 starts alternating COM5/COM6 frames.';
control.CoderInfo.StorageClass = 'ExportedGlobal';
assignin(workspace, 'Serial_Enable', control);
add_block('simulink/Sources/Constant', [model '/Enable test'], 'Value', 'Serial_Enable', ...
    'SampleTime', '0.001', 'Position', [30 360 145 405]);
functionBlock(model, 'Alternating transmitter', ...
    ['function [data5, length5, send5, data6, length6, send6, completed, failures] = tx(enable, setup, sent, status)' newline ...
     '[data5, length5, send5, data6, length6, send6, completed, failures] = simrtlinux.serial.duplexTransmit(enable, setup, sent, status);' newline 'end'], ...
    [315 285 550 525]);
functionBlock(model, 'Streaming frame receivers', ...
    ['function [stats5, stats6, healthy] = rx(enable, data5, length5, data6, length6, status)' newline ...
     '[stats5, stats6, healthy] = simrtlinux.serial.duplexReceive(enable, data5, length5, data6, length6, status);' newline 'end'], ...
    [1080 310 1310 520]);
devices = [options.Device5 options.Device6];
for port = 1:2
    label = sprintf('COM%d', port + 4); y = 90 + (port - 1) * 570;
    add_block('simrt_serial_library/Serial Setup', [model '/' label ' Setup'], ...
        'Device', char(devices(port)), 'BaudRate', '115200', 'DataBits', '8', 'Parity', 'None', ...
        'StopBits', '1', 'Mode', 'RS485', 'RS485Direction', 'Hardware auto', ...
        'SampleTime', '0.001', 'Position', [335 y 550 y+90]);
    add_block('simrt_serial_library/Serial Sent', [model '/' label ' Sent'], ...
        'Position', [705 y 885 y+110]);
    add_block('simrt_serial_library/Serial Receive', [model '/' label ' Receive'], ...
        'BufferSize', '64', 'Position', [920 y 1095 y+90]);
    wire(model, [label ' Setup/1'], [label ' Sent/1']);
    wire(model, [label ' Setup/1'], [label ' Receive/1']);
    for index = 1:3
        wire(model, sprintf('Alternating transmitter/%d', (port-1)*3+index), ...
            sprintf('%s Sent/%d', label, index+1));
    end
    wire(model, [label ' Receive/1'], sprintf('Streaming frame receivers/%d', port*2));
    wire(model, [label ' Receive/2'], sprintf('Streaming frame receivers/%d', port*2+1));
    observer(model, label, [1360 y 1580 y+200]);
    wire(model, sprintf('Streaming frame receivers/%d', port), [label ' counters/1']);
    select(model, [label ' completed'], port, 2, [1140 y+110 1190 y+140]);
    select(model, [label ' failed'], port, 2, [1210 y+155 1260 y+185]);
    wire(model, 'Alternating transmitter/7', [label ' completed/1']);
    wire(model, 'Alternating transmitter/8', [label ' failed/1']);
    wire(model, [label ' completed/1'], [label ' counters/2']);
    wire(model, [label ' failed/1'], [label ' counters/3']);
    wire(model, [label ' Setup/2'], [label ' counters/4']);
    wire(model, [label ' Receive/3'], [label ' counters/5']);
    wire(model, [label ' Sent/2'], [label ' counters/6']);
end
sources = {'Setup statuses', 'Sent counts', 'Write statuses', 'Read statuses'};
for index = 1:4
    name = sources{index};
    add_block('simulink/Signal Routing/Mux', [model '/' name], 'Inputs', '2', ...
        'ShowName', 'off', 'Position', [55+index*35 800 60+index*35 850]);
end
for port = 1:2
    label = sprintf('COM%d', port+4);
    wire(model, [label ' Setup/2'], sprintf('Setup statuses/%d', port));
    wire(model, [label ' Sent/1'], sprintf('Sent counts/%d', port));
    wire(model, [label ' Sent/2'], sprintf('Write statuses/%d', port));
    wire(model, [label ' Receive/3'], sprintf('Read statuses/%d', port));
end
for item = {'Sent counts', 'Write statuses'}
    name = item{1};
    datatype = 'uint32'; if strcmp(name, 'Write statuses'), datatype = 'int32'; end
    add_block('simulink/Discrete/Unit Delay', [model '/' name ' feedback'], ...
        'InitialCondition', [datatype '(0)'], 'SampleTime', '0.001', ...
        'Position', [235 800+strcmp(datatype,'int32')*70 275 835+strcmp(datatype,'int32')*70]);
    wire(model, [name '/1'], [name ' feedback/1']);
end
wire(model, 'Enable test/1', 'Alternating transmitter/1');
wire(model, 'Setup statuses/1', 'Alternating transmitter/2');
wire(model, 'Sent counts feedback/1', 'Alternating transmitter/3');
wire(model, 'Write statuses feedback/1', 'Alternating transmitter/4');
wire(model, 'Enable test/1', 'Streaming frame receivers/1');
wire(model, 'Read statuses/1', 'Streaming frame receivers/6');
functionBlock(model, 'Transport health', ...
    ['function [ready, passed] = health(setup, writes, reads, framesHealthy, txFailures)' newline ...
     'ready = all(setup == 0) && all(reads == 0) && all(writes == 0 | writes == -11);' newline ...
     'passed = ready && framesHealthy && all(txFailures == 0);' newline 'end'], ...
    [1135 1000 1350 1145]);
wire(model, 'Setup statuses/1', 'Transport health/1');
wire(model, 'Write statuses/1', 'Transport health/2');
wire(model, 'Read statuses/1', 'Transport health/3');
wire(model, 'Streaming frame receivers/3', 'Transport health/4');
wire(model, 'Alternating transmitter/8', 'Transport health/5');
for index = 1:2
    names = {'Serial_Ready', 'Serial_Healthy'}; name = names{index};
    add_block('simulink/Sinks/Out1', [model '/' name], 'Port', num2str(index), ...
        'Position', [1460 1045+index*50 1490 1059+index*50]);
    line = wire(model, sprintf('Transport health/%d', index), [name '/1']);
    mark(model, 'Transport health', index, line, name);
end
note = Simulink.Annotation(model, sprintf([ ...
    'SimRT COM5 / COM6 RS485 bidirectional bench test | 115200 8N1 | 1 ms base rate\n' ...
    'COM5 sends at 0 ms, COM6 at 50 ms, repeating every 100 ms. Serial_Enable defaults to 0.\n' ...
    '12-byte CRC16 frames; partial-write retries end at 10 ms. Confirm connector-to-device mapping before use.']));
note.Position = [30 10]; note.FontSize = 11;
save_system(model, modelFile);
configureSimRTModel(model, Address=options.Address, Save=true);
set_param(model, 'SimulationCommand', 'update');
save_system(model, modelFile);
end

function observer(model, label, position)
path = [model '/' label ' counters'];
add_block('simulink/Ports & Subsystems/Subsystem', path, 'Position', position);
Simulink.SubSystem.deleteContents(path);
inputNames = {'Rx statistics', 'TxFrames', 'TxFailures', 'SetupStatus', 'ReadStatus', 'WriteStatus'};
for index = 1:numel(inputNames)
    add_block('simulink/Sources/In1', [path '/' inputNames{index}], 'Port', num2str(index), ...
        'Position', [30 40+index*80 60 54+index*80]);
end
names = {'RxFrames', 'CrcErrors', 'SequenceGaps', 'Duplicates', 'ForeignFrames', ...
    'LastSequence', 'RxAgeMs', 'FormatErrors', 'TxFrames', 'TxFailures', 'SetupStatus', 'ReadStatus', 'WriteStatus'};
for index = 1:numel(names)
    name = [label '_' names{index}];
    if index <= 8
        block = [names{index} ' selector'];
        select(path, block, index, 8, [180 30+index*55 225 55+index*55]);
        wire(path, 'Rx statistics/1', [block '/1']);
    else
        block = inputNames{index-7};
    end
    add_block('simulink/Sinks/Terminator', [path '/' name], ...
        'Position', [630 30+index*55 650 50+index*55]);
    export = [names{index} ' export'];
    add_block('simulink/Signal Attributes/Signal Conversion', [path '/' export], ...
        'ConversionOutput', 'Signal copy', 'Position', [375 30+index*55 420 50+index*55]);
    wire(path, [block '/1'], [export '/1']);
    line = wire(path, [export '/1'], [name '/1']);
    mark(path, export, 1, line, name);
end
end

function select(model, name, index, width, position)
add_block('simulink/Signal Routing/Selector', [model '/' name], ...
    'NumberOfDimensions', '1', 'IndexMode', 'One-based', 'InputPortWidth', num2str(width), 'Indices', num2str(index), ...
    'Position', position);
end

function mark(model, block, port, line, name)
handles = get_param([model '/' block], 'PortHandles');
set_param(handles.Outport(port), 'TestPoint', 'on', 'DataLogging', 'on', ...
    'DataLoggingNameMode', 'Custom', 'DataLoggingName', name, ...
    'RTWStorageClass', 'ExportedGlobal');
set_param(line, 'Name', name);
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
