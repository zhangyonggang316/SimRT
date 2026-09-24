function record = generateX280RealtimeBundle(model, outputFolder, options)
%GENERATEX280REALTIMEBUNDLE Generate, package and adapt one saved model without SSH.
arguments
    model (1,1) string
    outputFolder (1,1) string
    options.PythonExecutable (1,1) string = ""
end
targetRoot = fileparts(mfilename('fullpath'));
projectRoot = fileparts(targetRoot);
setupX280LinuxTarget;
[~, modelName] = fileparts(model);
if ~bdIsLoaded(modelName)
    open_system(model);
end
configuration = validateX280RealtimeModel(modelName);
modelFile = string(get_param(modelName, 'FileName'));
assert(isfile(modelFile), 'x280linux:UnsavedModel', 'Save the model to an SLX file first.');
if isfile(model)
    assert(strcmpi(char(java.io.File(char(model)).getCanonicalPath()), ...
        char(java.io.File(char(modelFile)).getCanonicalPath())), ...
        'x280linux:ModelNameConflict', 'Another model with the same name is open.');
end
outputFolder = string(java.io.File(char(outputFolder)).getCanonicalPath());
assert(~isfolder(outputFolder) && ~isfile(outputFolder), ...
    'x280linux:OutputExists', 'Use a new output folder; previous build evidence is never overwritten.');
if options.PythonExecutable == ""
    options.PythonExecutable = fullfile(projectRoot, '.venv', 'Scripts', 'python.exe');
end
assert(isfile(options.PythonExecutable), 'x280linux:PythonMissing', ...
    'Set PythonExecutable to the project Python interpreter.');
assert(~contains(options.PythonExecutable, '"') && ~contains(outputFolder, '"'), ...
    'x280linux:InvalidPath', 'Paths must not contain quotation marks.');
mkdir(outputFolder);
copyfile(modelFile, fullfile(outputFolder, modelName + ".slx"));
previous = Simulink.fileGenControl('getConfig');
restore = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', previous));
Simulink.fileGenControl('set', ...
    'CacheFolder', char(fullfile(outputFolder, 'cache')), ...
    'CodeGenFolder', char(fullfile(outputFolder, 'codegen')), 'createDir', true);
slbuild(modelName, 'GenerateCodeOnly', true);
generatedFolder = fullfile(outputFolder, modelName + "_bundle");
bundle = prepareX280AppBundle(modelName, generatedFolder);
realtimeFolder = fullfile(outputFolder, modelName + "_rt_bundle");
converter = fullfile(targetRoot, 'tools', 'enable_realtime_bundle.py');
command = sprintf('"%s" "%s" --source "%s" --output "%s"', ...
    options.PythonExecutable, converter, generatedFolder, realtimeFolder);
[status, output] = system(command);
assert(status == 0, 'x280linux:RealtimeConversion', '%s', output);
record = configuration;
record.model_file = fullfile(outputFolder, modelName + ".slx");
record.model_sha256 = x280FileSHA256(record.model_file);
record.bundle = bundle;
record.realtime_source = realtimeFolder;
record.build_command = "python build_model.py --toolchain-root <portable-linux-toolchain> --jobs 2";
record.elf_relative_path = modelName + ".elf";
record.remote_operations_performed = false;
file = fopen(fullfile(outputFolder, 'generation_report.json'), 'w', 'n', 'UTF-8');
assert(file >= 0, 'x280linux:ReportWrite', 'Cannot create generation_report.json.');
closeFile = onCleanup(@() fclose(file));
% Keep the multi-model report shape used by the local build and export tools.
fprintf(file, '[%s]\n', jsonencode(record, PrettyPrint=true));
disp(record);
end
