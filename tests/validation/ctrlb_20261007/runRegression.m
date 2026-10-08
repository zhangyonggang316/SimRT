function runRegression
%RUNREGRESSION Check target registration and retain concise local evidence.
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
diary(fullfile(folder, 'target_tests.log'));
cleanup = onCleanup(@() diary('off'));
results = runtests(fullfile(root, 'simrt_linux_target', 'tests', 'tSimRTLinuxTarget.m'));
disp(table(results));
report = struct('names', {results.Name}, 'passed', num2cell([results.Passed]), ...
    'failed', num2cell([results.Failed]), 'incomplete', num2cell([results.Incomplete]));
file = fopen(fullfile(folder, 'target_tests.json'), 'w', 'n', 'UTF-8');
fileCleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
assert(all([results.Passed]), 'SimRT target regression failed.');
end
