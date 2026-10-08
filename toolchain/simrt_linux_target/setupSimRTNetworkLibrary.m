function locations = setupSimRTNetworkLibrary
%SETUPSIMRTNETWORKLIBRARY Register the Linux TCP/UDP System object blocks.
root = fileparts(mfilename('fullpath'));
driver = fullfile(root, 'drivers', 'network');
addpath(root, driver);
locations = struct('Library', string(fullfile(driver, 'simrt_network_library.slx')), ...
    'Documentation', string(fullfile(driver, 'README.md')));
end
