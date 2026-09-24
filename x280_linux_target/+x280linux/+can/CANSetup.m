classdef CANSetup < matlab.System
    %CANSETUP Configure one channel on the process-wide TC1013 adapter.
    %#codegen
    properties (Nontunable)
        % Channel CAN channel (1 or 2)
        Channel = 1
        % CANType Protocol
        CANType = 'CAN'
        % BaudRate Nominal bit rate (kbit/s)
        BaudRate = 500
        % DataBitRate CAN FD data bit rate (kbit/s)
        DataBitRate = 2000
        % Termination Enable internal termination
        Termination = true
        % SerialNumber Device serial number (empty selects first device)
        SerialNumber = ''
        % DriverDirectory Linux SDK directory
        DriverDirectory = '/home/zh/.local/lib/tscan'
        % SampleTime Sample time (s)
        SampleTime = 0.001
        % HostTransport MATLAB simulation transport
        HostTransport = 'Loopback'
    end

    properties (Hidden, Constant)
        CANTypeSet = matlab.system.StringSet({'CAN', 'CAN FD'});
        HostTransportSet = matlab.system.StringSet({'Loopback', 'Disabled'});
    end

    properties (Access=private)
        OwnershipToken = uint32(0)
    end

    methods
        function obj = CANSetup(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end

    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Channel, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 1, '<=', 2});
            validateattributes(obj.SerialNumber, {'char'}, {});
            assert(isempty(obj.SerialNumber) || isrow(obj.SerialNumber), ...
                'x280:can:SerialNumber', 'SerialNumber must be a character row.');
            validateattributes(obj.DriverDirectory, {'char'}, {'row', 'nonempty'});
            assert(obj.DriverDirectory(1) == '/', 'x280:can:DriverDirectory', ...
                'DriverDirectory must be an absolute Linux directory.');
            assert(~any(obj.SerialNumber == char(0)) && ...
                ~any(obj.DriverDirectory == char(0)), ...
                'x280:can:EmbeddedNull', 'Text parameters cannot contain NUL.');
            validateattributes(obj.BaudRate, {'double'}, ...
                {'scalar', 'real', 'finite', '>=', 5, '<=', 1000});
            validateattributes(obj.DataBitRate, {'double'}, ...
                {'scalar', 'real', 'finite', 'positive', '<=', 8000});
            assert(~strcmp(obj.CANType, 'CAN FD') || obj.DataBitRate >= obj.BaudRate, ...
                'x280:can:DataBitRate', ...
                'CAN FD DataBitRate must be at least BaudRate.');
            validateattributes(obj.Termination, {'logical'}, {'scalar'});
            validateattributes(obj.SampleTime, {'double'}, ...
                {'scalar', 'real', 'finite', 'positive'});
        end

        function setupImpl(obj)
            canfd = strcmp(obj.CANType, 'CAN FD');
            if coder.target('MATLAB')
                [obj.OwnershipToken, status] = x280linux.can.Loopback.configure( ...
                    obj.DriverDirectory, obj.SerialNumber, obj.Channel, canfd, ...
                    obj.BaudRate, obj.DataBitRate, obj.Termination, ...
                    strcmp(obj.HostTransport, 'Loopback'));
                if status ~= 0
                    warning('x280:can:SetupFailed', ...
                        'TC1013 CAN%d setup failed (status %d).', obj.Channel, status);
                end
            else
                obj.OwnershipToken = x280linux.can.Native.configure( ...
                    obj.DriverDirectory, obj.SerialNumber, obj.Channel, canfd, ...
                    obj.BaudRate, obj.DataBitRate, obj.Termination);
            end
        end

        function stepImpl(~)
        end

        function releaseImpl(obj)
            if obj.OwnershipToken ~= 0
                if coder.target('MATLAB')
                    x280linux.can.Loopback.release(obj.OwnershipToken);
                else
                    x280linux.can.Native.release(obj.OwnershipToken);
                end
            end
            obj.OwnershipToken = uint32(0);
        end

        function count = getNumInputsImpl(~)
            count = 0;
        end

        function count = getNumOutputsImpl(~)
            count = 0;
        end

        function sampleTime = getSampleTimeImpl(obj)
            sampleTime = createSampleTime(obj, 'Type', 'Discrete', ...
                'SampleTime', obj.SampleTime);
        end

        function inactive = isInactivePropertyImpl(obj, property)
            inactive = strcmp(property, 'DataBitRate') && strcmp(obj.CANType, 'CAN');
        end

        function icon = getIconImpl(obj)
            if strcmp(obj.CANType, 'CAN FD')
                icon = sprintf('CANSetup\nCAN%d / CAN FD\n%g / %g kbit/s', ...
                    obj.Channel, obj.BaudRate, obj.DataBitRate);
            else
                icon = sprintf('CANSetup\nCAN%d / CAN\n%g kbit/s', ...
                    obj.Channel, obj.BaudRate);
            end
        end
    end

    methods (Static, Access=protected)
        function simulation = getSimulateUsingImpl
            simulation = 'Interpreted execution';
        end

        function show = showSimulateUsingImpl
            show = true;
        end

        function header = getHeaderImpl
            header = matlab.system.display.Header('x280linux.can.CANSetup', ...
                'Title', 'TC1013 CANSetup', 'ShowSourceLink', true);
        end

        function groups = getPropertyGroupsImpl
            channel = matlab.system.display.Section('Title', 'Channel', ...
                'PropertyList', {'Channel', 'CANType', 'BaudRate', ...
                'DataBitRate', 'Termination'});
            device = matlab.system.display.Section('Title', 'Device', ...
                'PropertyList', {'SerialNumber', 'DriverDirectory'});
            execution = matlab.system.display.Section('Title', 'Execution', ...
                'PropertyList', {'SampleTime', 'HostTransport'});
            groups = [channel device execution];
        end
    end
end
