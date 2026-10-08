function tests=testDIO
tests=functiontests(localfunctions);
end

function setupOnce(testCase)
root=fullfile(fileparts(fileparts(fileparts(fileparts(mfilename('fullpath'))))), ...
    'toolchain','simrt_linux_target');
testCase.TestData.Path=path;
addpath(root);
end

function teardownOnce(testCase)
path(testCase.TestData.Path);
end

function testDesktopStatusAndShapes(testCase)
setup=simrtlinux.dio.DIOSetup('LineOffsets',[7 2 19],'Direction','Output','InitialValues',[true false true]);
reader=simrtlinux.dio.DIORead('LineCount',3);
writer=simrtlinux.dio.DIOWrite;
cleanup=onCleanup(@()releaseAll(setup,reader,writer)); %#ok<NASGU>
[token,status]=setup();
verifyEqual(testCase,token,uint32(0));
verifyEqual(testCase,status,int32(-38));
[values,status]=reader(token);
verifyEqual(testCase,values,false(3,1));
verifyEqual(testCase,status,int32(-38));
verifyEqual(testCase,writer(token,true(3,1),false),int32(0));
verifyEqual(testCase,writer(token,true(3,1),true),int32(-38));
end

function testScalarInitialValueAndFullWidth(testCase)
setup=simrtlinux.dio.DIOSetup('LineOffsets',0:63,'Direction','Output','InitialValues',true,'ActiveLow',true);
reader=simrtlinux.dio.DIORead('LineCount',64);
cleanup=onCleanup(@()releaseAll(setup,reader)); %#ok<NASGU>
[token,status]=setup();
verifyEqual(testCase,status,int32(-38));
[values,status]=reader(token);
verifyEqual(testCase,values,false(64,1));
verifyEqual(testCase,status,int32(-38));
end

function testRejectsDuplicateOffsets(testCase)
setup=simrtlinux.dio.DIOSetup('LineOffsets',[2 2]);
cleanup=onCleanup(@()release(setup)); %#ok<NASGU>
verifyError(testCase,@()step(setup),'simrt:dio:LineOffsets');
end

function testRejectsTooManyOffsets(testCase)
setup=simrtlinux.dio.DIOSetup('LineOffsets',0:64);
cleanup=onCleanup(@()release(setup)); %#ok<NASGU>
verifyError(testCase,@()step(setup),'simrt:dio:LineOffsets');
end

function testRejectsInitialValueCount(testCase)
setup=simrtlinux.dio.DIOSetup('LineOffsets',[1 3 5],'Direction','Output','InitialValues',[true false]);
cleanup=onCleanup(@()release(setup)); %#ok<NASGU>
verifyError(testCase,@()step(setup),'simrt:dio:InitialValues');
end

function testRejectsDeviceOutsideDev(testCase)
setup=simrtlinux.dio.DIOSetup('Device','/tmp/gpiochip0');
cleanup=onCleanup(@()release(setup)); %#ok<NASGU>
verifyError(testCase,@()step(setup),'simrt:dio:Device');
end

function testSimulinkPortTypesAndColumnWidth(testCase)
model='simrt_dio_test_ports';
assert(~bdIsLoaded(model),'DIO test model is already open.');
new_system(model);
cleanup=onCleanup(@()close_system(model,0)); %#ok<NASGU>
set_param(model,'Solver','FixedStepDiscrete','FixedStep','0.001','StopTime','0.002', ...
    'SaveOutput','on','OutputSaveName','yout','SaveFormat','Dataset','ReturnWorkspaceOutputs','on');
add_block('simulink/User-Defined Functions/MATLAB System',[model '/Setup'], ...
    'System','simrtlinux.dio.DIOSetup','LineOffsets','[7 2 19]','Direction','Output');
add_block('simulink/User-Defined Functions/MATLAB System',[model '/Read'], ...
    'System','simrtlinux.dio.DIORead','LineCount','3');
add_block('simulink/User-Defined Functions/MATLAB System',[model '/Write'], ...
    'System','simrtlinux.dio.DIOWrite');
add_block('simulink/Sources/Constant',[model '/Values'],'Value','[true;false;true]', ...
    'OutDataTypeStr','boolean','VectorParams1D','off');
add_block('simulink/Sources/Constant',[model '/Enable'],'Value','false','OutDataTypeStr','boolean');
names={'SetupStatus','ReadValues','ReadStatus','WriteStatus'};
for k=1:numel(names)
    add_block('simulink/Sinks/Out1',[model '/' names{k}],'Port',num2str(k));
end
add_line(model,'Setup/1','Read/1');
add_line(model,'Setup/1','Write/1');
add_line(model,'Values/1','Write/2');
add_line(model,'Enable/1','Write/3');
add_line(model,'Setup/2','SetupStatus/1');
add_line(model,'Read/1','ReadValues/1');
add_line(model,'Read/2','ReadStatus/1');
add_line(model,'Write/1','WriteStatus/1');
output=sim(model);
verifyEqual(testCase,reshape(output.yout.getElement(1).Values.Data,[],1),repmat(int32(-38),3,1));
values=output.yout.getElement(2).Values;
verifyEqual(testCase,values.Time,(0:0.001:0.002)','AbsTol',1e-12);
verifyEqual(testCase,getdatasamples(values,1),false(3,1));
verifyEqual(testCase,reshape(output.yout.getElement(3).Values.Data,[],1),repmat(int32(-38),3,1));
verifyEqual(testCase,reshape(output.yout.getElement(4).Values.Data,[],1),zeros(3,1,'int32'));

directory=tempname;
mkdir(directory);
settings=Simulink.fileGenControl('getConfig');
restoreSettings=onCleanup(@()Simulink.fileGenControl('setConfig','config',settings)); %#ok<NASGU>
Simulink.fileGenControl('set','CacheFolder',directory,'CodeGenFolder',directory,'createDir',true);
set_param([model '/Enable'],'Value','true');
set_param(model,'SystemTargetFile','ert.tlc','GenCodeOnly','on','GenerateMakefile','off','GenerateReport','off');
save_system(model,fullfile(directory,[model '.slx']));
slbuild(model);
generated=fileread(fullfile(directory,[model '_ert_rtw'],[model '.c']));
for entry={'simrt_dio_open','simrt_dio_read','simrt_dio_write','simrt_dio_close'}
    verifySubstring(testCase,generated,entry{1});
end
info=load(fullfile(directory,[model '_ert_rtw'],'buildInfo.mat'),'buildInfo');
verifyTrue(testCase,any(endsWith(string(info.buildInfo.getSourceFiles(true,true)),'simrt_dio.c')));
end

function releaseAll(varargin)
for k=1:nargin, release(varargin{k}); end
end
