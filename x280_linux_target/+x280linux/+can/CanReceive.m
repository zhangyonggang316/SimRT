classdef CanReceive < matlab.System
    %CANRECEIVE Read at most one configured-channel CAN/CAN FD frame per step.
    %#codegen
    properties (Nontunable)
        % Channel CAN channel (1 or 2)
        Channel = 1
        % CANType Protocol and message bus type
        CANType = 'CAN'
        % SampleTime Sample time (s)
        SampleTime = 0.001
    end

    properties (Hidden, Constant)
        CANTypeSet = matlab.system.StringSet({'CAN', 'CAN FD'});
    end

    methods
        function obj = CanReceive(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end

    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Channel, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 1, '<=', 2});
            validateattributes(obj.SampleTime, {'double'}, ...
                {'scalar', 'real', 'finite', 'positive'});
        end

        function count = getNumInputsImpl(~)
            count = 0;
        end

        function [message, valid, status] = stepImpl(obj)
            if coder.target('MATLAB')
                [message, valid, status] = x280linux.can.Loopback.receive( ...
                    obj.Channel, strcmp(obj.CANType, 'CAN FD'));
            elseif strcmp(obj.CANType, 'CAN FD')
                [message, valid, status] = x280linux.can.Native.receiveFD(obj.Channel);
            else
                [message, valid, status] = x280linux.can.Native.receive(obj.Channel);
            end
        end

        function [message, valid, status] = getOutputNamesImpl(~)
            message = 'Message';
            valid = 'Valid';
            status = 'Status';
        end

        function [message, valid, status] = getOutputDataTypeImpl(obj)
            if strcmp(obj.CANType, 'CAN FD')
                message = 'CAN_FD_MESSAGE_BUS';
            else
                message = 'CAN_MESSAGE_BUS';
            end
            valid = 'logical';
            status = 'int32';
        end

        function [message, valid, status] = getOutputSizeImpl(~)
            message = [1 1];
            valid = [1 1];
            status = [1 1];
        end

        function [message, valid, status] = isOutputComplexImpl(~)
            message = false;
            valid = false;
            status = false;
        end

        function [message, valid, status] = isOutputFixedSizeImpl(~)
            message = true;
            valid = true;
            status = true;
        end

        function sampleTime = getSampleTimeImpl(obj)
            sampleTime = createSampleTime(obj, 'Type', 'Discrete', ...
                'SampleTime', obj.SampleTime);
        end

        function icon = getIconImpl(obj)
            icon = sprintf('CanReceive\nCAN%d / %s', obj.Channel, obj.CANType);
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
            header = matlab.system.display.Header('x280linux.can.CanReceive', ...
                'Title', 'TC1013 CanReceive', 'ShowSourceLink', true);
        end

        function groups = getPropertyGroupsImpl
            groups = matlab.system.display.Section('Title', 'Receive', ...
                'PropertyList', {'Channel', 'CANType', 'SampleTime'});
        end
    end
end
