workspace = 'D:/05SimRT';
output = fullfile(workspace, 'validation', 'xcp_ports_20261005');
assert(strcmp(version('-release'), '2024b'));
addpath(fullfile(workspace, 'simrt_linux_target'));
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
