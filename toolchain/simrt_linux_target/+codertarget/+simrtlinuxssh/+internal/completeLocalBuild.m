function result = completeLocalBuild(model)
%COMPLETELOCALBUILD Publish only a deployment ZIP; never open SSH.
build = RTW.getBuildDir(model);
elf = fullfile(fileparts(build.BuildDirectory), [model '.elf']);
assert(isfile(elf), 'simrtlinux:LocalELFMissing', 'Local linker did not produce %s.', elf);
buildId = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyyMMdd_HHmmss_SSS'));
output = fullfile(fileparts(build.BuildDirectory), [model '_local'], buildId);
evidence = fullfile(build.BuildDirectory, 'simrt_build_evidence', buildId);
assert(~isfolder(output) && ~isfile(output) && ~isfile([output '.zip']) && ~isfolder(evidence), ...
    'simrtlinux:BuildCollision', 'Build output already exists: %s', output);
mkdir(evidence);
data = get_param(model, 'CoderTargetData');
address = string(data.BoardParameters.DeviceAddress);
staging = fullfile(evidence, 'pending_payload');
exportSimRTA2L(model, MapFile=string(elf), ...
    OutputFolder=string(staging), TargetAddress=address);
expectedFiles = string(model) + [".elf", ".a2l", ".xcp-manifest.json"];
entries = dir(staging);
entries = entries(~ismember({entries.name}, {'.', '..'}));
assert(numel(entries) == 3 && ~any([entries.isdir]) && ...
    isequal(sort(string({entries.name})), sort(expectedFiles)), ...
    'simrtlinux:UnexpectedArtifacts', 'Final output must contain only ELF, A2L and manifest.');
payload = output;
elfFile = fullfile(payload, [model '.elf']);
a2lFile = fullfile(payload, [model '.a2l']);
manifestFile = fullfile(payload, [model '.xcp-manifest.json']);
source = fullfile(evidence, [model '_rt_bundle']);
bundle = prepareSimRTAppBundle(model, string(source));
copyfile(fullfile(build.BuildDirectory, 'ert_main.c'), fullfile(source, 'original_ert_main.c'));
copyfile(fullfile(matlabroot, 'toolbox', 'target', 'codertarget', 'rtos', 'src', ...
    'linuxinitialize.c'), fullfile(source, 'original_linuxinitialize.c'));
modelSnapshot = fullfile(evidence, [model '.slx']);
copyfile(get_param(model, 'FileName'), modelSnapshot);
toolchain = simrtToolchainRoot;
command = sprintf('"%s" --version', fullfile(toolchain, 'toolchain', 'bin', 'linux-gcc.exe'));
[status, compilerVersion] = system(command);
assert(status == 0, 'simrtlinux:CompilerIdentity', 'Cannot record compiler version.');
readelf = fullfile(toolchain, 'toolchain', 'bin', 'linux-readelf.exe');
[status, elfInspection] = system(sprintf('"%s" -h -l -d -V "%s"', readelf, elf));
assert(status == 0, 'simrtlinux:ELFInspection', 'Cannot inspect local ELF dependencies.');
fid = fopen(fullfile(evidence, 'elf_inspection.txt'), 'w', 'n', 'UTF-8');
assert(fid >= 0, 'simrtlinux:ELFInspectionWrite', 'Cannot retain ELF inspection.');
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, elfInspection, 'char');
clear cleanup;
copyfile(fullfile(build.BuildDirectory, [model '.mk']), evidence);
copyfile(fullfile(build.BuildDirectory, [model '.bat']), evidence);
result = struct('model', string(model), 'success', true, 'build_mode', "local", ...
    'period_seconds', str2double(get_param(model, 'FixedStep')), ...
    'matlab_release', string(version('-release')), 'toolchain_root', string(toolchain), ...
    'compiler_version', string(strtrim(compilerVersion)), ...
    'compiler_sha256', simrtFileSHA256(fullfile(toolchain, 'toolchain', 'bin', 'linux-gcc.exe')), ...
    'model_file', string(modelSnapshot), 'model_sha256', simrtFileSHA256(modelSnapshot), ...
    'local_elf', string(elfFile), 'a2l', string(a2lFile), 'manifest', string(manifestFile), ...
    'payload', string(payload), 'realtime_source', string(source), 'bundle', bundle, ...
    'elf_sha256', simrtFileSHA256(fullfile(staging, [model '.elf'])), ...
    'evidence_directory', string(evidence), 'remote_operations_performed', false);
runtime = struct('runtime_sha256', simrtFileSHA256(fullfile(source, 'src', 'simrt_rt_runtime.c')), ...
    'main_sha256', simrtFileSHA256(fullfile(source, 'src', 'simrt_rt_main.c')), ...
    'model_sources_unchanged', true, 'build_mode', "local", ...
    'generated_main_preserved_but_not_compiled', true);
writeReport(fullfile(source, 'realtime_manifest.json'), runtime);
% Publish only the validated deployment files after source/diagnostic capture succeeds.
if ~isfolder(fileparts(output)), mkdir(fileparts(output)); end
movefile(staging, output);
[result.archive, result.archive_sha256] = packageSimRTArtifacts(string(output));
cachedPayload = unpackSimRTArtifacts(result.archive, fullfile(evidence, 'deployment_cache'), ...
    ExpectedSHA256=result.archive_sha256);
result.payload = result.archive;
result.local_elf = fullfile(cachedPayload, [model '.elf']);
result.a2l = fullfile(cachedPayload, [model '.a2l']);
result.manifest = fullfile(cachedPayload, [model '.xcp-manifest.json']);
writeReport(fullfile(evidence, 'build_report.json'), result);
writeReport(fullfile(build.BuildDirectory, 'simrt_local_build.json'), result);
delete(elf);
assert(~isfile(elf), 'simrtlinux:OuterELFCleanup', 'Cannot remove redundant linker output: %s.', elf);
fprintf('### SimRT deployment ZIP: %s\n', result.archive);
end

function writeReport(fileName, result)
fid = fopen(fileName, 'w', 'n', 'UTF-8');
assert(fid >= 0, 'simrtlinux:BuildReportWrite', 'Cannot write %s', fileName);
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, jsonencode(result, PrettyPrint=true), 'char');
end
