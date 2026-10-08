function onAfterCodeGen(hCS, buildInfo)
%ONAFTERCODEGEN Configure XCP and the local autonomous Linux runtime.

targetName = codertarget.targethardware.getTargetHardwareName(hCS);
if isempty(targetName)
    error('simrtlinuxssh:MissingTargetName', ...
        'Target hardware name is empty after code generation.');
end

modelHandle = getModel(hCS);
modelName = get_param(modelHandle, 'Name');
manager = coder.internal.ModelCodegenMgr.getInstance(modelHandle);
if ~isempty(manager) && manager.MdlRefBuildArgs.XilInfo.IsSil
    error('simrtlinuxssh:SILNotSupported', ...
        'SIL is not supported by the SimRT target.');
end

buildInfo.addMakeVars('CUSTOM_C_FLAGS', '');
buildInfo.addMakeVars('CUSTOM_CPP_FLAGS', '');

% The R2024b Linux main combines classic rtExtMode calls with ext_mode.h APIs.
% Include both official adapters so the generated entry point links completely.
xcpAdapterDirectory = fullfile(matlabroot, 'toolbox', 'coder', 'xcp', ...
    'src', 'target', 'ext_mode', 'src');
buildInfo.addSourceFiles('xcp_ext_mode.c', xcpAdapterDirectory, 'EXT_MODE');

% Keep MathWorks' XCP-on-Ethernet framing and rtIOStream driver, but replace
% its TCP defaults with the SimRT UDP-only initialization parameters.
buildInfo.removeSourceFiles('xcp_ext_param_default_tcp.c');
targetRoot = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
sourceDirectory = fullfile(targetRoot, 'src');
buildInfo.addSourcePaths(sourceDirectory, 'EXT_MODE');
buildInfo.addSourceFiles( ...
    'xcp_ext_param_simrt_udp.c', sourceDirectory, 'EXT_MODE');
% R2024b's UDP socket otherwise remains pinned to the first client's port
% after XCP DISCONNECT. The adapter includes the original driver unchanged.
buildInfo.removeSourceFiles('rtiostream_tcpip.c');
buildInfo.addIncludePaths(fullfile(matlabroot, 'toolbox', 'coder', ...
    'rtiostream', 'src', 'rtiostreamtcpip'));
buildInfo.addSourceFiles('simrt_rtiostream_udp.c', sourceDirectory, 'EXT_MODE');
buildInfo.addSourceFiles('simrt_xcp_status.c', sourceDirectory, 'EXT_MODE');
% pyXCP 0.22.32 accepts UDP datagrams up to 512 bytes. The XCP Ethernet
% header consumes four bytes, so advertise a maximum 508-byte DTO.
xcpConfig = simrtXCPConfiguration;
buildInfo.updateDefines( ...
    {sprintf('XCP_MAX_DTO_SIZE=%d', xcpConfig.MaxDTOBytes)}, ...
    'create', true);
synchronizeServerConfig(modelName, xcpConfig.MaxDTOBytes);
if ~strcmp(get_param(hCS, 'GenCodeOnly'), 'on')
    codertarget.simrtlinuxssh.internal.addRealtimeRuntime(modelName, buildInfo);
end
end

function synchronizeServerConfig(modelName, maxDTOBytes)
buildDirectory = RTW.getBuildDir(modelName);
serverConfigFile = fullfile( ...
    buildDirectory.BuildDirectory, 'xcp', 'server_config.json');
if ~isfile(serverConfigFile)
    error('simrtlinuxssh:MissingXCPServerConfig', ...
        'Generated XCP server metadata not found: %s', serverConfigFile);
end

metadata = jsondecode(fileread(serverConfigFile));
entries = metadata.entries;
serverIndex = find(strcmp(string({entries.type}), ...
    "coder.xcp.ServerConfig"), 1);
if isempty(serverIndex)
    error('simrtlinuxssh:InvalidXCPServerConfig', ...
        'No coder.xcp.ServerConfig entry exists in %s.', serverConfigFile);
end
entries(serverIndex).content.MaxDTOBytes = maxDTOBytes;
metadata.entries = entries;

fileID = fopen(serverConfigFile, 'w', 'n', 'UTF-8');
if fileID < 0
    error('simrtlinuxssh:XCPServerConfigWriteFailed', ...
        'Cannot update %s.', serverConfigFile);
end
cleanup = onCleanup(@() fclose(fileID));
fwrite(fileID, jsonencode(metadata), 'char');
clear cleanup;
end
