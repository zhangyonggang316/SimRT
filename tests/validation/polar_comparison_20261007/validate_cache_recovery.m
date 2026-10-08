function report = validate_cache_recovery
%VALIDATE_CACHE_RECOVERY Recover an interrupted registration without user intervention.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
root = fullfile(root, 'simrt_linux_target');
clear setupSimRTLinuxTarget;
signature = fullfile(root, 'registry', 'simrt_portable_toolchain_signature.json');
original = fileread(signature);
cleanup = onCleanup(@() writeText(signature, original)); %#ok<NASGU>
writeText(signature, '{');
setupSimRTLinuxTarget;
restored = jsondecode(fileread(signature));
assert(strcmp(restored.Root, root));
variables = whos('-file', fullfile(root, 'registry', 'simrt_portable_toolchain.mat'));
assert(numel(variables) == 1 && strcmp(variables.name, 'tc'));
report = struct('malformed_signature_recovered', true, 'toolchain_mat_single_object', true);
writeText(fullfile(fileparts(mfilename('fullpath')), 'cache_recovery.json'), ...
    jsonencode(report, PrettyPrint=true));
end

function writeText(file, text)
stream = fopen(file, 'w', 'n', 'UTF-8');
assert(stream >= 0);
cleanup = onCleanup(@() fclose(stream)); %#ok<NASGU>
fprintf(stream, '%s', text);
end
