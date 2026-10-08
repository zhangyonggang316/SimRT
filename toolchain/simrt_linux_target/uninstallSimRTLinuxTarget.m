function uninstallSimRTLinuxTarget(options)
%UNINSTALLSIMRTLINUXTARGET Remove the SimRT target from the MATLAB path.

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
    error('simrtlinux:SavePathFailed', ...
        'The target was removed for this session, but savepath failed.');
end
end
