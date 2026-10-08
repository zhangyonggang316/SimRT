function locations = setupSimRTEtherCATLibrary
%SETUPSIMRTETHERCATLIBRARY Register the SOEM PDO exchange block.
root=fileparts(mfilename('fullpath'));
driver=fullfile(root,'drivers','ethercat');
addpath(root,driver);
locations=struct('Library',string(fullfile(driver,'simrt_ethercat_library.slx')), ...
    'SOEMSource',string(fullfile(driver,'vendor','soem')));
end
