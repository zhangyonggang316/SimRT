root = 'D:/05SimRT';
output = fullfile(root, 'validation', 'realtime_20261006');
assert(strcmp(version('-release'), '2024b'));
addpath(fullfile(root, 'simrt_linux_target'));
setupSimRTLinuxTarget;
model = fullfile(root, 'Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single.slx');
if ~isfile(fullfile(output, 'model_before_build.slx'))
    copyfile(model, fullfile(output, 'model_before_build.slx'));
end
original = pwd;
cleanup = onCleanup(@() cd(original));
cd(fileparts(model));
receipt = buildSimRTLocal(model, Address="192.168.193.195");
fid = fopen(fullfile(output, 'model_build.json'), 'w');
fprintf(fid, '%s', jsonencode(receipt, PrettyPrint=true));
fclose(fid);
fprintf('BUILD_VERIFIED: %s\n', receipt.archive);
