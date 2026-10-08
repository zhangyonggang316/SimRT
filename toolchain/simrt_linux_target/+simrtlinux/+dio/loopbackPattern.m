function [values, mask] = loopbackPattern(enable, automatic, manualMask)
%LOOPBACKPATTERN Four outputs, one second per channel at the 1 ms base rate.
%#codegen
persistent ticks channel
if isempty(ticks)
    ticks = uint16(0);
    channel = uint8(0);
end
mask = uint8(0);
if enable == 0
    ticks = uint16(0);
    channel = uint8(0);
elseif automatic ~= 0
    mask = bitshift(uint8(1), channel);
    ticks = ticks + uint16(1);
    if ticks >= 1000
        ticks = uint16(0);
        channel = bitand(channel + uint8(1), uint8(3));
    end
else
    mask = bitand(manualMask, uint8(15));
    ticks = uint16(0);
    channel = uint8(0);
end
values = false(4, 1);
for index = 1:4
    values(index) = bitget(mask, index) ~= 0;
end
end
