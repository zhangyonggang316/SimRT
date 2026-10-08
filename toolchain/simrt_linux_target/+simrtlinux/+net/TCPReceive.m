classdef TCPReceive < matlab.System
    %TCPRECEIVE Consume a bounded TCP chunk or one UDP datagram each step.
    %#codegen
    properties (Nontunable)
        Channel = 1
        BufferSize = 1024
        SampleTime = 0.001
    end
    methods
        function obj = TCPReceive(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            simrtlinux.net.validateChannel(obj.Channel);
            validateattributes(obj.BufferSize, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 1, '<=', 4096});
            validateattributes(obj.SampleTime, {'double'}, ...
                {'scalar', 'real', 'finite', 'positive'});
        end
        function count = getNumInputsImpl(~), count = 0; end
        function [data, length, valid, status] = stepImpl(obj)
            data = zeros(obj.BufferSize, 1, 'uint8');
            length = uint16(0);
            valid = false;
            status = int32(-11);
            if ~coder.target('MATLAB')
                [data, length, valid, status] = simrtlinux.net.Native.receive(obj.Channel, obj.BufferSize);
            end
        end
        function [data, length, valid, status] = getOutputNamesImpl(~)
            data = 'Data'; length = 'Length'; valid = 'Valid'; status = 'Status';
        end
        function [data, length, valid, status] = getOutputDataTypeImpl(~)
            data = 'uint8'; length = 'uint16'; valid = 'logical'; status = 'int32';
        end
        function [data, length, valid, status] = getOutputSizeImpl(obj)
            data = [obj.BufferSize 1]; length = [1 1]; valid = [1 1]; status = [1 1];
        end
        function [data, length, valid, status] = isOutputComplexImpl(~)
            data = false; length = false; valid = false; status = false;
        end
        function [data, length, valid, status] = isOutputFixedSizeImpl(~)
            data = true; length = true; valid = true; status = true;
        end
        function value = getSampleTimeImpl(obj)
            value = createSampleTime(obj, 'Type', 'Discrete', 'SampleTime', obj.SampleTime);
        end
        function icon = getIconImpl(obj)
            icon = sprintf('TCP / UDP Receive\nChannel %d', obj.Channel);
        end
    end
    methods (Static, Access=protected)
        function value = getSimulateUsingImpl, value = 'Interpreted execution'; end
        function value = showSimulateUsingImpl, value = true; end
        function value = getHeaderImpl
            value = matlab.system.display.Header('simrtlinux.net.TCPReceive', ...
                'Title', 'TCP / UDP Receive', 'ShowSourceLink', true);
        end
    end
end
