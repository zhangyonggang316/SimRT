classdef DIORead < matlab.System
    %DIOREAD Read logical GPIO values in the Setup line-offset order.
    %#codegen
    properties (Nontunable)
        LineCount = 1
    end
    methods
        function obj=DIORead(varargin), setProperties(obj,nargin,varargin{:}); end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.LineCount,{'double'},{'scalar','real','integer','>=',1,'<=',64});
        end
        function validateInputsImpl(~,token), validateattributes(token,{'uint32'},{'scalar','real'}); end
        function [values,status]=stepImpl(obj,token)
            if coder.target('MATLAB')
                values=false(obj.LineCount,1); status=int32(-38);
            else
                [data,status]=simrtlinux.dio.Native.read(token,obj.LineCount);
                values=logical(data);
            end
        end
        function a=getInputNamesImpl(~), a='Connection'; end
        function [a,b]=getOutputNamesImpl(~), a='Values'; b='Status'; end
        function [a,b]=getOutputDataTypeImpl(~), a='logical'; b='int32'; end
        function [a,b]=getOutputSizeImpl(obj), a=[obj.LineCount 1]; b=[1 1]; end
        function [a,b]=isOutputComplexImpl(~), a=false; b=false; end
        function [a,b]=isOutputFixedSizeImpl(~), a=true; b=true; end
        function value=getSampleTimeImpl(obj), value=createSampleTime(obj,'Type','Inherited'); end
        function value=getIconImpl(~), value='DIO Read'; end
    end
    methods (Static,Access=protected)
        function value=getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
