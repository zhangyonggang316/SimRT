function report = restore_matlab_session
%RESTORE_MATLAB_SESSION Reopen the previously clean documents at their new paths.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
target = fullfile(root, 'toolchain', 'simrt_linux_target');
addpath(target);
setupSimRTLinuxTarget(Persist=true);
files = {fullfile(target,'drivers','serial','simrt_serial_library.slx'), ...
    fullfile(target,'drivers','dio','simrt_dio_library.slx'), ...
    fullfile(root,'demos','Demo_XCP_Qt','models','simrt_rt_single','simrt_rt_single.slx')};
for index = 1:numel(files)
    open_system(files{index});
end
cd(fullfile(root,'demos','io','dio','simrt_dio_loopback'));
report = struct('restored_models',{files},'folder',pwd, ...
    'registration',which('setupSimRTLinuxTarget'),'library',which('simrt_library'));
stream = fopen(fullfile(root,'tests','layout','matlab_restored.json'),'w','n','UTF-8');
cleanup = onCleanup(@()fclose(stream)); %#ok<NASGU>
fprintf(stream,'%s',jsonencode(report,PrettyPrint=true));
end
