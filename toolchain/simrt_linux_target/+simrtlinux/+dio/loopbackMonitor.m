function [inputMask, ready, valid, matched, mismatches] = ...
    loopbackMonitor(values, commandMask, enable, status, checkLoopback)
%LOOPBACKMONITOR Ignore output transitions for 20 ms; errors never pass.
%#codegen
persistent previous stable failures
if isempty(previous)
    previous = uint8(0);
    stable = uint16(0);
    failures = uint32(0);
end
inputMask = uint8(0);
for index = 1:4
    if values(index)
        inputMask = bitset(inputMask, index);
    end
end
ready = all(status == 0);
checking = enable ~= 0 && checkLoopback ~= 0;
if ~ready || ~checking || commandMask ~= previous
    stable = uint16(0);
elseif stable < 20
    stable = stable + uint16(1);
end
previous = commandMask;
valid = ready && checking && stable >= 20;
matched = valid && inputMask == commandMask;
if ~checking
    failures = uint32(0);
elseif valid && ~matched && failures < intmax('uint32')
    failures = failures + uint32(1);
end
mismatches = failures;
end
