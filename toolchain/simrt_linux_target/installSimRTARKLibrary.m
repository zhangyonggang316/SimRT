function installation = installSimRTARKLibrary
%INSTALLSIMRTARKLIBRARY Install for this user without administrator privileges.
parseWarning=warning('query','Simulink:dialog:parseError');
warningCleanup=onCleanup(@()warning(parseWarning)); %#ok<NASGU>
warning('error','Simulink:dialog:parseError');
setupSimRTLinuxTarget;
root = fileparts(mfilename('fullpath'));
installation = struct('library',which('simrt_library'), ...
    'release',version('-release'),'method',"pathdef",'startup',"");
browser = slLibraryBrowser('noshow');
refresh(browser);
installation.browser_parsed = true;
if savepath == 0, return; end
folders = strsplit(userpath,pathsep);
assert(~isempty(folders) && ~isempty(folders{1}), 'simrt:ark:UserPath', ...
    'MATLAB userpath must name a writable folder for persistent installation.');
folder = folders{1};
if ~isfolder(folder), mkdir(folder); end
startup = fullfile(folder,'startup.m');
text = '';
if isfile(startup), text = fileread(startup); end
beginMarker = '% BEGIN SIMRT ARK LIBRARY';
endMarker = '% END SIMRT ARK LIBRARY';
first = strfind(text,beginMarker); last = strfind(text,endMarker);
assert(numel(first)<=1 && numel(first)==numel(last) && ...
    (isempty(first) || first<last), 'simrt:ark:StartupMarkers', ...
    'The existing SimRT startup markers are incomplete; startup.m was not changed.');
paths = {root,fullfile(root,'drivers','ark'),fullfile(root,'drivers','dio'), ...
    fullfile(root,'drivers','serial'),fullfile(root,'drivers','network'), ...
    fullfile(root,'drivers','ethercat'),fullfile(root,'drivers','tc1013')};
lines = {beginMarker};
for index=1:numel(paths)
    literal = strrep(paths{index},'''','''''');
    lines{end+1} = sprintf('if isfolder(''%s''), addpath(''%s''); end',literal,literal); %#ok<AGROW>
end
lines{end+1}=endMarker;
block = strjoin(lines,newline);
if isempty(first)
    text = [text newline block newline];
else
    text = [text(1:first-1) block text(last+numel(endMarker):end)];
end
if isfile(startup) && ~isfile([startup '.before-simrt-ark'])
    copyfile(startup,[startup '.before-simrt-ark']);
end
stream=fopen(startup,'w','n','UTF-8');
assert(stream>=0,'simrt:ark:StartupWrite','Cannot write the user startup file.');
cleanup=onCleanup(@()fclose(stream)); %#ok<NASGU>
fprintf(stream,'%s',text);
installation.method="user startup";
installation.startup=string(startup);
end
