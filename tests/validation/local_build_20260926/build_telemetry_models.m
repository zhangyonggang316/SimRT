projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
evidenceRoot = fullfile(projectRoot, 'validation', 'local_build_20260926');
addpath(fullfile(projectRoot, 'simrt_linux_target'));
setupSimRTCANLibrary;
sources = {
    fullfile(projectRoot, 'Demo_XCP_Qt', 'models', 'simrt_rt_single', 'simrt_rt_single.slx');
    fullfile(projectRoot, 'simrt_linux_target', 'drivers', 'tc1013', 'models', 'simrt_can_loopback', 'simrt_can_loopback.slx');
    fullfile(projectRoot, 'validation', 'tc1013_can_20260919', 'simrt_canfd_loopback.slx')};
labels = {'main', 'can', 'canfd'};
originalFolder = pwd;
folderCleanup = onCleanup(@() cd(originalFolder));
for index = 1:numel(sources)
    receipt = fullfile(evidenceRoot, [labels{index} '_telemetry_build.json']);
    if isfile(receipt)
        previous = jsondecode(fileread(receipt));
        if string(previous.runtime_sha256) == simrtFileSHA256(fullfile(projectRoot, 'simrt_linux_target', 'src', 'simrt_rt_runtime.c')) && ...
                simrtFileSHA256(previous.archive) == string(previous.archive_sha256)
            fprintf('Retaining verified current build: %s\n', previous.archive);
            continue;
        end
    end
    [~, model] = fileparts(sources{index});
    if index == 1
        modelFile = sources{index};
    else
        destination = fullfile(projectRoot, 'validation', 'can926');
        if ~isfolder(destination), mkdir(destination); end
        modelFile = fullfile(destination, [model '.slx']);
        if ~isfile(modelFile), copyfile(sources{index}, modelFile); end
    end
    cd(fileparts(modelFile));
    result = buildSimRTLocal(string(modelFile), Address='192.168.219.195');
    runtimeFile = fullfile(result.realtime_source, 'src', 'simrt_rt_runtime.c');
    assert(simrtFileSHA256(runtimeFile) == simrtFileSHA256(fullfile(projectRoot, 'simrt_linux_target', 'src', 'simrt_rt_runtime.c')));
    assert(contains(fileread(fullfile(fileparts(fileparts(result.evidence_directory)), 'simrt_rt_main.c')), 'simrt_rt_set_stop_time'));
    result.runtime_sha256 = simrtFileSHA256(runtimeFile);
    file = fopen(receipt, 'w');
    fileCleanup = onCleanup(@() fclose(file));
    fprintf(file, '%s\n', jsonencode(result, PrettyPrint=true));
    clear fileCleanup;
    disp(result);
end
