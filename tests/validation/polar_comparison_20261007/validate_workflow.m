function report = validate_workflow(options)
%VALIDATE_WORKFLOW Isolated model build; no SSH or target hardware operations.
arguments
    options.RunTests (1,1) logical = true
end
folder = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(folder));
addpath(fullfile(root, 'simrt_linux_target'));
diary(fullfile(folder, 'matlab_validation.log'));
cleanupDiary = onCleanup(@() diary('off')); %#ok<NASGU>
clear configureSimRTModel buildSimRTLocal setupSimRTLinuxTarget setupSimRTARKLibrary
clear simrtToolchainRoot inspectSimRTToolchain verifySimRTEnvironment validateSimRTRealtimeModel
rehash;
if options.RunTests
    results = runtests({fullfile(root, 'simrt_linux_target', 'tests', 'tSimRTBuildWorkflow.m'), ...
        fullfile(root, 'simrt_linux_target', 'tests', 'tSimRTLinuxTarget.m')});
    report = struct('tests_passed', all([results.Passed]), 'tests_count', numel(results), ...
        'tests', {arrayfun(@(item) struct('name', item.Name, 'passed', item.Passed, ...
            'failed', item.Failed, 'incomplete', item.Incomplete), results)}, 'remote_operations', false);
else
    previousTests = jsondecode(fileread(fullfile(folder, 'matlab_validation.json')));
    report = struct('tests_passed', previousTests.tests_passed, 'tests_count', previousTests.tests_count, ...
        'tests', previousTests.tests, 'remote_operations', false);
end
writeReport(folder, report);
assert(report.tests_passed, 'SimRT regression tests failed.');
setupSimRTLinuxTarget;
report.environment = verifySimRTEnvironment(Strict=true);
output = fullfile(folder, ['model_' datestr(now, 'yyyymmdd_HHMMSS')]);
model = 'simrt_workflow_probe';
modelFile = createSimRTExampleModel(OutputFolder=output, ModelName=model, Address="192.168.193.195");
open_system(modelFile);
cleanupModel = onCleanup(@() close_system(model, 0)); %#ok<NASGU>
previous = cd(output);
cleanupFolder = onCleanup(@() cd(previous)); %#ok<NASGU>
settings = Simulink.fileGenControl('getConfig');
cleanupSettings = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', settings)); %#ok<NASGU>
Simulink.fileGenControl('set', 'CacheFolder', output, 'CodeGenFolder', output, 'createDir', true);
set_param(model, 'FixedStep', '0.005');
set_param([model '/Excitation'], 'SampleTime', '0.005');
save_system(model);
try
    slbuild(model);
    error('simrt:validation:ExpectedRejection', 'Invalid period unexpectedly built.');
catch exception
    assert(~strcmp(exception.identifier, 'simrt:validation:ExpectedRejection'));
    message = getReport(exception, 'extended', 'hyperlinks', 'off');
    assert(contains(message, 'FixedStep must be the literal'), message);
    report.invalid_period_rejected = true;
    report.invalid_period_message = message;
end
assert(~isfile(fullfile(output, [model '_ert_rtw'], [model '.c'])));
report.rejected_before_generated_c = true;
writeReport(folder, report);
set_param(model, 'FixedStep', '0.001');
set_param([model '/Excitation'], 'SampleTime', '0.001');
save_system(model);
report.build = buildSimRTLocal(model);
data = get_param(model, 'CoderTargetData');
assert(strcmp(data.BoardParameters.DeviceAddress, '192.168.193.195'));
a2l = fileread(report.build.a2l);
assert(contains(a2l, '192.168.193.195'));
report.address_preserved_in_model_and_a2l = true;
spec = jsondecode(fileread(fullfile(report.build.realtime_source, 'build_spec.json')));
assert(spec.runtime.daq_reserved_blocks == 1024);
assert(any(strcmp(spec.defines, '-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=1024')));
report.daq_pool_matches_compilation = true;
addpath(fullfile(root, 'validation', 'ctrlb_20261007'));
report.hardware = inspectBuildUI(model);
assert(report.hardware.build_action_enabled);
writeReport(folder, report);
end

function writeReport(folder, report)
file = fopen(fullfile(folder, 'matlab_validation.json'), 'w', 'n', 'UTF-8');
cleanup = onCleanup(@() fclose(file)); %#ok<NASGU>
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
end
