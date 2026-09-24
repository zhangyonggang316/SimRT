function bundle = prepareX280AppBundle(model, outputFolder)
%PREPAREX280APPBUNDLE Package generated single-task code for local compilation.
arguments
    model (1,1) string
    outputFolder (1,1) string
end
assert(~isfolder(outputFolder) && ~isfile(outputFolder), ...
    'x280linux:BundleExists', 'Choose a new bundle directory to avoid stale or mixed sources.');
buildDirectory = RTW.getBuildDir(model);
loaded = load(fullfile(buildDirectory.BuildDirectory, 'buildInfo.mat'), 'buildInfo');
original = loaded.buildInfo;
objects = getLinkObjects(original);
for index = 1:numel(objects)
    if ~strcmp(objects(index).Name, '$(LINUX_TARGET_LIBS_MACRO)')
        error('x280linux:ExternalLibrary', ...
            'Use the native target toolchain for external library %s.', objects(index).Name);
    end
end
% The native toolchain macro represents optional target libraries, not a local file.
% Reconstruct a packaging-only BuildInfo from its structured source/include metadata.
packing = RTW.BuildInfo;
sourcePaths = getSourceFiles(original, true, true);
sourceNames = cell(size(sourcePaths));
for index = 1:numel(sourcePaths)
    [~, name, extension] = fileparts(sourcePaths{index});
    sourceNames{index} = [name extension];
end
assert(numel(unique(lower(string(sourceNames)))) == numel(sourceNames), ...
    'x280linux:DuplicateSource', 'Flat packaging does not support duplicate source filenames.');
packing.addSourceFiles(sourcePaths);
packing.addIncludePaths(getIncludePaths(original, true));
packing.addDefines(getDefines(original));
if ~isfolder(outputFolder), mkdir(outputFolder); end
archive = fullfile(outputFolder, 'sources.zip');
packNGo(packing, 'fileName', archive, 'packType', 'flat', ...
    'minimalHeaders', true, 'ignoreFileMissing', false);
unzip(archive, fullfile(outputFolder, 'src'));
xcp = x280XCPConfiguration;
spec = struct('model', model, 'sources', {sourceNames}, ...
    'defines', {getDefines(original)}, 'matlab_release', version('-release'), ...
    'target', 'x86-64 Linux', 'xcp_transport', xcp.Transport, 'xcp_port', xcp.Port);
if any(strcmp(sourceNames, 'x280_rt_main.c'))
    spec.runtime = struct('name', 'x280_single_task_rt', ...
        'period_ns', int64(round(str2double(get_param(model, 'FixedStep')) * 1e9)), ...
        'tasking', 'single', 'kernel_required_default', true, 'optimization', 'O2', ...
        'main', 'x280_rt_main.c', 'xcp_background', true, ...
        'xcp_event_source', 'generated_model_step', 'daq_reserved_blocks', 64);
end
fid = fopen(fullfile(outputFolder, 'build_spec.json'), 'w', 'n', 'UTF-8');
assert(fid >= 0, 'Cannot create build_spec.json');
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, jsonencode(spec, PrettyPrint=true), 'char');
clear cleanup;
copyfile(fullfile(fileparts(mfilename('fullpath')), 'tools', 'build_model.py'), outputFolder);
bundle = struct('SourceDirectory', outputFolder, 'BuildCommand', ...
    'python build_model.py --toolchain-root <portable-linux-toolchain>', ...
    'ELFRelativePath', model + ".elf", 'CodeGenerationDirectory', string(buildDirectory.BuildDirectory));
end
