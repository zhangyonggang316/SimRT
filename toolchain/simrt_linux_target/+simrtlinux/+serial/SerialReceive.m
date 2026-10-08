classdef SerialReceive < matlab.System
    %SERIALRECEIVE Return available bytes; Length=0 means no new data.
    %#codegen
    properties (Nontunable)
        BufferSize = 256
    end
    methods
        function obj=SerialReceive(varargin), setProperties(obj,nargin,varargin{:}); end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.BufferSize,{'double'},{'scalar','integer','positive','<=',65536});
        end
        function validateInputsImpl(~,token), validateattributes(token,{'uint32'},{'scalar'}); end
        function [data,count,status] = stepImpl(obj,token)
            if coder.target('MATLAB')
                data=zeros(obj.BufferSize,1,'uint8'); count=uint32(0); status=int32(-38);
            else
                [data,count,status]=simrtlinux.serial.Native.receive(token,obj.BufferSize);
            end
        end
        function a=getInputNamesImpl(~), a='Connection'; end
        function [a,b,c]=getOutputNamesImpl(~), a='Data'; b='Length'; c='Status'; end
        function [a,b,c]=getOutputDataTypeImpl(~), a='uint8'; b='uint32'; c='int32'; end
        function [a,b,c]=getOutputSizeImpl(obj), a=[obj.BufferSize 1]; b=[1 1]; c=[1 1]; end
        function [a,b,c]=isOutputComplexImpl(~), a=false; b=false; c=false; end
        function [a,b,c]=isOutputFixedSizeImpl(~), a=true; b=true; c=true; end
        function value=getSampleTimeImpl(obj), value=createSampleTime(obj,'Type','Inherited'); end
        function value=getIconImpl(~), value='Serial Receive'; end
    end
    methods (Static,Access=protected)
        function value=getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
