classdef SerialSetup < matlab.System
    %SERIALSETUP Own a Linux serial port and publish its connection token.
    %#codegen
    properties (Nontunable)
        Device = '/dev/ttyS0'
        BaudRate = 115200
        DataBits = 8
        Parity = 'None'
        StopBits = 1
        Mode = 'RS232'
        RS485Direction = 'Hardware auto'
        RTSOnSend = true
        DelayBeforeSendMs = 0
        DelayAfterSendMs = 0
        SampleTime = 0.001
    end
    properties (Hidden, Constant)
        ParitySet = matlab.system.StringSet({'None', 'Odd', 'Even'});
        ModeSet = matlab.system.StringSet({'RS232', 'RS485'});
        RS485DirectionSet = matlab.system.StringSet({'Hardware auto', 'Linux RTS'});
    end
    properties (Access=private)
        Token = uint32(0)
        Status = int32(-38)
    end
    methods
        function obj = SerialSetup(varargin), setProperties(obj,nargin,varargin{:}); end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Device, {'char'}, {'row','nonempty'});
            assert(strncmp(obj.Device,'/dev/',5) && numel(obj.Device) < 256 && ...
                ~any(obj.Device == char(0)), 'simrt:serial:Device', 'Use a Linux /dev/ serial device.');
            validateattributes(obj.BaudRate,{'double'},{'scalar','real','finite','positive'});
            assert(any(obj.BaudRate == [1200 2400 4800 9600 19200 38400 57600 115200 230400 460800 921600]), ...
                'simrt:serial:BaudRate', 'Unsupported standard baud rate.');
            validateattributes(obj.DataBits,{'double'},{'scalar','integer','>=',5,'<=',8});
            validateattributes(obj.StopBits,{'double'},{'scalar','integer','>=',1,'<=',2});
            validateattributes(obj.RTSOnSend,{'logical'},{'scalar'});
            validateattributes(obj.DelayBeforeSendMs,{'double'},{'scalar','integer','>=',0,'<=',1000});
            validateattributes(obj.DelayAfterSendMs,{'double'},{'scalar','integer','>=',0,'<=',1000});
            validateattributes(obj.SampleTime,{'double'},{'scalar','real','finite','positive'});
        end
        function setupImpl(obj)
            if coder.target('MATLAB')
                obj.Token = uint32(0); obj.Status = int32(-38);
            else
                parity = double(strcmp(obj.Parity,'Odd')) + 2*double(strcmp(obj.Parity,'Even'));
                mode = double(strcmp(obj.Mode,'RS485')) * (1 + double(strcmp(obj.RS485Direction,'Linux RTS')));
                [obj.Token,obj.Status] = simrtlinux.serial.Native.open(obj.Device, obj.BaudRate, ...
                    obj.DataBits, parity, obj.StopBits, mode, obj.RTSOnSend, ...
                    obj.DelayBeforeSendMs, obj.DelayAfterSendMs);
            end
        end
        function [token,status] = stepImpl(obj), token=obj.Token; status=obj.Status; end
        function releaseImpl(obj)
            if ~coder.target('MATLAB'), simrtlinux.serial.Native.close(obj.Token); end
            obj.Token=uint32(0);
        end
        function [a,b] = getOutputNamesImpl(~), a='Connection'; b='Status'; end
        function [a,b] = getOutputDataTypeImpl(~), a='uint32'; b='int32'; end
        function [a,b] = getOutputSizeImpl(~), a=[1 1]; b=[1 1]; end
        function [a,b] = isOutputComplexImpl(~), a=false; b=false; end
        function [a,b] = isOutputFixedSizeImpl(~), a=true; b=true; end
        function value = getSampleTimeImpl(obj)
            value=createSampleTime(obj,'Type','Discrete','SampleTime',obj.SampleTime);
        end
        function value = getIconImpl(obj), value=sprintf('Serial Setup\n%s\n%s',obj.Device,obj.Mode); end
    end
    methods (Static,Access=protected)
        function value = getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
