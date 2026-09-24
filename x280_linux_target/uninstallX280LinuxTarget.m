function uninstallX280LinuxTarget(options)
%UNINSTALLX280LINUXTARGET Remove the X280 target from the MATLAB path.

arguments
    options.Persist (1,1) logical = false
end

targetRoot = fileparts(mfilename('fullpath'));
if contains([path pathsep], [targetRoot pathsep])
    rmpath(targetRoot);
end
rehash toolboxcache;
sl_refresh_customizations;

if options.Persist && savepath ~= 0
    error('x280linux:SavePathFailed', ...
        'The target was removed for this session, but savepath failed.');
end
end
