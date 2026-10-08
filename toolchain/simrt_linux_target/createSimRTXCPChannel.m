function [channel, a2l] = createSimRTXCPChannel(a2lFile, options)
%CREATESIMRTXCPCHANNEL Create an XCP-on-UDP channel for observation/calibration.

arguments
    a2lFile (1,1) string {mustBeFile}
    options.Address (1,1) string = "192.168.0.106"
    options.Port (1,1) double {mustBeInteger,mustBePositive} = 5555
    options.Connect (1,1) logical = false
end

xcpConfig = simrtXCPConfiguration;
if options.Port ~= xcpConfig.Port
    error('simrtlinux:FixedXCPConfigurationRequired', ...
        'Port must be %d because the generated target runtime is fixed.', ...
        xcpConfig.Port);
end
a2l = xcpA2L(a2lFile);
channel = xcpChannel(a2l, xcpConfig.Transport, ...
    options.Address, xcpConfig.Port);
if options.Connect
    connect(channel);
end
end
