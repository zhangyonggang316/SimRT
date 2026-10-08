classdef DIOSetup < matlab.System
    %DIOSETUP Own Linux GPIO character-device v2 lines in the listed order.
    %#codegen
    properties (Nontunable)
        Device = '/dev/gpiochip0'
        LineOffsets = 0
        Direction = 'Input'
        ActiveLow = false
        InitialValues = false
        SampleTime = 0.001
    end
    properties (Hidden, Constant)
        DirectionSet = matlab.system.StringSet({'Input', 'Output'});
    end
    properties (Access=private)
        Token = uint32(0)
        Status = int32(-38)
    end
    methods
        function obj = DIOSetup(varargin), setProperties(obj,nargin,varargin{:}); end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Device,{'char'},{'row','nonempty'});
            assert(strncmp(obj.Device,'/dev/',5) && numel(obj.Device)<256 && ...
                ~any(obj.Device==char(0)),'simrt:dio:Device','Use a Linux /dev/ GPIO chip device.');
            validateattributes(obj.LineOffsets,{'double'}, ...
                {'vector','nonempty','real','finite','integer','>=',0,'<=',double(intmax('uint32'))});
            assert(numel(obj.LineOffsets)<=64 && numel(unique(obj.LineOffsets))==numel(obj.LineOffsets), ...
                'simrt:dio:LineOffsets','Select 1 to 64 distinct GPIO line offsets.');
            validateattributes(obj.ActiveLow,{'logical'},{'scalar'});
            validateattributes(obj.InitialValues,{'logical'},{'vector','nonempty'});
            assert(isscalar(obj.InitialValues) || numel(obj.InitialValues)==numel(obj.LineOffsets), ...
                'simrt:dio:InitialValues','InitialValues must be scalar or match LineOffsets.');
            validateattributes(obj.SampleTime,{'double'},{'scalar','real','finite','positive'});
        end
        function setupImpl(obj)
            if coder.target('MATLAB')
                obj.Token=uint32(0); obj.Status=int32(-38);
            else
                count=numel(obj.LineOffsets);
                initial=zeros(count,1,'uint8');
                if isscalar(obj.InitialValues)
                    initial(:)=uint8(obj.InitialValues);
                else
                    initial(:)=uint8(obj.InitialValues(:));
                end
                [obj.Token,obj.Status]=simrtlinux.dio.Native.open(obj.Device, ...
                    uint32(obj.LineOffsets(:)),strcmp(obj.Direction,'Output'),obj.ActiveLow,initial);
            end
        end
        function [token,status]=stepImpl(obj), token=obj.Token; status=obj.Status; end
        function releaseImpl(obj)
            if ~coder.target('MATLAB'), simrtlinux.dio.Native.close(obj.Token); end
            obj.Token=uint32(0);
        end
        function [a,b]=getOutputNamesImpl(~), a='Connection'; b='Status'; end
        function [a,b]=getOutputDataTypeImpl(~), a='uint32'; b='int32'; end
        function [a,b]=getOutputSizeImpl(~), a=[1 1]; b=[1 1]; end
        function [a,b]=isOutputComplexImpl(~), a=false; b=false; end
        function [a,b]=isOutputFixedSizeImpl(~), a=true; b=true; end
        function value=getSampleTimeImpl(obj)
            value=createSampleTime(obj,'Type','Discrete','SampleTime',obj.SampleTime);
        end
        function value=getIconImpl(obj), value=sprintf('DIO Setup\n%s\n%s',obj.Device,obj.Direction); end
        function value=isInactivePropertyImpl(obj,property)
            value=strcmp(property,'InitialValues') && strcmp(obj.Direction,'Input');
        end
    end
    methods (Static,Access=protected)
        function value=getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
