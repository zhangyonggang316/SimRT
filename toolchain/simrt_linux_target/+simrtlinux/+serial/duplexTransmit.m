function [data5, length5, send5, data6, length6, send6, completed, failures] = ...
        duplexTransmit(enable, setupStatus, previousSent, previousStatus)
%DUPLEXTRANSMIT Alternate 10 ms write windows separated by 40 ms bus guards.
% Feedback belongs to the immediately preceding sample's Serial Sent call.
% A partial nonblocking write retries only its unaccepted suffix.
%#codegen
persistent tick frames offset active issued sequence done failed
if isempty(tick)
    tick = uint16(0); frames = zeros(12, 2, 'uint8');
    offset = zeros(2, 1, 'uint32'); active = false(2, 1); issued = false(2, 1);
    sequence = zeros(2, 1, 'uint32'); done = zeros(2, 1, 'uint32');
    failed = zeros(2, 1, 'uint32');
end
data = zeros(12, 2, 'uint8'); lengths = zeros(2, 1, 'uint32'); sends = false(2, 1);
if enable == 0
    tick = uint16(0); offset(:) = 0; active(:) = false; issued(:) = false;
    sequence(:) = 0; done(:) = 0; failed(:) = 0;
else
    for port = 1:2
        if issued(port)
            issued(port) = false;
            remaining = uint32(12) - offset(port);
            if previousSent(port) > remaining || ...
                    (previousStatus(port) ~= 0 && previousStatus(port) ~= -11)
                active(port) = false; failed(port) = failed(port) + uint32(1);
            else
                offset(port) = offset(port) + previousSent(port);
                if offset(port) == 12
                    active(port) = false; done(port) = done(port) + uint32(1);
                end
            end
        end
        % COM5 starts at tick 0, COM6 at tick 50.
        if port == 1, phase = double(tick); else, phase = mod(double(tick) + 50, 100); end
        if active(port) && (phase >= 10 || setupStatus(port) ~= 0)
            active(port) = false; failed(port) = failed(port) + uint32(1);
        end
        if phase == 0
            if setupStatus(port) == 0
                frames(:, port) = simrtlinux.serial.duplexFrame(uint8(port + 4), sequence(port));
                offset(port) = 0; active(port) = true;
            else
                failed(port) = failed(port) + uint32(1);
            end
            if sequence(port) == intmax('uint32'), sequence(port) = 0;
            else, sequence(port) = sequence(port) + uint32(1); end
        end
        if active(port)
            lengths(port) = uint32(12) - offset(port);
            for index = 1:double(lengths(port))
                data(index, port) = frames(index + double(offset(port)), port);
            end
            sends(port) = true; issued(port) = true;
        end
    end
    tick = uint16(mod(double(tick) + 1, 100));
end
data5 = data(:, 1); length5 = lengths(1); send5 = sends(1);
data6 = data(:, 2); length6 = lengths(2); send6 = sends(2);
completed = done; failures = failed;
end
