function report = buildX280DemoModels(outputFolder, options)
%BUILDX280DEMOMODELS Reproduce the delivered 1 ms model with a local Ctrl+B build.
arguments
    outputFolder (1,1) string
    options.Address (1,1) string = "192.168.219.86"
end
root = fileparts(fileparts(mfilename('fullpath')));
models = "x280_rt_single";
assert(~isfolder(outputFolder) && ~isfile(outputFolder), ...
    'x280linux:OutputExists', 'Use a new output folder to preserve earlier build evidence.');
for model = models
    assert(~bdIsLoaded(model), 'x280linux:ModelLoaded', ...
        'Close %s after preserving edits before building its delivery snapshot.', model);
end
outputFolder = string(java.io.File(char(outputFolder)).getCanonicalPath());
mkdir(outputFolder);
previous = Simulink.fileGenControl('getConfig');
cleanup = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', previous));
Simulink.fileGenControl('set', 'CacheFolder', char(fullfile(outputFolder, 'cache')), ...
    'CodeGenFolder', char(fullfile(outputFolder, 'codegen')), 'createDir', true);
records = struct([]);
for index = 1:numel(models)
    model = models(index);
    snapshot = fullfile(outputFolder, model + ".slx");
    copyfile(fullfile(root, 'Demo_XCP_Qt', 'models', model, model + ".slx"), snapshot);
    fprintf('### Local build %d/%d: %s\n', index, numel(models), model);
    buildError = [];
    buildLog = evalc(['try, item = buildX280Local(snapshot, Address=options.Address); ' ...
        'catch buildError, disp(getReport(buildError,''extended'',''hyperlinks'',''off'')); end']);
    writeText(fullfile(outputFolder, model + "_slbuild.log"), buildLog);
    if ~isempty(buildError), rethrow(buildError); end
    if index == 1
        records = item;
    else
        records(end + 1) = item; %#ok<AGROW>
    end
    fprintf('### Local payload: %s\n', item.payload);
    report = struct('success', index == numel(models), 'build_mode', "local", ...
        'host', options.Address, 'remote_operations_performed', false, 'models', records);
    writeText(fullfile(outputFolder, 'build_report.json'), jsonencode(report, PrettyPrint=true));
end
end

function writeText(file, value)
fid = fopen(file, 'w', 'n', 'UTF-8');
assert(fid >= 0, 'x280linux:BuildLogWrite', 'Cannot retain build evidence: %s', file);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, '%s', value);
end
