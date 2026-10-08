function tests = testSerialEtherCAT
tests = functiontests(localfunctions);
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

function testSerialDesktopStatus(testCase)
setup=simrtlinux.serial.SerialSetup;
tx=simrtlinux.serial.SerialSent;
rx=simrtlinux.serial.SerialReceive('BufferSize',16);
cleanup=onCleanup(@()releaseAll(setup,tx,rx)); %#ok<NASGU>
[token,status]=setup();
verifyEqual(testCase,token,uint32(0));
verifyEqual(testCase,status,int32(-38));
[count,status]=tx(token,uint8([1;2;3]),uint32(3),false);
verifyEqual(testCase,count,uint32(0));
verifyEqual(testCase,status,int32(0));
[count,status]=tx(token,uint8([1;2;3]),uint32(3),true);
verifyEqual(testCase,count,uint32(0));
verifyEqual(testCase,status,int32(-38));
[~,status]=tx(token,uint8([1;2;3]),uint32(4),true);
verifyEqual(testCase,status,int32(-22));
[data,count,status]=rx(token);
verifyEqual(testCase,data,zeros(16,1,'uint8'));
verifyEqual(testCase,count,uint32(0));
verifyEqual(testCase,status,int32(-38));
end

function testEtherCATDesktopStatus(testCase)
block=simrtlinux.ethercat.EtherCATExchange('OutputBytes',2,'InputBytes',4);
cleanup=onCleanup(@()release(block)); %#ok<NASGU>
[data,wkc,expected,status]=block(uint8([1;2]));
verifyEqual(testCase,data,zeros(4,1,'uint8'));
verifyEqual(testCase,[wkc expected status],int32([0 0 -38]));
end

function testEtherCATInputOnly(testCase)
block=simrtlinux.ethercat.EtherCATExchange('OutputBytes',0,'InputBytes',4);
cleanup=onCleanup(@()release(block)); %#ok<NASGU>
[data,~,~,status]=block(uint8(0));
verifyEqual(testCase,data,zeros(4,1,'uint8'));
verifyEqual(testCase,status,int32(-38));
end

function releaseAll(varargin)
for k=1:nargin, release(varargin{k}); end
end
