classdef DIOWrite < matlab.System
    %DIOWRITE Set logical output values; disabled steps do not access hardware.
    %#codegen
    methods (Access=protected)
        function validateInputsImpl(~,token,values,enable)
            validateattributes(token,{'uint32'},{'scalar','real'});
            validateattributes(values,{'logical'},{'vector','nonempty'});
            assert(numel(values)<=64,'simrt:dio:LineCount','At most 64 GPIO values are supported.');
            validateattributes(enable,{'logical'},{'scalar'});
        end
        function status=stepImpl(~,token,values,enable)
            status=int32(0);
            if enable
                if coder.target('MATLAB'), status=int32(-38);
                else, status=simrtlinux.dio.Native.write(token,uint8(values));
                end
            end
        end
        function [a,b,c]=getInputNamesImpl(~), a='Connection'; b='Values'; c='Enable'; end
        function a=getOutputNamesImpl(~), a='Status'; end
        function a=getOutputDataTypeImpl(~), a='int32'; end
        function a=getOutputSizeImpl(~), a=[1 1]; end
        function a=isOutputComplexImpl(~), a=false; end
        function a=isOutputFixedSizeImpl(~), a=true; end
        function value=getSampleTimeImpl(obj), value=createSampleTime(obj,'Type','Inherited'); end
        function value=getIconImpl(~), value='DIO Write'; end
    end
    methods (Static,Access=protected)
        function value=getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
