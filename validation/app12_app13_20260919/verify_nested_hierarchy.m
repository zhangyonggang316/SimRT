function report = verify_nested_hierarchy()
%VERIFY_NESTED_HIERARCHY Build the isolated fixture and verify source groups.
evidence = fileparts(mfilename('fullpath'));
project = fileparts(fileparts(evidence));
addpath(fullfile(project, 'x280_linux_target'));
model = 'x280_hierarchy_test';
modelFile = fullfile(evidence, 'nested_model', [model '.slx']);
assert(~bdIsLoaded(model), 'Close this saved verification model before running.');
previous = Simulink.fileGenControl('getConfig');
configCleanup = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', previous));
Simulink.fileGenControl('set', 'CodeGenFolder', fullfile(evidence, 'nested_model'), ...
    'CacheFolder', fullfile(evidence, 'nested_model'), 'createDir', true);
diary(fullfile(evidence, 'nested_hierarchy_build.log'));
diaryCleanup = onCleanup(@() diary('off'));
result = buildX280Local(string(modelFile));
load_system(modelFile);
modelCleanup = onCleanup(@() close_system(model, 0));
descriptions = createX280ASAP2Hierarchy(string(model));
groupNames = string(descriptions.find('Group'));
groups = struct('name', {}, 'label', {}, 'root', {}, 'children', {}, 'measurements', {}, 'calibrations', {});
for index = 1:numel(groupNames)
    group = descriptions.get('Group', char(groupNames(index)));
    groups(end + 1) = struct('name', string(group.Name), 'label', string(group.LongIdentifier), ...
        'root', logical(group.Root), 'children', {cellstr(group.SubGroup)}, ...
        'measurements', {cellstr(group.RefMeasurement)}, 'calibrations', {cellstr(group.RefCharacteristic)}); %#ok<AGROW>
end
expectedPath = {model, 'Outer_Control', 'Inner_Controller'};
expectedMeasurement = [model '_B.DeepSignal'];
expectedCalibration = [model '_P.DeepGain_Gain'];
actual = groups([groups.label] == "Inner_Controller");
assert(isscalar(actual) && ismember(expectedMeasurement, actual.measurements), ...
    'Nested measurement is not in the expected model group.');
assert(ismember(expectedCalibration, actual.calibrations), ...
    'Nested block calibration is not in the expected model group.');
outer = groups([groups.label] == "Outer_Control");
root = groups([groups.root]);
assert(isscalar(outer) && isscalar(root) && ismember(char(actual.name), outer.children) && ...
    ismember(char(outer.name), root.children), 'Nested groups do not reflect source parent relationships.');
gainPath = Simulink.ID.getFullName([model ':17']);
sourceParent = get_param(gainPath, 'Parent');
assert(strcmp(sourceParent, strjoin(expectedPath, '/')), 'The model fixture parent path changed.');
report = struct('passed', true, 'model', modelFile, 'model_sha256', x280FileSHA256(string(modelFile)), ...
    'source_parent', sourceParent, 'expected_path', {expectedPath}, ...
    'measurement', expectedMeasurement, 'calibration', expectedCalibration, ...
    'groups', groups, 'archive', result.archive, 'archive_sha256', result.archive_sha256, ...
    'a2l', result.a2l, 'manifest', result.manifest, 'local_elf', result.local_elf, ...
    'remote_operations_performed', result.remote_operations_performed);
output = fopen(fullfile(evidence, 'nested_hierarchy_matlab.json'), 'w', 'n', 'UTF-8');
assert(output >= 0);
fileCleanup = onCleanup(@() fclose(output));
fwrite(output, jsonencode(report, PrettyPrint=true), 'char');
clear fileCleanup modelCleanup diaryCleanup configCleanup;
end
