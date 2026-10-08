function [dlc, valid] = fdLengthToDLC(lengthBytes)
%FDLENGTHTODLC Exact ISO CAN FD byte-length to DLC conversion, without padding.
%#codegen
dlc = uint8(0);
valid = true;
switch double(lengthBytes)
    case {0, 1, 2, 3, 4, 5, 6, 7, 8}
        dlc = uint8(lengthBytes);
    case 12
        dlc = uint8(9);
    case 16
        dlc = uint8(10);
    case 20
        dlc = uint8(11);
    case 24
        dlc = uint8(12);
    case 32
        dlc = uint8(13);
    case 48
        dlc = uint8(14);
    case 64
        dlc = uint8(15);
    otherwise
        valid = false;
end
end
