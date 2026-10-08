function locations = setupSimRTARKLibrary(options)
%SETUPSIMRTARKLIBRARY Register the unified SimRT library and legacy ARK links.
arguments
    options.Persist (1,1) logical = false
    options.Refresh (1,1) logical = true
end
assert(strcmp(version('-release'),'2024b'), 'simrt:ark:Release', ...
    'The ARK library requires MATLAB R2024b.');
root = fileparts(mfilename('fullpath'));
setupSimRTSerialLibrary;
setupSimRTDIOLibrary;
setupSimRTNetworkLibrary;
setupSimRTEtherCATLibrary;
addpath(fullfile(root,'drivers','tc1013'));
driver = fullfile(root,'drivers','ark');
addpath(root,driver);
legacyLibrary = fullfile(driver,'simrt_ark_library.slx');
if ~isfile(legacyLibrary)
    buildSimRTARKLibrary;
end
library = fullfile(driver,'simrt_library.slx');
if ~isfile(library)
    buildSimRTLibrary;
end
if options.Refresh
    rehash toolboxcache;
    sl_refresh_customizations;
end
if options.Persist && savepath ~= 0
    error('simrt:ark:SavePathFailed', ...
        'Library registered for this session, but saving the MATLAB path failed.');
end
locations = struct('Library',string(library),'BrowserName',"SimRT", ...
    'LegacyLibrary',string(legacyLibrary));
end
