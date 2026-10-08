classdef TCPSetup < matlab.System
    %TCPSETUP Own a Linux TCP or UDP endpoint used by Sent and Receive blocks.
    %#codegen
    properties (Nontunable)
        Channel = 1
        Protocol = 'TCP'
        Role = 'Client'
        LocalAddress = '0.0.0.0'
        LocalPort = 0
        RemoteAddress = '127.0.0.1'
        RemotePort = 5000
        SampleTime = 0.001
    end
    properties (Hidden, Constant)
        ProtocolSet = matlab.system.StringSet({'TCP', 'UDP'});
        RoleSet = matlab.system.StringSet({'Client', 'Server'});
    end
    properties (Access=private)
        OwnershipToken = uint32(0)
        SetupStatus = int32(-11)
    end
    methods
        function obj = TCPSetup(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            simrtlinux.net.validateChannel(obj.Channel);
            simrtlinux.net.validateIPv4(obj.LocalAddress);
            simrtlinux.net.validateIPv4(obj.RemoteAddress);
            validateattributes(obj.LocalPort, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 0, '<=', 65535});
            validateattributes(obj.RemotePort, {'double'}, ...
                {'scalar', 'real', 'integer', '>=', 0, '<=', 65535});
            validateattributes(obj.SampleTime, {'double'}, ...
                {'scalar', 'real', 'finite', 'positive'});
            server = strcmp(obj.Protocol, 'TCP') && strcmp(obj.Role, 'Server');
            assert(~server || obj.LocalPort > 0, 'simrt:net:LocalPort', ...
                'TCP Server requires a nonzero LocalPort.');
            assert(server || (obj.RemotePort > 0 && ~strcmp(obj.RemoteAddress, '0.0.0.0')), ...
                'simrt:net:RemoteEndpoint', 'TCP Client and UDP require a remote IP and port.');
        end
        function setupImpl(obj)
            if coder.target('MATLAB')
                obj.SetupStatus = int32(-11);
            else
                [obj.OwnershipToken, obj.SetupStatus] = simrtlinux.net.Native.configure( ...
                    obj.Channel, strcmp(obj.Protocol, 'UDP'), strcmp(obj.Role, 'Server'), ...
                    obj.LocalAddress, obj.LocalPort, obj.RemoteAddress, obj.RemotePort);
            end
        end
        function status = stepImpl(obj)
            status = obj.SetupStatus;
            if ~coder.target('MATLAB') && obj.OwnershipToken ~= 0
                status = simrtlinux.net.Native.status(obj.Channel, obj.OwnershipToken);
            end
        end
        function releaseImpl(obj)
            if ~coder.target('MATLAB') && obj.OwnershipToken ~= 0
                simrtlinux.net.Native.release(obj.OwnershipToken);
            end
            obj.OwnershipToken = uint32(0);
        end
        function count = getNumInputsImpl(~), count = 0; end
        function name = getOutputNamesImpl(~), name = 'Status'; end
        function type = getOutputDataTypeImpl(~), type = 'int32'; end
        function size = getOutputSizeImpl(~), size = [1 1]; end
        function value = isOutputComplexImpl(~), value = false; end
        function value = isOutputFixedSizeImpl(~), value = true; end
        function value = getSampleTimeImpl(obj)
            value = createSampleTime(obj, 'Type', 'Discrete', 'SampleTime', obj.SampleTime);
        end
        function value = isInactivePropertyImpl(obj, property)
            server = strcmp(obj.Protocol, 'TCP') && strcmp(obj.Role, 'Server');
            value = (strcmp(property, 'Role') && strcmp(obj.Protocol, 'UDP')) || ...
                (server && any(strcmp(property, {'RemoteAddress', 'RemotePort'})));
        end
        function icon = getIconImpl(obj)
            icon = sprintf('%s Setup\nChannel %d', obj.Protocol, obj.Channel);
        end
    end
    methods (Static, Access=protected)
        function value = getSimulateUsingImpl, value = 'Interpreted execution'; end
        function value = showSimulateUsingImpl, value = true; end
        function value = getHeaderImpl
            value = matlab.system.display.Header('simrtlinux.net.TCPSetup', ...
                'Title', 'TCP / UDP Setup', 'ShowSourceLink', true);
        end
    end
end
