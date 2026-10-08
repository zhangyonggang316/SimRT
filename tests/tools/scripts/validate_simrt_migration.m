function validate_simrt_migration(options)
%VALIDATE_SIMRT_MIGRATION Register, verify links and rebuild the delivered models.
arguments
    options.BuildOnly (1,1) logical = false
end
root=fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
target=fullfile(root,'toolchain/simrt_linux_target');
out=fullfile(root,'tests/validation','simrt_migration_20261007');
if ~isfolder(out), mkdir(out); end
addpath(target,fullfile(root,'tests/tools/scripts'));
setupSimRTLinuxTarget;
installation=installSimRTARKLibrary;
library=check_ark_installation(ReportFolder=string(fullfile(out,'library')));
if ~options.BuildOnly
    results=runtests(fullfile(root,'tests','toolchain'),'IncludeSubfolders',false);
    testReport=struct('name',{results.Name},'passed',{results.Passed}, ...
        'failed',{results.Failed},'incomplete',{results.Incomplete});
    writeJSON(fullfile(out,'matlab_tests.json'),testReport);
    assertSuccess(results);
end
report=struct('installation',installation,'library',library,'builds',[],'passed',false);
models={fullfile(root,'demos/Demo_XCP_Qt','models','simrt_rt_single','simrt_rt_single.slx'), ...
    fullfile(root,'demos','io','tc1013','simrt_can_loopback','simrt_can_loopback.slx')};
for index=1:numel(models)
    cd(fileparts(models{index}));
    Simulink.fileGenControl('set','CacheFolder',fileparts(models{index}), ...
        'CodeGenFolder',fileparts(models{index}),'createDir',true);
    item=buildSimRTLocal(string(models{index}),Address="192.168.193.195");
    report.builds=[report.builds; item]; %#ok<AGROW>
    writeJSON(fullfile(out,'matlab_builds.json'),report);
end
report.passed=true;
writeJSON(fullfile(out,'matlab_builds.json'),report);
cd(root);
disp('SIMRT_MIGRATION_BUILD_PASSED');
end

function writeJSON(path,value)
stream=fopen(path,'w','n','UTF-8');
cleanup=onCleanup(@()fclose(stream)); %#ok<NASGU>
fprintf(stream,'%s\n',jsonencode(value,PrettyPrint=true));
end
