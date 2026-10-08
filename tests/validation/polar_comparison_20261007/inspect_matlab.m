function report = inspect_matlab
%INSPECT_MATLAB Inspect existing registrations without loading vendor code.
report = struct;
report.release = version('-release');
report.customizations = which('sl_customization', '-all');
report.polar = which('PolarDriver');
report.toolchains = coder.make.getToolchains;
report.path = strsplit(path, pathsep);
report.loaded_models = find_system('type', 'block_diagram');
folder = fileparts(mfilename('fullpath'));
stream = fopen(fullfile(folder, 'matlab_before.json'), 'w', 'n', 'UTF-8');
cleanup = onCleanup(@() fclose(stream)); %#ok<NASGU>
fprintf(stream, '%s\n', jsonencode(report, PrettyPrint=true));
disp(report);
end
