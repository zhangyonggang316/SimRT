root = 'D:/05SimRT';
output = fullfile(root, 'validation', 'xcp_ports_20261005');
addpath(fullfile(root, 'simrt_linux_target'));
suite = matlab.unittest.TestSuite.fromFile( ...
    fullfile(root, 'simrt_linux_target', 'tests', 'tSimRTCANLoopback.m'));
runner = matlab.unittest.TestRunner.withTextOutput;
runner.addPlugin(matlab.unittest.plugins.XMLPlugin.producingJUnitFormat( ...
    fullfile(output, 'matlab_can_retest.xml')));
results = runner.run(suite);
fid = fopen(fullfile(output, 'matlab_can_retest.json'), 'w');
fprintf(fid, '%s', jsonencode(table2struct(table(results)), PrettyPrint=true));
fclose(fid);
disp(table(results));
assertSuccess(results);
