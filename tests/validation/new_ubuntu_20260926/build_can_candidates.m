function build_can_candidates
% Build isolated CAN models against the validated SDK compatibility candidate.
evidence = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(evidence));
addpath(fullfile(root, 'simrt_linux_target'));
modelRoot = fullfile(evidence, 'can_models');
originalFolder = pwd;
restoreFolder = onCleanup(@() cd(originalFolder));
cd(modelRoot);
models = ["simrt_can_loopback", "simrt_canfd_loopback"];
results = cell(1, numel(models));
for index = 1:numel(models)
    modelFile = fullfile(modelRoot, models(index) + ".slx");
    buildFailure = [];
    buildOutput = evalc(['try; results{index} = buildSimRTLocal(modelFile, ' ...
        'Address="192.168.219.195"); catch buildFailure; ' ...
        'disp(getReport(buildFailure, "extended", "hyperlinks", "off")); end']);
    logFile = fullfile(evidence, models(index) + "_build_" + ...
        string(datetime('now', Format='yyyyMMdd_HHmmss')) + ".log");
    logStream = fopen(logFile, 'w', 'n', 'UTF-8');
    assert(logStream >= 0, 'Cannot open candidate build log.');
    fprintf(logStream, '%s', buildOutput);
    fclose(logStream);
    if ~isempty(buildFailure), rethrow(buildFailure); end
    reportFile = fullfile(evidence, models(index) + "_candidate_build.json");
    stream = fopen(reportFile, 'w', 'n', 'UTF-8');
    assert(stream >= 0, 'Cannot open candidate build report.');
    fcloseGuard = onCleanup(@() fclose(stream));
    fprintf(stream, '%s\n', jsonencode(results{index}, PrettyPrint=true));
    clear fcloseGuard;
    disp(results{index}.archive);
end
end
