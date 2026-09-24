function results = runLocalTests
%RUNLOCALTESTS Run the offline X280 target regression tests.

targetRoot = fileparts(mfilename('fullpath'));
setupX280LinuxTarget;
results = runtests(fullfile(targetRoot, 'tests'), ...
    'IncludeSubfolders', true);
disp(table(results));
assertSuccess(results);
end
