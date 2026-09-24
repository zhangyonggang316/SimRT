classdef CanSent < matlab.System
    %CANSENT Queue one CAN or CAN FD frame for the configured TC1013 channel.
    %#codegen
    properties (Nontunable)
        % Channel CAN channel (1 or 2)
        Channel = 1
        % CANType Protocol and message bus type
        CANType = 'CAN'
    end

    properties (Hidden, Constant)
        CANTypeSet = matlab.system.StringSet({'CAN', 'CAN FD'});
    end

    methods
        function obj = CanSent(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end

    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Channel, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 1, '<=', 2});
        end

        function validateInputsImpl(obj, message, enable)
            if strcmp(obj.CANType, 'CAN FD')
                x280linux.can.validateFDMessage(message);
            else
                x280linux.can.validateMessage(message);
            end
            validateattributes(enable, {'logical'}, {'scalar'});
        end

        function status = stepImpl(obj, message, enable)
            status = int32(0);
            if enable
                if coder.target('MATLAB')
                    status = x280linux.can.Loopback.send( ...
                        obj.Channel, strcmp(obj.CANType, 'CAN FD'), message);
                elseif strcmp(obj.CANType, 'CAN FD')
                    status = x280linux.can.Native.sendFD(obj.Channel, message);
                else
                    status = x280linux.can.Native.send(obj.Channel, message);
                end
            end
        end

        function [message, enable] = getInputNamesImpl(~)
            message = 'Message';
            enable = 'Enable';
        end

        function name = getOutputNamesImpl(~)
            name = 'Status';
        end

        function type = getOutputDataTypeImpl(~)
            type = 'int32';
        end

        function size = getOutputSizeImpl(~)
            size = [1 1];
        end

        function complex = isOutputComplexImpl(~)
            complex = false;
        end

        function fixed = isOutputFixedSizeImpl(~)
            fixed = true;
        end

        function sampleTime = getSampleTimeImpl(obj)
            sampleTime = createSampleTime(obj, 'Type', 'Inherited');
        end

        function icon = getIconImpl(obj)
            icon = sprintf('CanSent\nCAN%d / %s', obj.Channel, obj.CANType);
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
            header = matlab.system.display.Header('x280linux.can.CanSent', ...
                'Title', 'TC1013 CanSent', 'ShowSourceLink', true);
        end

        function groups = getPropertyGroupsImpl
            groups = matlab.system.display.Section('Title', 'Transmit', ...
                'PropertyList', {'Channel', 'CANType'});
        end
    end
end
