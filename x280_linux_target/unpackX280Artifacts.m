function payload = unpackX280Artifacts(archiveFile, cacheRoot, options)
%UNPACKX280ARTIFACTS Resolve a verified archive into an internal build cache.
arguments
    archiveFile (1,1) string {mustBeFile}
    cacheRoot (1,1) string
    options.ExpectedSHA256 (1,1) string = ""
end
hash = x280FileSHA256(archiveFile);
assert(options.ExpectedSHA256 == "" || hash == options.ExpectedSHA256, ...
    'x280linux:ArchiveHashMismatch', 'The deployment ZIP differs from the build report.');
archive = java.util.zip.ZipFile(char(archiveFile));
cleanup = onCleanup(@() archive.close());
entries = archive.entries();
names = strings(0, 1);
folders = strings(0, 1);
expandedBytes = 0;
while entries.hasMoreElements()
    entry = entries.nextElement();
    name = string(entry.getName());
    assert(~entry.isDirectory() && ...
        ~isempty(regexp(name, '^[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z][A-Za-z0-9_.-]*$', 'once')), ...
        'x280linux:ArchiveInvalid', 'The ZIP must contain three direct files in one result folder.');
    parts = split(name, '/');
    assert(~any(parts == "." | parts == "..") && ~any(strcmpi(names, name)), ...
        'x280linux:ArchiveInvalid', 'The ZIP contains an invalid or repeated path.');
    names(end + 1, 1) = name; %#ok<AGROW>
    folders(end + 1, 1) = parts(1); %#ok<AGROW>
    expandedBytes = expandedBytes + double(entry.getSize());
    assert(numel(names) <= 3 && entry.getSize() >= 0 && expandedBytes <= 1024^3, ...
        'x280linux:ArchiveInvalid', 'The ZIP exceeds deployment package limits.');
end
assert(numel(names) == 3 && isscalar(unique(folders)), ...
    'x280linux:ArchiveInvalid', 'The ZIP must contain exactly three deployment files.');
clear cleanup;
cache = fullfile(cacheRoot, hash);
payload = fullfile(cache, folders(1));
if ~isfolder(payload)
    if ~isfolder(cacheRoot), mkdir(cacheRoot); end
    staging = string(tempname(cacheRoot));
    stagingCleanup = onCleanup(@() removeStaging(staging));
    unzip(archiveFile, staging);
    validateFiles(fullfile(staging, folders(1)));
    assert(~isfolder(cache), 'x280linux:ArchiveCacheInvalid', 'Unexpected archive cache directory.');
    movefile(staging, cache);
end
validateFiles(payload);
end

function validateFiles(payload)
entries = dir(payload);
entries = entries(~ismember({entries.name}, {'.', '..'}));
names = sort(string({entries.name}));
manifestName = names(endsWith(names, '.xcp-manifest.json'));
assert(numel(entries) == 3 && ~any([entries.isdir]) && isscalar(manifestName), ...
    'x280linux:ArchiveInvalid', 'Unexpected files in the deployment archive.');
manifest = jsondecode(fileread(fullfile(payload, manifestName)));
required = {'ModelName', 'ELFFile', 'A2LFile', 'ELFSHA256', 'A2LSHA256'};
assert(all(isfield(manifest, required)) && ischar(manifest.ModelName) && ...
    ~isempty(regexp(manifest.ModelName, '^[A-Za-z][A-Za-z0-9_]*$', 'once')), ...
    'x280linux:ArchiveInvalid', 'The archive manifest is invalid.');
model = string(manifest.ModelName);
assert(isequal(names, sort(model + [".elf", ".a2l", ".xcp-manifest.json"])) && ...
    string(manifest.ELFFile) == model + ".elf" && string(manifest.A2LFile) == model + ".a2l" && ...
    x280FileSHA256(fullfile(payload, model + ".elf")) == string(manifest.ELFSHA256) && ...
    x280FileSHA256(fullfile(payload, model + ".a2l")) == string(manifest.A2LSHA256), ...
    'x280linux:ArtifactHashMismatch', 'The ZIP manifest does not match its deployment files.');
end

function removeStaging(folder)
if isfolder(folder), rmdir(folder, 's'); end
end
