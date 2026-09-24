function records = generate_period_models(outputFolder)
%GENERATE_PERIOD_MODELS Regenerate the saved 1 ms validation model in R2024b.
arguments
    outputFolder (1,1) string
end
assert(strcmp(version('-release'), '2024b'), 'MATLAB R2024b is required.');
projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(fullfile(projectRoot, 'x280_linux_target'));
setupX280LinuxTarget;
previous = Simulink.fileGenControl('getConfig');
restore = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', previous));
Simulink.fileGenControl('set', ...
    'CacheFolder', char(fullfile(outputFolder, 'cache')), ...
    'CodeGenFolder', char(fullfile(outputFolder, 'codegen')), 'createDir', true);
models = "x280_rt_single";
periods = 0.001;
records = struct([]);
for index = 1:numel(models)
    model = models(index);
    modelFile = fullfile(outputFolder, model + ".slx");
    if bdIsLoaded(model)
        assert(strcmp(get_param(model, 'Dirty'), 'off'), 'Save pending model edits first.');
        close_system(model, 0);
    end
    open_system(modelFile);
    assert(strcmp(get_param(model, 'SolverType'), 'Fixed-step'));
    assert(strcmp(get_param(model, 'EnableMultiTasking'), 'off'));
    assert(strcmp(get_param(model, 'ConcurrentTasks'), 'off'));
    assert(strcmp(get_param(model, 'GenCodeOnly'), 'on'));
    assert(str2double(get_param(model, 'FixedStep')) == periods(index));
    bundleFolder = fullfile(outputFolder, model + "_bundle");
    assert(~isfolder(bundleFolder), 'Use a new validation directory.');
    slbuild(model, 'GenerateCodeOnly', true);
    bundle = prepareX280AppBundle(model, bundleFolder);
    records(index).model = model;
    records(index).period_seconds = periods(index);
    records(index).tasking = "single";
    records(index).model_file = modelFile;
    records(index).model_sha256 = x280FileSHA256(modelFile);
    records(index).bundle = bundle;
end
file = fopen(fullfile(outputFolder, 'generation_report.json'), 'w', 'n', 'UTF-8');
assert(file >= 0);
closeFile = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(records, PrettyPrint=true));
end
