function destination = buildSimRTLibrary
%BUILDSIMRTLIBRARY Group the existing driver blocks under one browser root.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
drivers = {'serial','dio','ethercat','tc1013','network'};
for index = 1:numel(drivers)
    addpath(fullfile(root,'drivers',drivers{index}));
end
addpath(root);
name = 'simrt_library';
destination = fullfile(fileparts(mfilename('fullpath')),[name '.slx']);
assert(~bdIsLoaded(name),'simrt:library:Loaded', ...
    'Close the SimRT library before rebuilding it.');
new_system(name,'Library');
cleanup = onCleanup(@()close_system(name,0)); %#ok<NASGU>
set_param(name,'EnableLBRepository','on','Location',[100 100 1240 580]);
groups = {'Serial','simrt_serial_library'; 'Digital IO','simrt_dio_library'; ...
    'EtherCAT','simrt_ethercat_library'; 'CAN','simrt_can_library'; ...
    'TCP UDP','simrt_network_library'};
for index = 1:size(groups,1)
    sublibrary = [name '/' groups{index,1}];
    column = mod(index-1,3); row = floor((index-1)/3);
    add_block('built-in/Subsystem',sublibrary, ...
        'Position',[50+column*350 60+row*200 300+column*350 160+row*200]);
    source = groups{index,2};
    wasLoaded = bdIsLoaded(source);
    load_system(source);
    sourceCleanup = onCleanup(@()closeIfNew(source,wasLoaded));
    blocks = find_system(source,'SearchDepth',1,'Type','Block');
    for blockIndex = 1:numel(blocks)
        block = blocks{blockIndex};
        add_block(block,[sublibrary '/' get_param(block,'Name')], ...
            'Position',get_param(block,'Position'));
    end
    clear sourceCleanup;
end
set_param(name,'Lock','on');
save_system(name,destination);
end

function closeIfNew(name,wasLoaded)
if ~wasLoaded && bdIsLoaded(name), close_system(name,0); end
end
