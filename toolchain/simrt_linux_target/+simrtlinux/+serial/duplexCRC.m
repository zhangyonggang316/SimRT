function checksum = duplexCRC(bytes, count)
%DUPLEXCRC CRC-16/CCITT-FALSE, polynomial 0x1021 and initial value 0xFFFF.
%#codegen
checksum = uint16(65535);
for index = 1:double(count)
    checksum = bitxor(checksum, bitshift(uint16(bytes(index)), 8));
    for bit = 1:8
        high = bitand(checksum, uint16(32768)) ~= 0;
        checksum = bitshift(checksum, 1);
        if high, checksum = bitxor(checksum, uint16(4129)); end
    end
end
end
