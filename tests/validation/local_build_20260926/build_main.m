projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
evidenceRoot = fullfile(projectRoot, 'validation', 'local_build_20260926');
addpath(fullfile(projectRoot, 'simrt_linux_target'));
modelFolder = fullfile(projectRoot, 'Demo_XCP_Qt', 'models', 'simrt_rt_single');
modelFile = fullfile(modelFolder, 'simrt_rt_single.slx');
backupFile = fullfile(evidenceRoot, 'original_simrt_rt_single.slx');
if ~isfile(backupFile), copyfile(modelFile, backupFile); end
originalFolder = pwd;
folderCleanup = onCleanup(@() cd(originalFolder));
cd(modelFolder);
result = buildSimRTLocal(string(modelFile), Address='192.168.219.195');
file = fopen(fullfile(evidenceRoot, 'simrt_local_build.json'), 'w');
fileCleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(result, PrettyPrint=true));
disp(result);
