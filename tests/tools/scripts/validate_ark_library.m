function validate_ark_library
%VALIDATE_ARK_LIBRARY Install and build a hardware-inert ARK integration model.
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
target = fullfile(root,'toolchain/simrt_linux_target');
reportRoot = fullfile(root,'tests/validation','ark_io_20261005');
if ~isfolder(reportRoot), mkdir(reportRoot); end
addpath(target,fullfile(target,'drivers','dio'),fullfile(target,'drivers','ark'));
buildSimRTDIOLibrary;
buildSimRTARKLibrary;
installation=installSimRTARKLibrary;
report = struct('release',version('-release'),'version',version, ...
    'library',which('simrt_ark_library'),'physical_io_test',false, ...
    'installation',installation,'passed',false);
results = runtests({fullfile(root,'tests','drivers','dio','testDIO.m'), ...
    fullfile(root,'tests','drivers','serial','testSerialEtherCAT.m')});
report.tests = struct('name',{results.Name},'passed',{results.Passed}, ...
    'failed',{results.Failed},'incomplete',{results.Incomplete});
assertSuccess(results);
settings=Simulink.fileGenControl('getConfig');
settingsCleanup=onCleanup(@()Simulink.fileGenControl('setConfig','config',settings)); %#ok<NASGU>
Simulink.fileGenControl('set','CacheFolder',reportRoot,'CodeGenFolder',reportRoot,'createDir',true);
name = 'ark_io_codegen_check';
modelFile = fullfile(reportRoot,[name '.slx']);
assert(~bdIsLoaded(name),'simrt:ark:TestModelLoaded','Close the test model before testing.');
new_system(name);
cleanup = onCleanup(@()close_system(name,0)); %#ok<NASGU>
set_param(name,'SolverType','Fixed-step','Solver','FixedStepDiscrete', ...
    'FixedStep','0.001','StopTime','0.005','EnableMultiTasking','off', ...
    'SaveOutput','on','OutputSaveName','yout','SaveFormat','Dataset','ReturnWorkspaceOutputs','on');
library = 'simrt_ark_library';
add_block([library '/Serial Setup'],[name '/Serial Setup'], ...
    'Device','/dev/simrt-validation-no-serial','Position',[50 60 210 150]);
add_block([library '/Serial Sent'],[name '/Serial Sent'],'Position',[490 40 640 155]);
add_block([library '/Serial Receive'],[name '/Serial Receive'], ...
    'BufferSize','16','Position',[490 200 640 295]);
add_block([library '/DIO Setup'],[name '/DIO Input Setup'], ...
    'Device','/dev/simrt-validation-no-gpio','LineOffsets','[0 1 2 3]', ...
    'Direction','Input','Position',[50 360 235 450]);
add_block([library '/DIO Read'],[name '/DIO Read'], ...
    'LineCount','4','Position',[490 360 640 450]);
add_block([library '/DIO Setup'],[name '/DIO Output Setup'], ...
    'Device','/dev/simrt-validation-no-gpio','LineOffsets','[4 5 6 7]', ...
    'Direction','Output','InitialValues','false','Position',[50 550 235 640]);
add_block([library '/DIO Write'],[name '/DIO Write'],'Position',[490 550 640 640]);
constant(name,'Serial Data','uint8([1;2;3;4])',[275 45 375 75]);
constant(name,'Serial Length','uint32(4)',[275 105 375 135]);
constant(name,'Enable','true',[275 240 375 270]);
constant(name,'Output Values','false(4,1)',[275 570 385 600]);
connect(name,'Serial Setup/1','Serial Sent/1');
connect(name,'Serial Setup/1','Serial Receive/1');
connect(name,'Serial Data/1','Serial Sent/2');
connect(name,'Serial Length/1','Serial Sent/3');
connect(name,'Enable/1','Serial Sent/4');
connect(name,'DIO Input Setup/1','DIO Read/1');
connect(name,'DIO Output Setup/1','DIO Write/1');
connect(name,'Output Values/1','DIO Write/2');
connect(name,'Enable/1','DIO Write/3');
signals = {'Serial Setup/2','Serial Sent/1','Serial Sent/2', ...
    'Serial Receive/1','Serial Receive/2','Serial Receive/3', ...
    'DIO Input Setup/2','DIO Read/1','DIO Read/2', ...
    'DIO Output Setup/2','DIO Write/1'};
for index=1:numel(signals)
    destination = sprintf('Result %d',index);
    add_block('simulink/Sinks/Out1',[name '/' destination], ...
        'Port',num2str(index),'Position',[760 30+index*55 790 45+index*55]);
    connect(name,signals{index},[destination '/1']);
end
set_param(name,'SimulationCommand','update');
simulation=sim(name);
for index=[1 3 6 7 9 10 11]
    status=simulation.yout.getElement(index).Values.Data;
    assert(all(status(:)==int32(-38)), 'simrt:ark:Simulation', ...
        'Desktop simulation must report hardware access unavailable.');
end
report.desktop_simulation = true;
save_system(name,modelFile);
oldFolder = cd(reportRoot);
folderCleanup = onCleanup(@()cd(oldFolder)); %#ok<NASGU>
report.build = buildSimRTLocal(string(modelFile),Address='192.168.193.195');
load_system(library);
print(['-s' library],'-dpng',fullfile(reportRoot,'ark_library.png'));
report.passed = true;
stream=fopen(fullfile(reportRoot,'matlab_validation.json'),'w','n','UTF-8');
fileCleanup=onCleanup(@()fclose(stream)); %#ok<NASGU>
fprintf(stream,'%s',jsonencode(report,PrettyPrint=true));
disp(report);
end

function constant(model,name,value,position)
add_block('simulink/Sources/Constant',[model '/' name], ...
    'Value',value,'SampleTime','0.001','Position',position);
end

function connect(model,source,destination)
add_line(model,source,destination,'autorouting','on');
end
