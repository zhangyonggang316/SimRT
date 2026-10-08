function frame = duplexFrame(source, sequence)
%DUPLEXFRAME A5 5A, source, version, sequence LE, payload, CRC16 LE.
%#codegen
frame = zeros(12, 1, 'uint8');
frame(1:4) = uint8([165; 90; source; 1]);
for index = 0:3
    frame(5 + index) = uint8(bitand(bitshift(sequence, -8 * index), uint32(255)));
end
frame(9) = bitxor(frame(5), uint8(source));
frame(10) = bitxor(frame(9), uint8(255));
checksum = simrtlinux.serial.duplexCRC(frame, uint32(10));
frame(11) = uint8(bitand(checksum, uint16(255)));
frame(12) = uint8(bitshift(checksum, -8));
end
