function state = prepare_layout
%PREPARE_LAYOUT Capture and release project-owned MATLAB files before relocation.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
names = find_system('type', 'block_diagram');
state = struct('folder', pwd, 'models', struct('name', {}, 'file', {}, 'dirty', {}), ...
    'paths', {strsplit(path, pathsep)});
for index = 1:numel(names)
    file = get_param(names{index}, 'FileName');
    if startsWith(file, [root filesep], 'IgnoreCase', true)
        state.models(end+1) = struct('name', names{index}, 'file', file, ...
            'dirty', get_param(names{index}, 'Dirty')); %#ok<AGROW>
    end
end
state.paths = state.paths(startsWith(state.paths, [root filesep], 'IgnoreCase', true));
file = fopen(fullfile(fileparts(mfilename('fullpath')), 'matlab_before.json'), 'w', 'n', 'UTF-8');
assert(file >= 0);
cleanup = onCleanup(@() fclose(file));
fprintf(file, '%s', jsonencode(state, PrettyPrint=true));
clear cleanup;
assert(~any(strcmp({state.models.dirty}, 'on')), 'simrt:layout:UnsavedModels', ...
    'Unsaved project model edits exist; preserve them before relocating files.');
for index = 1:numel(state.models)
    close_system(state.models(index).name, 0);
end
cd(root);
for index = 1:numel(state.paths)
    if ~strcmp(state.paths{index}, fileparts(mfilename('fullpath')))
        rmpath(state.paths{index});
    end
end
disp(state);
end
