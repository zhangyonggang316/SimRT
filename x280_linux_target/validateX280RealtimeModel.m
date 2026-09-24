function report = validateX280RealtimeModel(model)
%VALIDATEX280REALTIMEMODEL Check the supported RT bundle contract without editing it.
arguments
    model (1,1) string
end
assert(strcmp(version('-release'), '2024b'), ...
    'x280linux:UnsupportedRelease', 'Use MATLAB R2024b for this runtime adapter.');
assert(bdIsLoaded(model), 'x280linux:ModelNotOpen', 'Open the saved model first.');
expected = {
    'SolverType', 'Fixed-step';
    'Solver', 'FixedStepDiscrete';
    'EnableMultiTasking', 'off';
    'ConcurrentTasks', 'off';
    'SystemTargetFile', 'ert.tlc';
    'TargetLang', 'C';
    'HardwareBoard', 'SimRT';
    'ProdHWDeviceType', 'Intel->x86-64 (Linux 64)';
    'ExtMode', 'on';
    'DefaultParameterBehavior', 'Tunable'};
settings = struct;
issues = strings(0, 1);
for index = 1:size(expected, 1)
    name = expected{index, 1};
    value = get_param(model, name);
    settings.(name) = string(value);
    if ~strcmp(value, expected{index, 2})
        issues(end + 1) = name + ": expected " + expected{index, 2} + ", got " + string(value); %#ok<AGROW>
    end
end
settings.FixedStep = string(get_param(model, 'FixedStep'));
period = str2double(settings.FixedStep);
if ~ismember(period, [0.001, 0.01, 0.1])
    issues(end + 1) = "FixedStep must be the literal 0.001, 0.01 or 0.1 seconds.";
end
if strcmp(get_param(model, 'Dirty'), 'on')
    issues(end + 1) = "Save the model before generating a reproducible bundle.";
end
assert(isempty(issues), 'x280linux:RealtimeConfiguration', '%s', strjoin(issues, newline));
report = struct('model', model, 'period_seconds', period, 'tasking', "single", ...
    'settings', settings, 'xcp', x280XCPConfiguration, 'matlab_release', string(version('-release')));
end
