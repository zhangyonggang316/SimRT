function report = verifySimRTEnvironment(options)
%VERIFYSIMRTENVIRONMENT Validate local prerequisites and target reachability.

arguments
    options.Address (1,1) string = "192.168.219.86"
    options.SSHPort (1,1) double {mustBeInteger,mustBePositive} = 22
    options.TimeoutSeconds (1,1) double {mustBePositive} = 3
    options.ProbeTarget (1,1) logical = false
    options.Strict (1,1) logical = false
end

report = struct;
report.MATLABRelease = string(version('-release'));
report.TargetRoot = string(fileparts(mfilename('fullpath')));
report.TargetRegistered = false;
report.BoardRegistered = false;
report.RegistrationError = "";
report.Toolchain = inspectSimRTToolchain;
report.LocalToolchainRoot = report.Toolchain.Root;
report.LocalBuildAvailable = report.Toolchain.Passed;
report.A2LExportAvailable = ~isempty(which('coder.asap2.export'));
report.XCPAvailable = ~isempty(which('xcpA2L')) && ...
    ~isempty(which('xcpChannel'));
report.RequiredProducts = struct( ...
    'Simulink', ~isempty(ver('Simulink')), ...
    'SimulinkCoder', ~isempty(which('slbuild')), ...
    'EmbeddedCoder', ~isempty(which('coder.asap2.export')));
try
    setupSimRTLinuxTarget;
    report.TargetRegistered = codertarget.target.isTargetRegistered('simrtlinux');
    boards = codertarget.target.getAllHardwareBoards('simrtlinux');
    report.BoardRegistered = any(strcmp({boards.Name}, 'SimRT'));
catch exception
    report.RegistrationError = string(exception.message);
end
report.Address = options.Address;
report.SSHPort = options.SSHPort;
if options.ProbeTarget
    [report.TargetPortReachable, report.TargetProbeMessage] = probeTcpPort( ...
        options.Address, options.SSHPort, options.TimeoutSeconds);
else
    report.TargetPortReachable = NaN;
    report.TargetProbeMessage = "not requested";
end

productChecks = struct2array(report.RequiredProducts);
report.AllLocalChecksPassed = report.MATLABRelease == "2024b" && ...
    report.TargetRegistered && report.BoardRegistered && ...
    report.LocalBuildAvailable && report.A2LExportAvailable && ...
    report.XCPAvailable && all(productChecks);

if options.Strict && ~report.AllLocalChecksPassed
    error('simrtlinux:LocalValidationFailed', ...
        'One or more local SimRT prerequisites failed. Inspect the returned report.');
end
if options.Strict && options.ProbeTarget && ~report.TargetPortReachable
    error('simrtlinux:TargetUnreachable', ...
        'Cannot reach %s:%d: %s', options.Address, options.SSHPort, ...
        report.TargetProbeMessage);
end
end

function [reachable, message] = probeTcpPort(address, port, timeoutSeconds)
socket = javaObject('java.net.Socket');
cleanup = onCleanup(@() closeSocket(socket));
try
    endpoint = javaObject('java.net.InetSocketAddress', char(address), port);
    socket.connect(endpoint, int32(timeoutSeconds * 1000));
    reachable = true;
    message = "connected";
catch exception
    reachable = false;
    message = string(exception.message);
end
clear cleanup;
end

function closeSocket(socket)
try
    socket.close;
catch
end
end
