function result = buildX280Local(model, options)
%BUILDX280LOCAL Generate C, cross compile and package ELF/A2L without SSH.
arguments
    model (1,1) string
    options.Address (1,1) string = "192.168.219.86"
    options.ArtifactDirectory (1,1) string = ""
end
setupX280LinuxTarget;
[~, modelName] = fileparts(model);
loadedHere = ~bdIsLoaded(modelName);
if loadedHere, open_system(model); end
cleanup = onCleanup(@() closeOwnedModel(modelName, loadedHere));
assert(strcmp(get_param(modelName, 'Dirty'), 'off'), ...
    'x280linux:UnsavedModel', 'Save pending model edits before a reproducible build.');
if isfile(model)
    assert(strcmpi(char(java.io.File(char(model)).getCanonicalPath()), ...
        char(java.io.File(get_param(modelName, 'FileName')).getCanonicalPath())), ...
        'x280linux:ModelNameConflict', 'Another model with the same name is open.');
end
configureX280Model(modelName, Address=options.Address, Save=true);
slbuild(modelName);
build = RTW.getBuildDir(modelName);
result = jsondecode(fileread(fullfile(build.BuildDirectory, 'x280_local_build.json')));
assert(result.success && x280FileSHA256(string(result.local_elf)) == string(result.elf_sha256), ...
    'x280linux:LocalBuildInvalid', 'The local build report does not match its ELF.');
assert(isfield(result, 'archive') && isfield(result, 'archive_sha256') && ...
    x280FileSHA256(string(result.archive)) == string(result.archive_sha256), ...
    'x280linux:LocalArchiveInvalid', 'The local build report does not match its deployment ZIP.');
if options.ArtifactDirectory ~= ""
    assert(~isfolder(options.ArtifactDirectory) && ~isfile(options.ArtifactDirectory) && ...
        ~isfile(options.ArtifactDirectory + ".zip") && ~isfolder(options.ArtifactDirectory + ".zip"), ...
        'x280linux:ArtifactDirectoryExists', 'Choose a new artifact directory.');
    cachedPayload = unpackX280Artifacts(string(result.archive), ...
        fullfile(build.BuildDirectory, 'x280_archive_cache'), ...
        ExpectedSHA256=string(result.archive_sha256));
    copyfile(cachedPayload, options.ArtifactDirectory);
    [result.archive, result.archive_sha256] = packageX280Artifacts(options.ArtifactDirectory);
    result.payload = result.archive;
end
end

function closeOwnedModel(model, loadedHere)
if loadedHere && bdIsLoaded(model), close_system(model, 0); end
end
