function report = check_ark_installation(options)
%CHECK_ARK_INSTALLATION Check the unified browser catalog and legacy links.
arguments
    options.ReportFolder (1,1) string = ""
    options.ShowBrowser (1,1) logical = false
end
root=fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
folder=options.ReportFolder;
if strlength(folder)==0
    folder=fullfile(root,'tests/validation','simrt_library_20261006');
end
if ~isfolder(folder), mkdir(folder); end
expected=fullfile(root,'toolchain/simrt_linux_target','drivers','ark','simrt_library.slx');
assert(strcmpi(which('simrt_library'),expected),'simrt:ark:NotInstalled', ...
    'The persisted MATLAB path did not resolve the current SimRT library.');
name='simrt_library';
wasLoaded=bdIsLoaded(name);
load_system(name);
cleanup=onCleanup(@()closeIfNew(name,wasLoaded)); %#ok<NASGU>
assert(strcmp(get_param(name,'EnableLBRepository'),'on'));
groups={'Serial','simrt_serial_library'; 'Digital IO','simrt_dio_library'; ...
    'EtherCAT','simrt_ethercat_library'; 'CAN','simrt_can_library'; ...
    'TCP UDP','simrt_network_library'};
blocks=find_system(name,'SearchDepth',1,'Type','Block');
assert(isequal(sort(get_param(blocks,'Name')),sort(groups(:,1))));
sublibraries=cell(size(groups,1),1);
for index=1:size(groups,1)
    source=groups{index,2};
    sourceWasLoaded=bdIsLoaded(source);
    load_system(source);
    sourceCleanup=onCleanup(@()closeIfNew(source,sourceWasLoaded));
    sourceBlocks=find_system(source,'SearchDepth',1,'Type','Block');
    groupPath=[name '/' groups{index,1}];
    references=libinfo(groupPath);
    assert(numel(references)==numel(sourceBlocks) && ...
        all(strcmp({references.LinkStatus},'resolved')));
    assert(isequal(sort({references.ReferenceBlock}'),sort(sourceBlocks)));
    blockNames=get_param(sourceBlocks,'Name');
    if ischar(blockNames), blockNames={blockNames}; end
    sublibraries{index}=struct('name',groups{index,1},'source',source, ...
        'blocks',{blockNames},'links_resolved',true);
    clear sourceCleanup;
end
legacyName='simrt_ark_library';
legacyWasLoaded=bdIsLoaded(legacyName);
load_system(legacyName);
legacyCleanup=onCleanup(@()closeIfNew(legacyName,legacyWasLoaded)); %#ok<NASGU>
legacyLinks=libinfo(legacyName);
assert(numel(legacyLinks)==6 && all(strcmp({legacyLinks.LinkStatus},'resolved')));
parseWarning=warning('query','Simulink:dialog:parseError');
warningCleanup=onCleanup(@()warning(parseWarning)); %#ok<NASGU>
warning('error','Simulink:dialog:parseError');
rehash toolboxcache;
sl_refresh_customizations;
browser=slLibraryBrowser('noshow');
refresh(browser);
if options.ShowBrowser, show(browser); end
assert(strcmp(version('-release'),'2024b'),'simrt:ark:BrowserRelease', ...
    'Browser catalog inspection is validated for R2024b.');
% R2024b exposes the same catalog through standalone and docked components.
components=browser.getLBComponents;
assert(~isempty(components),'simrt:ark:BrowserMissing','No library browser component was created.');
oldLibraries={'SimRT ARK I/O','SimRT Linux Digital IO','SimRT Linux Serial', ...
    'SimRT Linux EtherCAT','SimRT Linux TCP UDP','SimRT Linux TC1013 CAN'};
catalogs=cell(size(components));
for index=1:numel(components)
    component=components{index};
    libraries=component.getSortedLibraryNames;
    assert(sum(strcmp(libraries,'SimRT'))==1 && ~any(ismember(oldLibraries,libraries)), ...
        'simrt:ark:BrowserLibraries','Expected one SimRT root and no legacy project roots.');
    previous=component.getCurrentTreeNode;
    selectionCleanup=onCleanup(@()restoreSelection(component,previous,options.ShowBrowser));
    assert(component.selectTreeNodeByName('SimRT'), ...
        'simrt:ark:BrowserSelection','Cannot select SimRT in the browser tree.');
    children=component.getChildren('SimRT');
    assert(isequal(sort(children(:)),sort(strcat('SimRT/',groups(:,1)))), ...
        'simrt:ark:BrowserChildren','The SimRT root must contain only the functional sublibraries.');
    palettes=cell(size(groups,1),1);
    for groupIndex=1:size(groups,1)
        node=['SimRT/' groups{groupIndex,1}];
        assert(component.selectTreeNodeByName(node), ...
            'simrt:ark:BrowserSelection','Cannot select a SimRT sublibrary.');
        displayed=component.getBlocks;
        expectedBlocks=strcat(node,'/',sublibraries{groupIndex}.blocks);
        assert(isequal(sort(displayed(:)),sort(expectedBlocks(:))), ...
            'simrt:ark:BrowserBlocks','A sublibrary palette differs from its source library.');
        palettes{groupIndex}=struct('node',node,'blocks',{displayed});
    end
    catalogs{index}=struct('libraries',{libraries}, ...
        'children',{children},'sublibraries',{palettes});
    if options.ShowBrowser, component.selectTreeNodeByName('SimRT'); end
    clear selectionCleanup;
end
report=struct('release',version('-release'),'persistent_path',true, ...
    'library',which(name),'sublibraries',{sublibraries},'links_resolved',true, ...
    'legacy_library',which(legacyName),'legacy_links_resolved',true, ...
    'browser_initialized',true,'browser_parse_errors',false, ...
    'browser_open',isOpen(browser),'browser_catalogs',{catalogs}, ...
    'browser_blocks_verified',true,'passed',true);
stream=fopen(fullfile(folder,'installation_check.json'),'w');
assert(stream>=0,'simrt:ark:ReportWrite','Cannot write the installation check report.');
fileCleanup=onCleanup(@()fclose(stream)); %#ok<NASGU>
fprintf(stream,'%s',jsonencode(report,PrettyPrint=true));
disp(report);
end

function closeIfNew(name,wasLoaded)
if ~wasLoaded && bdIsLoaded(name), close_system(name,0); end
end

function restoreSelection(component,previous,showBrowser)
if ~showBrowser && ~isempty(previous)
    component.selectTreeNodeByName(previous);
end
end
