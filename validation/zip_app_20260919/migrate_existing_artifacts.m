function report = migrate_existing_artifacts
%MIGRATE_EXISTING_ARTIFACTS Package only the two explicitly selected model roots.
root = string(fileparts(fileparts(fileparts(mfilename('fullpath')))));
addpath(fullfile(root, 'x280_linux_target'));
modelRoots = [fullfile(root, 'Demo_XCP_Qt', 'models', 'x280_rt_single'), ...
    fullfile(root, 'x280_linux_target', 'drivers', 'tc1013', 'models', 'x280_can_loopback')];
report = struct('created_utc', string(datetime('now', 'TimeZone', 'UTC', ...
    'Format', "yyyy-MM-dd'T'HH:mm:ss'Z'")), 'success', false, ...
    'scope', modelRoots, 'models', struct([]));
report.models = cell(1, numel(modelRoots));
reportFile = fullfile(fileparts(mfilename('fullpath')), 'artifact_migration.json');
assert(~isfile(reportFile), 'x280linux:MigrationReportExists', 'Preserve the existing migration report.');
for modelIndex = 1:numel(modelRoots)
    modelRoot = modelRoots(modelIndex);
    [~, model] = fileparts(modelRoot);
    modelFile = fullfile(modelRoot, model + '.slx');
    originalModelHash = x280FileSHA256(modelFile);
    folders = dir(fullfile(modelRoot, model + '_local'));
    folders = folders([folders.isdir]);
    folders = folders(~cellfun(@isempty, regexp({folders.name}, '^\d{8}_\d{6}_\d{3}$', 'once')));
    assert(~isempty(folders), 'x280linux:MigrationNoPayloads', 'No timestamp payloads found for %s.', model);
    records = cell(1, numel(folders));
    for folderIndex = 1:numel(folders)
        folder = fullfile(folders(folderIndex).folder, folders(folderIndex).name);
        hashes = verifyPayload(string(folder), model);
        archive = string(folder) + '.zip';
        created = ~isfile(archive);
        if created, packageX280Artifacts(string(folder)); end
        verifyArchive(archive, folders(folderIndex).name, model, hashes);
        records{folderIndex} = struct('directory', string(folder), ...
            'archive', archive, 'archive_created', created, ...
            'archive_sha256', x280FileSHA256(archive), 'files', hashes, 'verified', true);
    end
    records = [records{:}];
    outerELF = fullfile(modelRoot, model + '.elf');
    outer = struct('path', outerELF, 'existed', isfile(outerELF), ...
        'sha256', "", 'matched_archive', "", 'removed', false);
    if outer.existed
        outer.sha256 = x280FileSHA256(outerELF);
        matching = find(arrayfun(@(item) item.files.elf_sha256 == outer.sha256, records), 1, 'last');
        assert(~isempty(matching), 'x280linux:OuterELFMismatch', ...
            'Preserve outer ELF because no verified published archive matches: %s.', outerELF);
        outer.matched_archive = records(matching).archive;
        % The path is exactly one named model's direct child, never a recursive deletion.
        delete(outerELF);
        assert(~isfile(outerELF), 'x280linux:OuterELFCleanup', 'Cannot remove redundant ELF: %s.', outerELF);
        outer.removed = true;
    end
    currentModelHash = x280FileSHA256(modelFile);
    assert(currentModelHash == originalModelHash, 'x280linux:ModelChanged', 'The model file changed during migration.');
    report.models{modelIndex} = struct('model', model, 'model_file', modelFile, ...
        'model_sha256_before', originalModelHash, 'model_sha256_after', currentModelHash, ...
        'artifacts', records, 'outer_elf', outer);
end
report.models = [report.models{:}];
report.success = true;
file = fopen(reportFile, 'w', 'n', 'UTF-8');
assert(file >= 0, 'Cannot write migration report.');
cleanup = onCleanup(@() fclose(file));
fwrite(file, jsonencode(report, PrettyPrint=true), 'char');
fprintf('Verified %d model roots. Report: %s\n', numel(report.models), reportFile);
end

function hashes = verifyPayload(folder, model)
entries = dir(folder);
entries = entries(~ismember({entries.name}, {'.', '..'}));
expected = sort(model + [".a2l", ".elf", ".xcp-manifest.json"]);
assert(numel(entries) == 3 && ~any([entries.isdir]) && ...
    isequal(sort(string({entries.name})), expected), ...
    'x280linux:UnexpectedArtifacts', 'Expected exactly three deployment files in %s.', folder);
manifest = jsondecode(fileread(fullfile(folder, model + '.xcp-manifest.json')));
hashes = struct('elf_sha256', x280FileSHA256(fullfile(folder, model + '.elf')), ...
    'a2l_sha256', x280FileSHA256(fullfile(folder, model + '.a2l')), ...
    'manifest_sha256', x280FileSHA256(fullfile(folder, model + '.xcp-manifest.json')));
assert(string(manifest.ModelName) == model && string(manifest.ELFFile) == (model + ".elf") && ...
    string(manifest.A2LFile) == (model + ".a2l") && ...
    string(manifest.ELFSHA256) == hashes.elf_sha256 && ...
    string(manifest.A2LSHA256) == hashes.a2l_sha256, ...
    'x280linux:ArtifactHashMismatch', 'Manifest does not match the deployment files: %s.', folder);
end

function verifyArchive(archive, folderName, model, hashes)
zipFile = java.util.zip.ZipFile(char(archive));
closeZip = onCleanup(@() zipFile.close());
entries = zipFile.entries();
files = strings(1, 0);
while entries.hasMoreElements()
    entry = entries.nextElement();
    name = string(entry.getName());
    if entry.isDirectory()
        assert(name == string(folderName) + '/', 'x280linux:ArchiveInvalid', 'Unexpected ZIP directory.');
    else
        files(end + 1) = name; %#ok<AGROW>
    end
end
expected = string(folderName) + '/' + model + [".a2l", ".elf", ".xcp-manifest.json"];
assert(isequal(sort(files), sort(expected)), 'x280linux:ArchiveInvalid', 'Unexpected deployment ZIP contents.');
clear closeZip;
temporary = string(tempname);
cleanup = onCleanup(@() removeTemporary(temporary));
unzip(archive, temporary);
extractedHashes = verifyPayload(fullfile(temporary, folderName), model);
assert(isequal(extractedHashes, hashes), 'x280linux:ArchiveInvalid', 'Archive contents do not match the original folder.');
end

function removeTemporary(folder)
if isfolder(folder), rmdir(folder, 's'); end
end
