function elfFile = locateX280ELF(model)
%LOCATEX280ELF Find this model's linker output or verified published ELF.

arguments
    model (1,1) string
end

[~, modelName, extension] = fileparts(model);
if extension == ""
    modelName = char(model);
else
    modelName = char(modelName);
end
if ~bdIsLoaded(modelName)
    load_system(model);
    cleanup = onCleanup(@() close_system(modelName, 0));
else
    cleanup = onCleanup(@() []);
end

build = RTW.getBuildDir(modelName);
elfFile = fullfile(fileparts(build.BuildDirectory), string(modelName) + ".elf");
reportFile = fullfile(build.BuildDirectory, 'x280_local_build.json');
if ~isfile(elfFile) && isfile(reportFile)
    report = jsondecode(fileread(reportFile));
    required = {'model', 'success', 'local_elf', 'elf_sha256', 'model_sha256'};
    assert(all(isfield(report, required)) && report.success && ...
        string(report.model) == string(modelName) && ...
        strcmp(get_param(modelName, 'Dirty'), 'off') && ...
        x280FileSHA256(string(get_param(modelName, 'FileName'))) == string(report.model_sha256), ...
        'x280linux:LocalBuildInvalid', 'Rebuild the model before exporting A2L for its published ELF.');
    elfFile = string(report.local_elf);
    if ~isfile(elfFile) && all(isfield(report, {'archive', 'archive_sha256'}))
        payload = unpackX280Artifacts(string(report.archive), ...
            fullfile(build.BuildDirectory, 'x280_archive_cache'), ...
            ExpectedSHA256=string(report.archive_sha256));
        elfFile = fullfile(payload, string(modelName) + '.elf');
    end
    assert(isfile(elfFile) && x280FileSHA256(elfFile) == string(report.elf_sha256), ...
        'x280linux:LocalBuildInvalid', 'The published ELF does not match the build report.');
end
if ~isfile(elfFile)
    error('x280linux:ELFNotReturned', ...
        ['No local %s.elf was found in the current code generation directory. Do not export ' ...
         'A2L against an unrelated executable.'], modelName);
end
clear cleanup;
end
