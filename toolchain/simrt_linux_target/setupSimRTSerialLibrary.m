function locations = setupSimRTSerialLibrary
%SETUPSIMRTSERIALLIBRARY Register RS232/RS485 System object blocks.
root = fileparts(mfilename('fullpath'));
driver = fullfile(root,'drivers','serial');
addpath(root,driver);
locations = struct('Library',string(fullfile(driver,'simrt_serial_library.slx')));
end
