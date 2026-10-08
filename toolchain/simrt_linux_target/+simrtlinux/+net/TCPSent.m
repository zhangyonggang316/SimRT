classdef TCPSent < matlab.System
    %TCPSENT Queue up to 4096 bytes without waiting for the network.
    %#codegen
    properties (Nontunable)
        Channel = 1
    end
    methods
        function obj = TCPSent(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            simrtlinux.net.validateChannel(obj.Channel);
        end
        function validateInputsImpl(~, data, length, enable)
            validateattributes(data, {'uint8'}, {'real', 'vector', 'nonempty'});
            assert(numel(data) <= 4096, 'simrt:net:BufferSize', ...
                'Data must contain at most 4096 bytes.');
            validateattributes(length, {'uint16'}, {'scalar', 'real'});
            validateattributes(enable, {'logical'}, {'scalar'});
        end
        function status = stepImpl(obj, data, length, enable)
            status = int32(0);
            if enable
                if length == 0 || double(length) > numel(data)
                    status = int32(-1);
                elseif coder.target('MATLAB')
                    status = int32(-11);
                else
                    status = simrtlinux.net.Native.send(obj.Channel, data, length);
                end
            end
        end
        function [data, length, enable] = getInputNamesImpl(~)
            data = 'Data'; length = 'Length'; enable = 'Enable';
        end
        function name = getOutputNamesImpl(~), name = 'Status'; end
        function type = getOutputDataTypeImpl(~), type = 'int32'; end
        function size = getOutputSizeImpl(~), size = [1 1]; end
        function value = isOutputComplexImpl(~), value = false; end
        function value = isOutputFixedSizeImpl(~), value = true; end
        function value = getSampleTimeImpl(obj)
            value = createSampleTime(obj, 'Type', 'Inherited');
        end
        function icon = getIconImpl(obj)
            icon = sprintf('TCP / UDP Sent\nChannel %d', obj.Channel);
        end
    end
    methods (Static, Access=protected)
        function value = getSimulateUsingImpl, value = 'Interpreted execution'; end
        function value = showSimulateUsingImpl, value = true; end
        function value = getHeaderImpl
            value = matlab.system.display.Header('simrtlinux.net.TCPSent', ...
                'Title', 'TCP / UDP Sent', 'ShowSourceLink', true);
        end
    end
end
