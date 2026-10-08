classdef Native < coder.ExternalDependency
    %#codegen
    methods (Static)
        function name=getDescriptiveName(~), name='SimRT SOEM EtherCAT master'; end
        function yes=isSupportedContext(context), yes=context.isCodeGenTarget('rtw'); end
        function updateBuildInfo(buildInfo,~)
            root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            driver=fullfile(root,'drivers','ethercat');
            source=fullfile(driver,'src');
            vendor=fullfile(driver,'vendor','soem');
            assert(isfile(fullfile(vendor,'soem','ethercat.h')), ...
                'simrt:ethercat:MissingSOEM','Pinned SOEM v1.4.0 sources are missing from drivers/ethercat/vendor/soem.');
            folders={source,fullfile(vendor,'soem'),fullfile(vendor,'osal'), ...
                fullfile(vendor,'osal','linux'),fullfile(vendor,'oshw','linux')};
            for k=1:numel(folders)
                buildInfo.addIncludePaths(folders{k});
                headers=dir(fullfile(folders{k},'*.h'));
                for j=1:numel(headers), buildInfo.addIncludeFiles(headers(j).name,folders{k}); end
                sources=dir(fullfile(folders{k},'*.c'));
                for j=1:numel(sources), buildInfo.addSourceFiles(sources(j).name,folders{k}); end
            end
            buildInfo.addDefines('_DEFAULT_SOURCE');
            buildInfo.addLinkFlags('-lpthread -lrt');
        end
        function [token,expected,status]=open(interface,outputs,inputs,slaves,timeout)
            coder.cinclude('simrt_ethercat.h');
            token=uint32(0); expected=int32(0); status=int32(0);
            interfaceC=[interface char(0)];
            status=coder.ceval('simrt_ethercat_open',coder.rref(interfaceC), ...
                uint32(outputs),uint32(inputs),uint32(slaves),uint32(timeout), ...
                coder.wref(token),coder.wref(expected));
        end
        function [inputs,wkc,status]=exchange(token,outputs,inputCapacity)
            coder.cinclude('simrt_ethercat.h');
            inputs=zeros(inputCapacity,1,'uint8'); wkc=int32(0); status=int32(0);
            status=coder.ceval('simrt_ethercat_exchange',token,coder.rref(outputs), ...
                uint32(numel(outputs)),coder.wref(inputs),uint32(inputCapacity),coder.wref(wkc));
        end
        function close(token)
            coder.cinclude('simrt_ethercat.h');
            coder.ceval('simrt_ethercat_close',token);
        end
    end
end
