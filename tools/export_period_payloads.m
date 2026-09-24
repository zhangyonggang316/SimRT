function records = export_period_payloads(outputFolder, options)
%EXPORT_PERIOD_PAYLOADS Export A2L against the exact locally cross-compiled ELF.
arguments
    outputFolder (1,1) string
    options.BuildFolder (1,1) string = ""
end
projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(fullfile(projectRoot, 'x280_linux_target'));
if options.BuildFolder == ""
    options.BuildFolder = outputFolder;
end
build = jsondecode(fileread(fullfile(options.BuildFolder, 'build_report.json')));
generation = jsondecode(fileread(fullfile(outputFolder, 'generation_report.json')));
assert(isfield(build, 'success') && isequal(build.success, true) && ...
    isfield(build, 'host') && strlength(string(build.host)) > 0, ...
    'A successful build report with its actual target host is required.');
assert(isfolder(fullfile(outputFolder, 'codegen')) && ...
    isfolder(fullfile(outputFolder, 'cache')), ...
    'Preserve the matching generation cache and codegen metadata.');
assert(isfield(generation, 'model_sha256'), ...
    'Regenerate with the current tools: generation report has no model hash.');
assert(~isfile(fullfile(options.BuildFolder, 'export_report.json')), ...
    'Preserve existing export evidence; use a new build directory.');
% Validate the whole selection before creating any payload directories.
for index = 1:numel(build.models)
    item = build.models(index);
    model = string(item.model);
    assert(~isempty(regexp(model, '^[A-Za-z][A-Za-z0-9_]*$', 'once')), ...
        'Invalid model name in build report.');
    match = find(string({generation.model}) == model);
    assert(isscalar(match), 'Each built model must match one generation record.');
    expectedHash = string(generation(match).model_sha256);
    snapshot = fullfile(outputFolder, model + ".slx");
    assert(x280FileSHA256(snapshot) == expectedHash, ...
        'Model snapshot changed after code generation: %s.', model);
    assert(isfield(item, 'success') && isequal(item.success, true) && ...
        isfield(item, 'elf_sha256') && ...
        x280FileSHA256(string(item.local_elf)) == string(item.elf_sha256), ...
        'ELF does not match a successful build: %s.', model);
    if bdIsLoaded(model)
        assert(strcmp(get_param(model, 'Dirty'), 'off') && ...
            x280FileSHA256(string(get_param(model, 'FileName'))) == expectedHash, ...
            'Open model differs from the generation snapshot. Preserve edits and close it first: %s.', model);
    end
    assert(~isfolder(fullfile(options.BuildFolder, model + "_payload")), ...
        'Existing delivery must be preserved: %s.', model);
end
previous = Simulink.fileGenControl('getConfig');
restore = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', previous));
Simulink.fileGenControl('set', ...
    'CacheFolder', char(fullfile(outputFolder, 'cache')), ...
    'CodeGenFolder', char(fullfile(outputFolder, 'codegen')));
records = struct([]);
for index = 1:numel(build.models)
    model = string(build.models(index).model);
    payload = fullfile(options.BuildFolder, model + "_payload");
    [a2l, elf, manifest] = exportX280A2L(fullfile(outputFolder, model + ".slx"), ...
        OutputFolder=payload, MapFile=string(build.models(index).local_elf), ...
        TargetAddress=string(build.host));
    records(index).model = model;
    records(index).a2l = a2l;
    records(index).elf = elf;
    records(index).manifest = manifest;
    records(index).model_sha256 = string(generation(string({generation.model}) == model).model_sha256);
    records(index).elf_sha256 = x280FileSHA256(elf);
    records(index).a2l_sha256 = x280FileSHA256(a2l);
    records(index).runtime_tested = false;
end
file = fopen(fullfile(options.BuildFolder, 'export_report.json'), 'w', 'n', 'UTF-8');
assert(file >= 0, 'Cannot create export report.');
closeFile = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(records, PrettyPrint=true));
end
