function results = runLocalTests
%RUNLOCALTESTS Run the offline SimRT target regression tests.

setupSimRTLinuxTarget;
results = runtests(fullfile(simrtProjectRoot, 'tests', 'toolchain'), ...
    'IncludeSubfolders', true);
disp(table(results));
assertSuccess(results);
end
