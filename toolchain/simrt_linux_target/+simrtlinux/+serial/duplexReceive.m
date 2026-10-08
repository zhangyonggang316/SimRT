function [stats5, stats6, healthy] = duplexReceive(enable, data5, length5, data6, length6, status)
%DUPLEXRECEIVE Bounded streaming parser: fragmented and coalesced serial frames.
% Per-port counters: valid, CRC errors, missed sequence numbers, duplicates/
% out-of-order frames, foreign frames, last sequence, age in ms, format errors.
%#codegen
persistent buffer used stats seen
if isempty(buffer)
    buffer = zeros(12, 2, 'uint8'); used = zeros(2, 1, 'uint8');
    stats = zeros(8, 2, 'uint32'); seen = false(2, 1);
end
if enable == 0
    used(:) = 0; stats(:) = 0; seen(:) = false;
else
    data = [data5 data6]; lengths = [length5; length6];
    for port = 1:2
        stats(7, port) = stats(7, port) + uint32(1);
        if status(port) ~= 0
            used(port) = 0;
            continue
        end
        for index = 1:min(double(lengths(port)), size(data, 1))
            used(port) = used(port) + uint8(1);
            buffer(double(used(port)), port) = data(index, port);
            % Shift past noise, retaining an incomplete A5 5A prefix.
            while used(port) > 0 && (buffer(1, port) ~= 165 || ...
                    (used(port) >= 2 && buffer(2, port) ~= 90))
                buffer(1:11, port) = buffer(2:12, port);
                used(port) = used(port) - uint8(1);
            end
            if used(port) ~= 12, continue; end
            checksum = bitor(uint16(buffer(11, port)), bitshift(uint16(buffer(12, port)), 8));
            expected = simrtlinux.serial.duplexCRC(buffer(:, port), uint32(10));
            if checksum ~= expected
                stats(2, port) = stats(2, port) + uint32(1);
                buffer(1:11, port) = buffer(2:12, port); used(port) = uint8(11);
                continue
            end
            used(port) = 0;
            if buffer(3, port) ~= uint8(7 - port)
                stats(5, port) = stats(5, port) + uint32(1);
                continue
            end
            if buffer(4, port) ~= 1 || buffer(9, port) ~= bitxor(buffer(5, port), buffer(3, port)) || ...
                    buffer(10, port) ~= bitxor(buffer(9, port), uint8(255))
                stats(8, port) = stats(8, port) + uint32(1);
                continue
            end
            sequence = uint32(0);
            for byte = 0:3
                sequence = bitor(sequence, bitshift(uint32(buffer(5 + byte, port)), 8 * byte));
            end
            if seen(port)
                delta = mod(double(sequence) - double(stats(6, port)), 4294967296);
                if delta == 0 || delta >= 2147483648
                    stats(4, port) = stats(4, port) + uint32(1);
                    continue
                end
                stats(3, port) = stats(3, port) + uint32(delta - 1);
            else
                % Sender sequences start at zero; count initial losses too.
                stats(3, port) = stats(3, port) + sequence;
            end
            seen(port) = true; stats(6, port) = sequence;
            stats(1, port) = stats(1, port) + uint32(1); stats(7, port) = 0;
        end
    end
end
stats5 = stats(:, 1); stats6 = stats(:, 2);
healthy = enable ~= 0 && all(status == 0) && all(seen) && all(stats(7, :) < 250) && ...
    all(all(stats(2:5, :) == 0)) && all(stats(8, :) == 0);
end
