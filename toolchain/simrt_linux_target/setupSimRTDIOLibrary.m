function locations=setupSimRTDIOLibrary
%SETUPSIMRTDIOLIBRARY Register Linux GPIO character-device v2 System blocks.
root=fileparts(mfilename('fullpath'));
driver=fullfile(root,'drivers','dio');
addpath(root,driver);
locations=struct('Library',string(fullfile(driver,'simrt_dio_library.slx')));
end
