projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(projectRoot, 'simrt_linux_target'));
results = runtests(fullfile(projectRoot, 'simrt_linux_target', 'tests', 'tSimRTLinuxTarget.m'));
disp(table(results));
save(fullfile(projectRoot, 'validation', 'local_build_20260926', 'target_tests.mat'), 'results');
assertSuccess(results);
