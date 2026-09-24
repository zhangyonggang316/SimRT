function modelPath = createX280ExampleModel(options)
%CREATEX280EXAMPLEMODEL Create an R2024b X280 calibration demo model.

arguments
    options.OutputFolder (1,1) string = fullfile( ...
        fileparts(mfilename('fullpath')), 'models')
    options.ModelName (1,1) string = "x280_calibration_demo"
    options.Address (1,1) string = "192.168.219.86"
    options.Username (1,1) string = ""
    options.BasePeriod (1,1) double {mustBeMember(options.BasePeriod, [0.001, 0.01, 0.1])} = 0.001
    options.Overwrite (1,1) logical = false
end

setupX280LinuxTarget;
mustBeValidVariableName(options.ModelName);
if ~isfolder(options.OutputFolder)
    mkdir(options.OutputFolder);
end
modelPath = fullfile(options.OutputFolder, options.ModelName + ".slx");
if isfile(modelPath) && ~options.Overwrite
    error('x280linux:ModelExists', ...
        'Model already exists: %s. Set Overwrite=true to replace it.', modelPath);
end

modelName = char(options.ModelName);
if bdIsLoaded(modelName)
    error('x280linux:ModelLoaded', ...
        'Close the loaded model %s before recreating it.', modelName);
end
new_system(modelName);
cleanup = onCleanup(@() closeModel(modelName));

add_block('simulink/Sources/Sine Wave', modelName + "/Excitation", ...
    'Amplitude', 'InputAmplitude', ...
    'Frequency', '1', ...
    'SampleTime', char(string(options.BasePeriod)), ...
    'Position', [55 80 125 110]);
add_block('simulink/Math Operations/Gain', modelName + "/Calibrated gain", ...
    'Gain', 'CalGain', ...
    'Position', [180 75 270 115]);
add_block('simulink/Math Operations/Bias', modelName + "/Calibrated offset", ...
    'Bias', 'CalOffset', ...
    'Position', [330 75 430 115]);
add_block('simulink/Discontinuities/Saturation', modelName + "/Output limits", ...
    'UpperLimit', 'OutputUpperLimit', ...
    'LowerLimit', 'OutputLowerLimit', ...
    'Position', [490 70 580 120]);
add_block('simulink/Sinks/Out1', modelName + "/Measured output", ...
    'Position', [650 88 680 102]);

add_line(modelName, 'Excitation/1', 'Calibrated gain/1');
add_line(modelName, 'Calibrated gain/1', 'Calibrated offset/1');
measuredLine = add_line(modelName, 'Calibrated offset/1', 'Output limits/1');
set_param(measuredLine, 'Name', 'MeasuredBeforeLimits');
limitedLine = add_line(modelName, 'Output limits/1', 'Measured output/1');
set_param(limitedLine, 'Name', 'MeasuredOutput');
offsetPorts = get_param(modelName + "/Calibrated offset", 'PortHandles');
limitPorts = get_param(modelName + "/Output limits", 'PortHandles');
set_param(offsetPorts.Outport, 'TestPoint', 'on');
set_param(limitPorts.Outport, 'TestPoint', 'on');

workspace = get_param(modelName, 'ModelWorkspace');
assignin(workspace, 'InputAmplitude', calibrationParameter(1.0, 0, 10));
assignin(workspace, 'CalGain', calibrationParameter(2.0, 0, 20));
assignin(workspace, 'CalOffset', calibrationParameter(0.0, -10, 10));
assignin(workspace, 'OutputUpperLimit', calibrationParameter(10.0, 0, 100));
assignin(workspace, 'OutputLowerLimit', calibrationParameter(-10.0, -100, 0));

set_param(modelName, ...
    'StopTime', 'inf', ...
    'FixedStep', char(string(options.BasePeriod)), ...
    'EnableMultiTasking', 'off', ...
    'SignalLogging', 'on', ...
    'SignalLoggingName', 'logsout');
configureX280Model(modelName, ...
    Address=options.Address, ...
    Username=options.Username, ...
    Save=false);
save_system(modelName, modelPath);
clear cleanup;
end

function parameter = calibrationParameter(value, minimum, maximum)
parameter = Simulink.Parameter(value);
parameter.Min = minimum;
parameter.Max = maximum;
parameter.CoderInfo.StorageClass = 'ExportedGlobal';
end

function mustBeValidVariableName(value)
if ~isvarname(char(value))
    error('x280linux:InvalidModelName', ...
        'ModelName must be a valid MATLAB identifier.');
end
end

function closeModel(modelName)
if bdIsLoaded(modelName)
    close_system(modelName, 0);
end
end
