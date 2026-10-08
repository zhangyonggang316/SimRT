function result = buildSimRTLocal(model, options)
%BUILDSIMRTLOCAL Generate C, cross compile and package ELF/A2L without SSH.
arguments
    model (1,1) string
    options.Address (1,1) string = ""
    options.ArtifactDirectory (1,1) string = ""
end
[~, modelName] = fileparts(model);
loadedHere = ~bdIsLoaded(modelName);
if loadedHere, open_system(model); end
cleanup = onCleanup(@() closeOwnedModel(modelName, loadedHere));
assert(strcmp(get_param(modelName, 'Dirty'), 'off'), ...
    'simrtlinux:UnsavedModel', 'Save pending model edits before a reproducible build.');
if isfile(model)
    assert(strcmpi(char(java.io.File(char(model)).getCanonicalPath()), ...
        char(java.io.File(get_param(modelName, 'FileName')).getCanonicalPath())), ...
        'simrtlinux:ModelNameConflict', 'Another model with the same name is open.');
end
configureSimRTModel(modelName, Address=options.Address, Save=true);
slbuild(modelName);
build = RTW.getBuildDir(modelName);
result = jsondecode(fileread(fullfile(build.BuildDirectory, 'simrt_local_build.json')));
assert(result.success && simrtFileSHA256(string(result.local_elf)) == string(result.elf_sha256), ...
    'simrtlinux:LocalBuildInvalid', 'The local build report does not match its ELF.');
assert(isfield(result, 'archive') && isfield(result, 'archive_sha256') && ...
    simrtFileSHA256(string(result.archive)) == string(result.archive_sha256), ...
    'simrtlinux:LocalArchiveInvalid', 'The local build report does not match its deployment ZIP.');
if options.ArtifactDirectory ~= ""
    assert(~isfolder(options.ArtifactDirectory) && ~isfile(options.ArtifactDirectory) && ...
        ~isfile(options.ArtifactDirectory + ".zip") && ~isfolder(options.ArtifactDirectory + ".zip"), ...
        'simrtlinux:ArtifactDirectoryExists', 'Choose a new artifact directory.');
    cachedPayload = unpackSimRTArtifacts(string(result.archive), ...
        fullfile(build.BuildDirectory, 'simrt_archive_cache'), ...
        ExpectedSHA256=string(result.archive_sha256));
    copyfile(cachedPayload, options.ArtifactDirectory);
    [result.archive, result.archive_sha256] = packageSimRTArtifacts(options.ArtifactDirectory);
    result.payload = result.archive;
end
end

function closeOwnedModel(model, loadedHere)
if loadedHere && bdIsLoaded(model), close_system(model, 0); end
end
