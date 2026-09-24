function locations = setupX280CANLibrary
%SETUPX280CANLIBRARY Register TC1013 blocks and the official CAN/CAN FD buses.
root = fileparts(mfilename('fullpath'));
driverRoot = fullfile(root, 'drivers', 'tc1013');
modelRoot = fullfile(driverRoot, 'models', 'x280_can_loopback');
assert(~isempty(which('canMessageBusType')) && ...
    ~isempty(which('canFDMessageBusType')), 'x280:can:MissingVNT', ...
    'Vehicle Network Toolbox is required for CAN/CAN FD Pack and Unpack.');
addpath(root, driverRoot);
if isfolder(modelRoot), addpath(modelRoot); end
canMessageBusType;
canFDMessageBusType;
locations = struct('Library', string(fullfile(driverRoot, 'x280_can_library.slx')), ...
    'TestModel', string(fullfile(modelRoot, 'x280_can_loopback.slx')), ...
    'DriverDirectory', "/home/zh/.local/lib/tscan");
end
