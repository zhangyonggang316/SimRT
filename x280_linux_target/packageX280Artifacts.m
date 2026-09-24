function [archiveFile, archiveSHA256] = packageX280Artifacts(payload, options)
%PACKAGEX280ARTIFACTS Publish a verified ZIP and remove the expanded result.
arguments
    payload (1,1) string {mustBeFolder}
    options.RemoveSource (1,1) logical = true
end
payload = string(java.io.File(char(payload)).getCanonicalPath());
[parent, folderName] = fileparts(payload);
archiveFile = payload + ".zip";
assert(~isfile(archiveFile) && ~isfolder(archiveFile), ...
    'x280linux:ArchiveExists', 'Preserve the existing deployment ZIP: %s.', archiveFile);
files = validatePayload(payload);
temporaryArchive = string(tempname(parent)) + ".zip";
verification = string(tempname);
cleanup = onCleanup(@() removeTemporary(temporaryArchive, verification));
zip(temporaryArchive, cellstr(fullfile(folderName, files)), parent);
unzip(temporaryArchive, verification);
verifiedFolder = fullfile(verification, folderName);
assert(isequal(validatePayload(verifiedFolder), files), ...
    'x280linux:ArchiveInvalid', 'The deployment ZIP contains unexpected files.');
for index = 1:numel(files)
    assert(x280FileSHA256(fullfile(payload, files(index))) == ...
        x280FileSHA256(fullfile(verifiedFolder, files(index))), ...
        'x280linux:ArchiveInvalid', 'ZIP verification failed for %s.', files(index));
end
archiveSHA256 = x280FileSHA256(temporaryArchive);
[success, message] = movefile(temporaryArchive, archiveFile);
assert(success, 'x280linux:ArchivePublish', 'Cannot publish deployment ZIP: %s.', message);
if options.RemoveSource
    [success, message] = rmdir(payload, 's');
    assert(success, 'x280linux:ExpandedArtifactCleanup', ...
        'ZIP verified, but cannot remove its expanded result folder: %s.', message);
end
end

function files = validatePayload(payload)
entries = dir(payload);
entries = entries(~ismember({entries.name}, {'.', '..'}));
assert(numel(entries) == 3 && ~any([entries.isdir]), ...
    'x280linux:UnexpectedArtifacts', 'Deployment output must contain exactly ELF, A2L and manifest.');
files = sort(string({entries.name}));
manifestName = files(endsWith(files, '.xcp-manifest.json'));
assert(isscalar(manifestName), 'x280linux:UnexpectedArtifacts', 'Exactly one XCP manifest is required.');
manifest = jsondecode(fileread(fullfile(payload, manifestName)));
assert(isfield(manifest, 'ModelName') && ischar(manifest.ModelName) && ...
    ~isempty(regexp(manifest.ModelName, '^[A-Za-z][A-Za-z0-9_]*$', 'once')), ...
    'x280linux:InvalidManifest', 'The manifest must identify a valid model.');
model = string(manifest.ModelName);
expected = sort(model + [".elf", ".a2l", ".xcp-manifest.json"]);
assert(isequal(files, expected), 'x280linux:UnexpectedArtifacts', ...
    'The deployment files must all belong to model %s.', model);
assert(isfield(manifest, 'ELFFile') && isfield(manifest, 'A2LFile') && ...
    isfield(manifest, 'ELFSHA256') && isfield(manifest, 'A2LSHA256') && ...
    string(manifest.ELFFile) == model + ".elf" && ...
    string(manifest.A2LFile) == model + ".a2l" && ...
    x280FileSHA256(fullfile(payload, model + ".elf")) == string(manifest.ELFSHA256) && ...
    x280FileSHA256(fullfile(payload, model + ".a2l")) == string(manifest.A2LSHA256), ...
    'x280linux:ArtifactHashMismatch', 'The manifest does not match the deployment files.');
end

function removeTemporary(archiveFile, folder)
if isfile(archiveFile), delete(archiveFile); end
if isfolder(folder), rmdir(folder, 's'); end
end
