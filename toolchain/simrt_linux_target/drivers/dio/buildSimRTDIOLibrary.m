function destination=buildSimRTDIOLibrary
%BUILDSIMRTDIOLIBRARY Create the R2024b DIO block library without hardware access.
root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(root);
name='simrt_dio_library';
destination=fullfile(fileparts(mfilename('fullpath')),[name '.slx']);
assert(~bdIsLoaded(name),'simrt:dio:LibraryLoaded','Close the DIO library before rebuilding it.');
new_system(name,'Library');
cleanup=onCleanup(@()close_system(name,0)); %#ok<NASGU>
set_param(name,'EnableLBRepository','on');
blocks={'DIO Setup','DIOSetup';'DIO Read','DIORead';'DIO Write','DIOWrite'};
for k=1:size(blocks,1)
    add_block('simulink/User-Defined Functions/MATLAB System',[name '/' blocks{k,1}], ...
        'System',['simrtlinux.dio.' blocks{k,2}], ...
        'Position',[60+(k-1)*190 60 190+(k-1)*190 140]);
end
set_param(name,'Lock','on');
save_system(name,destination);
end
