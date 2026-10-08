function report = validate_registration_cache
%VALIDATE_REGISTRATION_CACHE Verify the final registration optimization.
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
addpath(fullfile(root, 'simrt_linux_target'));
clear setupSimRTLinuxTarget tSimRTBuildWorkflow
rehash;
tic;
target = setupSimRTLinuxTarget(Refresh=true);
report.forced_refresh_seconds = toc;
file = fullfile(target, 'registry', 'simrt_portable_toolchain.mat');
before = dir(file);
hash = simrtFileSHA256(file);
tic;
setupSimRTLinuxTarget;
report.reuse_seconds = toc;
after = dir(file);
report.registration_unchanged = before.datenum == after.datenum && hash == simrtFileSHA256(file);
assert(report.registration_unchanged);
results = runtests(fullfile(target, 'tests', 'tSimRTBuildWorkflow.m'), ...
    'Name', '*unchangedRegistrationIsNotRewritten');
assert(numel(results) == 1 && results.Passed);
report.cache_regression_passed = true;
report.toolchain = inspectSimRTToolchain(Strict=true);
addpath(fullfile(root, 'validation', 'ctrlb_20261007'));
model = 'simrt_rt_single';
if bdIsLoaded(model)
    report.hardware = inspectBuildUI(model);
    assert(report.hardware.build_action_enabled);
end
stream = fopen(fullfile(folder, 'registration_cache.json'), 'w', 'n', 'UTF-8');
cleanup = onCleanup(@() fclose(stream)); %#ok<NASGU>
fprintf(stream, '%s\n', jsonencode(report, PrettyPrint=true));
disp(report);
end
