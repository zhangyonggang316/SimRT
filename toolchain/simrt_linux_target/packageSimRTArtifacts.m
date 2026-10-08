function [archiveFile, archiveSHA256] = packageSimRTArtifacts(payload, options)
%PACKAGESIMRTARTIFACTS Publish a verified ZIP and remove the expanded result.
arguments
    payload (1,1) string {mustBeFolder}
    options.RemoveSource (1,1) logical = true
end
payload = string(java.io.File(char(payload)).getCanonicalPath());
[parent, folderName] = fileparts(payload);
archiveFile = payload + ".zip";
assert(~isfile(archiveFile) && ~isfolder(archiveFile), ...
    'simrtlinux:ArchiveExists', 'Preserve the existing deployment ZIP: %s.', archiveFile);
files = validatePayload(payload);
temporaryArchive = string(tempname(parent)) + ".zip";
verification = string(tempname);
cleanup = onCleanup(@() removeTemporary(temporaryArchive, verification));
zip(temporaryArchive, cellstr(fullfile(folderName, files)), parent);
unzip(temporaryArchive, verification);
verifiedFolder = fullfile(verification, folderName);
assert(isequal(validatePayload(verifiedFolder), files), ...
    'simrtlinux:ArchiveInvalid', 'The deployment ZIP contains unexpected files.');
for index = 1:numel(files)
    assert(simrtFileSHA256(fullfile(payload, files(index))) == ...
        simrtFileSHA256(fullfile(verifiedFolder, files(index))), ...
        'simrtlinux:ArchiveInvalid', 'ZIP verification failed for %s.', files(index));
end
archiveSHA256 = simrtFileSHA256(temporaryArchive);
[success, message] = movefile(temporaryArchive, archiveFile);
assert(success, 'simrtlinux:ArchivePublish', 'Cannot publish deployment ZIP: %s.', message);
if options.RemoveSource
    [success, message] = rmdir(payload, 's');
    assert(success, 'simrtlinux:ExpandedArtifactCleanup', ...
        'ZIP verified, but cannot remove its expanded result folder: %s.', message);
end
end

function files = validatePayload(payload)
entries = dir(payload);
entries = entries(~ismember({entries.name}, {'.', '..'}));
assert(numel(entries) == 3 && ~any([entries.isdir]), ...
    'simrtlinux:UnexpectedArtifacts', 'Deployment output must contain exactly ELF, A2L and manifest.');
files = sort(string({entries.name}));
manifestName = files(endsWith(files, '.xcp-manifest.json'));
assert(isscalar(manifestName), 'simrtlinux:UnexpectedArtifacts', 'Exactly one XCP manifest is required.');
manifest = jsondecode(fileread(fullfile(payload, manifestName)));
assert(isfield(manifest, 'ModelName') && ischar(manifest.ModelName) && ...
    ~isempty(regexp(manifest.ModelName, '^[A-Za-z][A-Za-z0-9_]*$', 'once')), ...
    'simrtlinux:InvalidManifest', 'The manifest must identify a valid model.');
model = string(manifest.ModelName);
expected = sort(model + [".elf", ".a2l", ".xcp-manifest.json"]);
assert(isequal(files, expected), 'simrtlinux:UnexpectedArtifacts', ...
    'The deployment files must all belong to model %s.', model);
assert(isfield(manifest, 'ELFFile') && isfield(manifest, 'A2LFile') && ...
    isfield(manifest, 'ELFSHA256') && isfield(manifest, 'A2LSHA256') && ...
    string(manifest.ELFFile) == model + ".elf" && ...
    string(manifest.A2LFile) == model + ".a2l" && ...
    simrtFileSHA256(fullfile(payload, model + ".elf")) == string(manifest.ELFSHA256) && ...
    simrtFileSHA256(fullfile(payload, model + ".a2l")) == string(manifest.A2LSHA256), ...
    'simrtlinux:ArtifactHashMismatch', 'The manifest does not match the deployment files.');
end

function removeTemporary(archiveFile, folder)
if isfile(archiveFile), delete(archiveFile); end
if isfolder(folder), rmdir(folder, 's'); end
end
