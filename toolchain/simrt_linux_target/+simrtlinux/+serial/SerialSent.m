classdef SerialSent < matlab.System
    %SERIALSENT Send bytes without blocking; Sent reports partial writes.
    %#codegen
    methods (Access=protected)
        function validateInputsImpl(~,token,data,length,enable)
            validateattributes(token,{'uint32'},{'scalar'});
            validateattributes(data,{'uint8'},{'vector','nonempty','<=',255});
            assert(numel(data)<=65536,'simrt:serial:Size','Maximum buffer size is 65536 bytes.');
            validateattributes(length,{'uint32'},{'scalar'});
            validateattributes(enable,{'logical'},{'scalar'});
        end
        function [sent,status] = stepImpl(~,token,data,length,enable)
            sent=uint32(0); status=int32(0);
            if enable
                if length > numel(data), status=int32(-22);
                elseif coder.target('MATLAB'), status=int32(-38);
                else, [sent,status]=simrtlinux.serial.Native.send(token,data,length);
                end
            end
        end
        function [a,b,c,d] = getInputNamesImpl(~), a='Connection'; b='Data'; c='Length'; d='Enable'; end
        function [a,b] = getOutputNamesImpl(~), a='Sent'; b='Status'; end
        function [a,b] = getOutputDataTypeImpl(~), a='uint32'; b='int32'; end
        function [a,b] = getOutputSizeImpl(~), a=[1 1]; b=[1 1]; end
        function [a,b] = isOutputComplexImpl(~), a=false; b=false; end
        function [a,b] = isOutputFixedSizeImpl(~), a=true; b=true; end
        function value = getSampleTimeImpl(obj), value=createSampleTime(obj,'Type','Inherited'); end
        function value = getIconImpl(~), value='Serial Sent'; end
    end
    methods (Static,Access=protected)
        function value = getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
