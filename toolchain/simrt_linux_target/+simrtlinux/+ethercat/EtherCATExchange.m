classdef EtherCATExchange < matlab.System
    %ETHERCATEXCHANGE Exchange one complete default-mapped PDO image per step.
    %#codegen
    properties (Nontunable)
        Interface = 'eth1'
        ExpectedSlaves = 1
        OutputBytes = 8
        InputBytes = 8
        ReceiveTimeoutUs = 500
        SampleTime = 0.001
    end
    properties (Access=private)
        Token=uint32(0)
        ExpectedWKC=int32(0)
        SetupStatus=int32(-38)
    end
    methods
        function obj=EtherCATExchange(varargin), setProperties(obj,nargin,varargin{:}); end
    end
    methods (Access=protected)
        function validatePropertiesImpl(obj)
            validateattributes(obj.Interface,{'char'},{'row','nonempty'});
            assert(numel(obj.Interface)<16 && ~any(obj.Interface==char(0)), ...
                'simrt:ethercat:Interface','Use a Linux interface name of at most 15 characters.');
            validateattributes(obj.ExpectedSlaves,{'double'},{'scalar','integer','>=',1,'<',200});
            validateattributes(obj.OutputBytes,{'double'},{'scalar','integer','>=',0,'<=',65536});
            validateattributes(obj.InputBytes,{'double'},{'scalar','integer','>=',0,'<=',65536});
            assert(obj.OutputBytes+obj.InputBytes>0,'simrt:ethercat:EmptyPDO','At least one PDO direction is required.');
            validateattributes(obj.ReceiveTimeoutUs,{'double'},{'scalar','integer','positive','<=',1000000});
            validateattributes(obj.SampleTime,{'double'},{'scalar','real','finite','positive'});
            assert(obj.ReceiveTimeoutUs<obj.SampleTime*1e6, ...
                'simrt:ethercat:Timeout','Receive timeout must be shorter than the sample period.');
        end
        function validateInputsImpl(obj,outputs)
            validateattributes(outputs,{'uint8'},{'vector','numel',max(1,obj.OutputBytes)});
        end
        function setupImpl(obj,~)
            if ~coder.target('MATLAB')
                [obj.Token,obj.ExpectedWKC,obj.SetupStatus]=simrtlinux.ethercat.Native.open( ...
                    obj.Interface,obj.OutputBytes,obj.InputBytes,obj.ExpectedSlaves,obj.ReceiveTimeoutUs);
            end
        end
        function [inputs,wkc,expected,status]=stepImpl(obj,outputs)
            inputs=zeros(max(1,obj.InputBytes),1,'uint8');
            wkc=int32(0); expected=obj.ExpectedWKC; status=obj.SetupStatus;
            if ~coder.target('MATLAB') && obj.SetupStatus==0
                [inputs,wkc,status]=simrtlinux.ethercat.Native.exchange(obj.Token,outputs,max(1,obj.InputBytes));
            end
        end
        function releaseImpl(obj)
            if ~coder.target('MATLAB'), simrtlinux.ethercat.Native.close(obj.Token); end
            obj.Token=uint32(0);
        end
        function a=getInputNamesImpl(~), a='Outputs'; end
        function [a,b,c,d]=getOutputNamesImpl(~), a='Inputs'; b='WKC'; c='ExpectedWKC'; d='Status'; end
        function [a,b,c,d]=getOutputDataTypeImpl(~), a='uint8'; b='int32'; c='int32'; d='int32'; end
        function [a,b,c,d]=getOutputSizeImpl(obj), a=[max(1,obj.InputBytes) 1]; b=[1 1]; c=[1 1]; d=[1 1]; end
        function [a,b,c,d]=isOutputComplexImpl(~), a=false; b=false; c=false; d=false; end
        function [a,b,c,d]=isOutputFixedSizeImpl(~), a=true; b=true; c=true; d=true; end
        function value=getSampleTimeImpl(obj)
            value=createSampleTime(obj,'Type','Discrete','SampleTime',obj.SampleTime);
        end
        function value=getIconImpl(obj), value=sprintf('EtherCAT PDO Exchange\n%s / %d slaves',obj.Interface,obj.ExpectedSlaves); end
    end
    methods (Static,Access=protected)
        function value=getSimulateUsingImpl, value='Interpreted execution'; end
    end
end
