function [a2lFile, packagedELF, manifestFile] = exportX280A2L(model, options)
%EXPORTX280A2L Package a matching x86-64 ELF and XCP-enabled A2L file.

arguments
    model (1,1) string
    options.OutputFolder (1,1) string = ""
    options.MapFile (1,1) string = ""
    options.TargetAddress (1,1) string = "192.168.219.86"
    options.XCPPort (1,1) double {mustBeInteger,mustBePositive} = 17725
    options.IndentFile (1,1) logical = true
end

xcpConfig = x280XCPConfiguration;
if options.XCPPort ~= xcpConfig.Port
    error('x280linux:FixedXCPConfigurationRequired', ...
        'XCPPort must be %d because the generated target runtime is fixed.', ...
        xcpConfig.Port);
end
[modelName, loadedHere] = openModel(model);
cleanup = onCleanup(@() closeIfLoadedHere(modelName, loadedHere));
if options.OutputFolder == ""
    root = fileparts(mfilename('fullpath'));
    options.OutputFolder = fullfile(root, 'artifacts', modelName);
end
if ~isfolder(options.OutputFolder)
    mkdir(options.OutputFolder);
end
if options.MapFile == ""
    options.MapFile = locateX280ELF(modelName);
end
assertX8664ELF(options.MapFile);

fileName = string(modelName) + ".a2l";
descriptions = coder.asap2.getEcuDescriptions(modelName, ...
    Folder=char(options.OutputFolder), ...
    FileName=char(fileName), ...
    MapFile=char(options.MapFile), ...
    GenerateXCPInfo=true, ...
    IncludeDefaultEventList=true, ...
    IndentFile=options.IndentFile);
descriptions = createX280ASAP2Hierarchy(string(modelName), descriptions);
coder.asap2.export(modelName, CustomEcuDescriptions=descriptions);
a2lFile = fullfile(options.OutputFolder, fileName);
if ~isfile(a2lFile)
    error('x280linux:A2LNotCreated', ...
        'ASAP2 export completed without creating %s.', a2lFile);
end
rewriteX280A2LForUDP(a2lFile, ...
    TargetAddress=options.TargetAddress, ...
    Port=xcpConfig.Port, ...
    MaxDTOBytes=xcpConfig.MaxDTOBytes);

[~, elfName, elfExtension] = fileparts(options.MapFile);
packagedELF = fullfile(options.OutputFolder, elfName + elfExtension);
if ~strcmpi(char(options.MapFile), char(packagedELF))
    copyfile(options.MapFile, packagedELF, 'f');
end

a2lInfo = dir(a2lFile);
elfInfo = dir(packagedELF);
created = datetime('now', 'TimeZone', 'UTC', ...
    'Format', "yyyy-MM-dd'T'HH:mm:ss'Z'");
manifest = struct( ...
    'SchemaVersion', 2, ...
    'ModelName', string(modelName), ...
    'MATLABRelease', string(version('-release')), ...
    'CreatedUTC', string(created), ...
    'TargetHardware', "SimRT", ...
    'TargetAddress', options.TargetAddress, ...
    'XCPTransport', "UDP", ...
    'XCPPort', xcpConfig.Port, ...
    'XCPMaxDTOBytes', xcpConfig.MaxDTOBytes, ...
    'XCPMaxDatagramBytes', xcpConfig.MaxDatagramBytes, ...
    'A2LFile', string(a2lInfo.name), ...
    'A2LBytes', a2lInfo.bytes, ...
    'A2LSHA256', fileSHA256(a2lFile), ...
    'ELFFile', string(elfInfo.name), ...
    'ELFBytes', elfInfo.bytes, ...
    'ELFSHA256', fileSHA256(packagedELF));
manifestFile = fullfile(options.OutputFolder, ...
    string(modelName) + ".xcp-manifest.json");
fileID = fopen(manifestFile, 'w', 'n', 'UTF-8');
if fileID < 0
    error('x280linux:ManifestOpenFailed', ...
        'Cannot write artifact manifest: %s.', manifestFile);
end
fileCleanup = onCleanup(@() fclose(fileID));
fwrite(fileID, jsonencode(manifest, PrettyPrint=true), 'char');
clear fileCleanup;
clear cleanup;
end

function assertX8664ELF(fileName)
if ~isfile(fileName)
    error('x280linux:ELFNotFound', 'ELF file not found: %s.', fileName);
end
fileID = fopen(fileName, 'rb');
if fileID < 0
    error('x280linux:ELFOpenFailed', 'Cannot read ELF file: %s.', fileName);
end
cleanup = onCleanup(@() fclose(fileID));
header = fread(fileID, 20, '*uint8');
if numel(header) < 20 || ~isequal(header(1:4).', uint8([127 69 76 70]))
    error('x280linux:InvalidELF', 'File is not an ELF executable: %s.', fileName);
end
machine = double(header(19)) + 256 * double(header(20));
if header(5) ~= 2 || header(6) ~= 1 || machine ~= 62
    error('x280linux:WrongELFArchitecture', ...
        'Expected little-endian x86-64 ELF (machine 62): %s.', fileName);
end
clear cleanup;
end

function hashValue = fileSHA256(fileName)
fileID = fopen(fileName, 'rb');
if fileID < 0
    error('x280linux:HashOpenFailed', 'Cannot hash file: %s.', fileName);
end
cleanup = onCleanup(@() fclose(fileID));
bytes = fread(fileID, Inf, '*uint8');
digest = java.security.MessageDigest.getInstance('SHA-256');
digest.update(bytes);
signedHash = digest.digest;
unsignedHash = uint8(mod(double(signedHash), 256));
hashValue = lower(string(reshape(dec2hex(unsignedHash, 2).', 1, [])));
clear cleanup;
end

function [modelName, loadedHere] = openModel(model)
[~, fileName, extension] = fileparts(model);
if extension == ""
    modelName = char(model);
else
    modelName = char(fileName);
end
loadedHere = ~bdIsLoaded(modelName);
if loadedHere
    load_system(model);
end
end

function closeIfLoadedHere(modelName, loadedHere)
if loadedHere && bdIsLoaded(modelName)
    close_system(modelName, 0);
end
end
