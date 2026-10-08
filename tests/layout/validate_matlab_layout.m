function report = validate_matlab_layout
%VALIDATE_MATLAB_LAYOUT Register moved sources and build without target hardware.
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
target = fullfile(root, 'toolchain', 'simrt_linux_target');
diary(fullfile(folder, 'matlab_validation.log'));
cleanupDiary = onCleanup(@() diary('off')); %#ok<NASGU>
addpath(target);
clear setupSimRTLinuxTarget simrtToolchainRoot tSimRTLinuxTarget tSimRTBuildWorkflow
rehash;
fprintf('Registering relocated SimRT target...\n');
setupSimRTLinuxTarget(Refresh=true, Persist=true);
report = struct('environment', verifySimRTEnvironment(Strict=true), 'remote_operations', false);
fprintf('Running relocated MATLAB regression tests...\n');
results = runLocalTests;
report.tests = numel(results);
report.tests_passed = all([results.Passed]);
setupSimRTLinuxTarget;
output = fullfile(folder, 'model');
file = createSimRTExampleModel(OutputFolder=output, ModelName="simrt_layout_probe", ...
    Address="192.168.193.195");
open_system(file);
cleanupModel = onCleanup(@() close_system('simrt_layout_probe', 0)); %#ok<NASGU>
oldFolder = cd(output);
cleanupFolder = onCleanup(@() cd(oldFolder)); %#ok<NASGU>
settings = Simulink.fileGenControl('getConfig');
cleanupSettings = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', settings)); %#ok<NASGU>
Simulink.fileGenControl('set', 'CacheFolder', output, 'CodeGenFolder', output, 'createDir', true);
fprintf('Building from the relocated compiler and runtime sources...\n');
report.build = buildSimRTLocal('simrt_layout_probe');
assert(report.build.success);
addpath(fullfile(root, 'tests', 'validation', 'ctrlb_20261007'));
report.hardware = inspectBuildUI('simrt_layout_probe');
assert(report.hardware.build_action_enabled);
assert(strcmp(get_param('simrt_layout_probe', 'Dirty'), 'off'));
writeReport(fullfile(folder, 'matlab_validation.json'), report);
end

function writeReport(file, value)
stream = fopen(file, 'w', 'n', 'UTF-8');
assert(stream >= 0);
cleanup = onCleanup(@() fclose(stream)); %#ok<NASGU>
fprintf(stream, '%s', jsonencode(value, PrettyPrint=true));
end
