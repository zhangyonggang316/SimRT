workspace = 'D:/05SimRT';
output = fullfile(workspace, 'validation', 'xcp_ports_20261005');
assert(strcmp(version('-release'), '2024b'));
addpath(fullfile(workspace, 'simrt_linux_target'));
setupSimRTLinuxTarget;
suite = matlab.unittest.TestSuite.fromFolder( ...
    fullfile(workspace, 'simrt_linux_target', 'tests'), IncludingSubfolders=true);
runner = matlab.unittest.TestRunner.withTextOutput;
runner.addPlugin(matlab.unittest.plugins.XMLPlugin.producingJUnitFormat( ...
    fullfile(output, 'matlab_tests.xml')));
results = runner.run(suite);
records = table2struct(table(results));
fid = fopen(fullfile(output, 'matlab_tests.json'), 'w');
fprintf(fid, '%s', jsonencode(records, PrettyPrint=true));
fclose(fid);
disp(table(results));
assertSuccess(results);

model = fullfile(workspace, 'Demo_XCP_Qt', 'models', ...
    'simrt_rt_single', 'simrt_rt_single.slx');
copyfile(model, fullfile(output, 'simrt_rt_single_before_build.slx'));
cd(fileparts(model));
receipt = buildSimRTLocal(model, Address="192.168.193.195");
manifest = jsondecode(fileread(receipt.manifest));
assert(strcmp(manifest.XCPTransport, 'UDP') && manifest.XCPPort == 55555);
assert(~receipt.remote_operations_performed);
fid = fopen(fullfile(output, 'model_build.json'), 'w');
fprintf(fid, '%s', jsonencode(receipt, PrettyPrint=true));
fclose(fid);
fprintf('PORT_MIGRATION_BUILD_PASSED: %s\n', receipt.archive);
