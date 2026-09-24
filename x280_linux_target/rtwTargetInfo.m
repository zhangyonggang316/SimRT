function rtwTargetInfo(registry)
%RTWTARGETINFO Register the SimRT hardware target.

codertarget.TargetRegistry.addToTargetRegistry(@registerTarget);
codertarget.TargetBoardRegistry.addToTargetBoardRegistry(@registerBoards);
registry.registerTargetInfo(@registerToolchain);
end

function info = registerToolchain
info = coder.make.ToolchainInfoRegistry;
info.Name = 'X280 portable-linux-toolchain';
info.FileName = fullfile(fileparts(mfilename('fullpath')), 'registry', 'x280_portable_toolchain.mat');
info.TargetHWDeviceType = {'Intel->x86-64 (Linux 64)'};
info.Platform = {'win64'};
end

function info = registerTarget
info.Name = 'x280linux';
info.ShortName = 'x280linux';
info.TargetFolder = fileparts(mfilename('fullpath'));
info.TargetType = 1;
info.TargetVersion = 1;
end

function boards = registerBoards
targetFolder = fileparts(mfilename('fullpath'));
boardFolder = codertarget.target.getTargetHardwareRegistryFolder(targetFolder);
boards = codertarget.target.getTargetHardwareInfo( ...
    targetFolder, boardFolder, 'x280linux', true);
end
