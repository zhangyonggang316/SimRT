classdef Loopback
    %LOOPBACK Bounded, MATLAB-only CAN1 <-> CAN2 simulation transport.
    methods (Static)
        function [token, status] = configure(directory, serial, channel, canfd, baud, dataBaud, termination, enabled)
            [token, status] = x280linux.can.Loopback.state('configure', ...
                directory, serial, channel, canfd, baud, dataBaud, termination, enabled);
        end

        function release(token)
            x280linux.can.Loopback.state('release', token);
        end

        function status = send(channel, canfd, message)
            status = x280linux.can.Loopback.state('send', channel, canfd, message);
        end

        function [message, valid, status] = receive(channel, canfd)
            [message, valid, status] = x280linux.can.Loopback.state( ...
                'receive', channel, canfd);
        end
    end

    methods (Static, Access=private)
        function varargout = state(action, varargin)
            persistent tokens nextToken enabled modes queues heads counts
            persistent directory serial nominalRates dataRates setupStatus pendingStatus
            capacity = 256;
            if isempty(nextToken)
                nextToken = uint32(0);
                tokens = zeros(1, 2, 'uint32');
                enabled = false(1, 2);
                modes = false(1, 2);
                queues = cell(capacity, 2);
                heads = ones(1, 2);
                counts = zeros(1, 2);
                directory = '';
                serial = '';
                nominalRates = zeros(1, 2);
                dataRates = zeros(1, 2);
                setupStatus = zeros(1, 2, 'int32');
                pendingStatus = zeros(1, 2, 'int32');
            end
            switch action
                case 'configure'
                    channel = varargin{3};
                    status = int32(0);
                    token = uint32(0);
                    if tokens(channel) ~= 0
                        status = int32(-2);
                        pendingStatus(channel) = status;
                    elseif any(tokens ~= 0) && ...
                            (~strcmp(directory, varargin{1}) || ~strcmp(serial, varargin{2}))
                        status = int32(-12);
                        setupStatus(channel) = status;
                    else
                        if nextToken == intmax('uint32')
                            nextToken = uint32(0);
                        end
                        nextToken = nextToken + uint32(1);
                        token = nextToken;
                        tokens(channel) = token;
                        modes(channel) = varargin{4};
                        nominalRates(channel) = varargin{5};
                        dataRates(channel) = varargin{6};
                        enabled(channel) = varargin{8};
                        directory = varargin{1};
                        serial = varargin{2};
                        heads(channel) = 1;
                        counts(channel) = 0;
                        queues(:, channel) = {[]};
                        setupStatus(channel) = 0;
                        pendingStatus(channel) = 0;
                    end
                    varargout = {token, status};
                case 'release'
                    token = varargin{1};
                    channel = find(tokens == token & tokens ~= 0, 1);
                    if ~isempty(channel)
                        tokens(channel) = 0;
                        counts(channel) = 0;
                        queues(:, channel) = {[]};
                        setupStatus(channel) = 0;
                        pendingStatus(channel) = 0;
                    end
                case 'send'
                    channel = varargin{1};
                    canfd = varargin{2};
                    message = varargin{3};
                    if canfd
                        valid = x280linux.can.isValidFDMessage(message);
                    else
                        valid = x280linux.can.isValidMessage(message);
                    end
                    if ~valid
                        varargout = {int32(-1)};
                        return
                    end
                    [status, pendingStatus(channel)] = channelStatus(channel, ...
                        canfd, tokens, modes, enabled, setupStatus, pendingStatus);
                    if status ~= 0
                        varargout = {status};
                        return
                    end
                    destination = 3 - channel;
                    % A disconnected or differently configured peer receives nothing.
                    if tokens(destination) == 0 || ~enabled(destination) || ...
                            modes(destination) ~= canfd || ...
                            nominalRates(destination) ~= nominalRates(channel) || ...
                            (canfd && message.BRS ~= 0 && dataRates(destination) ~= dataRates(channel))
                        varargout = {int32(0)};
                        return
                    end
                    if counts(destination) == capacity
                        varargout = {int32(-7)};
                        return
                    end
                    if message.Remote ~= 0
                        message.Data(:) = 0;
                    else
                        message.Data(double(message.Length) + 1:end) = 0;
                    end
                    tail = mod(heads(destination) + counts(destination) - 1, capacity) + 1;
                    queues{tail, destination} = message;
                    counts(destination) = counts(destination) + 1;
                    varargout = {int32(0)};
                case 'receive'
                    channel = varargin{1};
                    canfd = varargin{2};
                    if canfd
                        message = x280linux.can.emptyFDMessage();
                    else
                        message = x280linux.can.emptyMessage();
                    end
                    valid = false;
                    [status, pendingStatus(channel)] = channelStatus(channel, ...
                        canfd, tokens, modes, enabled, setupStatus, pendingStatus);
                    if status == 0 && counts(channel) > 0
                        message = queues{heads(channel), channel};
                        queues{heads(channel), channel} = [];
                        heads(channel) = mod(heads(channel), capacity) + 1;
                        counts(channel) = counts(channel) - 1;
                        valid = true;
                    end
                    varargout = {message, valid, status};
            end
        end
    end
end

function [status, remaining] = channelStatus(channel, canfd, tokens, modes, enabled, setupStatus, pendingStatus)
remaining = pendingStatus(channel);
if tokens(channel) == 0
    status = setupStatus(channel);
    if status == 0
        status = int32(-5);
    end
elseif modes(channel) ~= canfd
    status = int32(-13);
elseif ~enabled(channel)
    status = int32(-15);
else
    status = pendingStatus(channel);
    remaining = int32(0);
end
end
