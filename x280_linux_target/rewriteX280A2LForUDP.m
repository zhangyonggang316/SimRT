function rewriteX280A2LForUDP(a2lFile, options)
%REWRITEX280A2LFORUDP Synchronize generated XCP metadata with the UDP target.

arguments
    a2lFile (1,1) string {mustBeFile}
    options.TargetAddress (1,1) string = "192.168.0.106"
    options.Port (1,1) double {mustBeInteger,mustBePositive, ...
        mustBeLessThanOrEqual(options.Port, 65535)} = 17725
    options.MaxDTOBytes (1,1) double {mustBeInteger,mustBePositive, ...
        mustBeLessThanOrEqual(options.MaxDTOBytes, 65535)} = 508
end

config = x280XCPConfiguration;
requireFixedValue(options.Port, config.Port, 'Port');
requireFixedValue(options.MaxDTOBytes, config.MaxDTOBytes, 'MaxDTOBytes');
mustBeIPv4Address(options.TargetAddress);

contents = fileread(a2lFile);
contents = rewriteTransportBlock(contents, options.TargetAddress, options.Port);
contents = rewriteProtocolLayer(contents, options.MaxDTOBytes);
writeTextFileAtomically(a2lFile, contents);
end

function contents = rewriteTransportBlock(contents, address, port)
pattern = ['(?ms)^[ \t]*/begin[ \t]+XCP_ON_(?:TCP|UDP)_IP[ \t]*\r?$' ...
    '.*?^[ \t]*/end[ \t]+XCP_ON_(?:TCP|UDP)_IP[ \t]*\r?$'];
[startIndex, endIndex] = regexp(contents, pattern, 'start', 'end');
if numel(startIndex) ~= 1
    error('x280linux:UnexpectedXCPTransportMetadata', ...
        'Expected one XCP-on-Ethernet IF_DATA block; found %d.', ...
        numel(startIndex));
end

block = contents(startIndex:endIndex);
[lines, lineEnding] = splitTextLines(block);
meaningful = find(~cellfun(@(line) isempty(strtrim(line)), lines));
if numel(meaningful) ~= 5 || ...
        isempty(regexp(strtrim(lines{meaningful(2)}), ...
        '^(?:0[xX][0-9A-Fa-f]+|[0-9]+)$', 'once'))
    error('x280linux:UnexpectedXCPTransportMetadata', ...
        'The XCP transport block does not match the R2024b generated form.');
end

outerIndent = regexp(lines{meaningful(1)}, '^[ \t]*', 'match', 'once');
valueIndent = regexp(lines{meaningful(2)}, '^[ \t]*', 'match', 'once');
version = strtrim(lines{meaningful(2)});
replacementLines = { ...
    [outerIndent, '/begin XCP_ON_UDP_IP'], ...
    [valueIndent, version], ...
    [valueIndent, sprintf('0x%04X', port)], ...
    [valueIndent, sprintf('ADDRESS "%s"', char(address))], ...
    [outerIndent, '/end XCP_ON_UDP_IP']};
replacement = strjoin(replacementLines, lineEnding);
contents = [contents(1:startIndex-1), replacement, ...
    contents(endIndex+1:end)];
end

function contents = rewriteProtocolLayer(contents, maxDTOBytes)
pattern = ['(?ms)^[ \t]*/begin[ \t]+PROTOCOL_LAYER[ \t]*\r?$' ...
    '.*?^[ \t]*/end[ \t]+PROTOCOL_LAYER[ \t]*\r?$'];
[startIndex, endIndex] = regexp(contents, pattern, 'start', 'end');
if numel(startIndex) ~= 1
    error('x280linux:UnexpectedXCPProtocolMetadata', ...
        'Expected one XCP PROTOCOL_LAYER block; found %d.', numel(startIndex));
end

block = contents(startIndex:endIndex);
[lines, lineEnding] = splitTextLines(block);
numericPattern = '^[ \t]*(?:0[xX][0-9A-Fa-f]+|[0-9]+)[ \t]*$';
numericLines = find(cellfun(@(line) ...
    ~isempty(regexp(line, numericPattern, 'once')), lines));
meaningful = find(~cellfun(@(line) isempty(strtrim(line)), lines));
if numel(numericLines) < 10 || numel(meaningful) < 11 || ...
        ~isequal(numericLines(1:10), meaningful(2:11))
    error('x280linux:UnexpectedXCPProtocolMetadata', ...
        'The XCP PROTOCOL_LAYER block does not match the R2024b generated form.');
end

maxDTOLine = numericLines(10);
valueIndent = regexp(lines{maxDTOLine}, '^[ \t]*', 'match', 'once');
lines{maxDTOLine} = [valueIndent, sprintf('0x%04X', maxDTOBytes)];
replacement = strjoin(lines, lineEnding);
contents = [contents(1:startIndex-1), replacement, ...
    contents(endIndex+1:end)];
end

function [lines, lineEnding] = splitTextLines(contents)
if contains(contents, sprintf('\r\n'))
    lineEnding = sprintf('\r\n');
elseif contains(contents, newline)
    lineEnding = newline;
else
    lineEnding = sprintf('\r');
end
lines = regexp(contents, '\r\n|\n|\r', 'split');
end

function requireFixedValue(actual, expected, optionName)
if actual ~= expected
    error('x280linux:FixedXCPConfigurationRequired', ...
        '%s must be %d because the generated target runtime is fixed.', ...
        optionName, expected);
end
end

function mustBeIPv4Address(address)
octets = regexp(char(address), ...
    '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', 'tokens', 'once');
if isempty(octets) || any(cellfun(@str2double, octets) > 255)
    error('x280linux:InvalidIPv4Address', ...
        'TargetAddress must be an IPv4 dotted-decimal address.');
end
end

function writeTextFileAtomically(fileName, contents)
temporaryFile = string(tempname(fileparts(fileName))) + ".a2l";
cleanup = onCleanup(@() deleteIfPresent(temporaryFile));
fileID = fopen(temporaryFile, 'w', 'n', 'UTF-8');
if fileID < 0
    error('x280linux:A2LRewriteFailed', ...
        'Cannot open a temporary file for %s.', fileName);
end
fileCleanup = onCleanup(@() fclose(fileID));
fwrite(fileID, contents, 'char');
clear fileCleanup;
[status, message] = movefile(temporaryFile, fileName, 'f');
if ~status
    error('x280linux:A2LRewriteFailed', ...
        'Cannot replace %s: %s', fileName, message);
end
clear cleanup;
end

function deleteIfPresent(fileName)
if isfile(fileName)
    delete(fileName);
end
end
