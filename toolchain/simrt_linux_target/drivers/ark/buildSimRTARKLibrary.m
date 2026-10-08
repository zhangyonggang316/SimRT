function destination = buildSimRTARKLibrary
%BUILDSIMRTARKLIBRARY Build the shared entry point with linked driver blocks.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(root);
setupSimRTSerialLibrary;
setupSimRTDIOLibrary;
name = 'simrt_ark_library';
destination = fullfile(fileparts(mfilename('fullpath')),[name '.slx']);
assert(~bdIsLoaded(name),'simrt:ark:LibraryLoaded', ...
    'Close the ARK library before rebuilding it.');
new_system(name,'Library');
cleanup = onCleanup(@()close_system(name,0)); %#ok<NASGU>
set_param(name,'EnableLBRepository','on','Location',[100 100 1320 620]);
sources = {'simrt_serial_library/Serial Setup','simrt_serial_library/Serial Sent', ...
    'simrt_serial_library/Serial Receive','simrt_dio_library/DIO Setup', ...
    'simrt_dio_library/DIO Read','simrt_dio_library/DIO Write'};
for index = 1:numel(sources)
    [~,blockName] = fileparts(sources{index});
    column = mod(index-1,3); row = floor((index-1)/3);
    add_block(sources{index},[name '/' blockName], ...
        'Position',[40+column*370 60+row*190 310+column*370 160+row*190]);
end
set_param(name,'Lock','on');
save_system(name,destination);
end
