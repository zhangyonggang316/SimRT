classdef Native < coder.ExternalDependency
    %#codegen
    methods (Static)
        function name=getDescriptiveName(~), name='SimRT Linux GPIO v2'; end
        function yes=isSupportedContext(context), yes=context.isCodeGenTarget('rtw'); end
        function updateBuildInfo(buildInfo,~)
            root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            source=fullfile(root,'drivers','dio','src');
            buildInfo.addIncludePaths(source);
            buildInfo.addIncludeFiles({'simrt_dio.h','simrt_dio_platform.h','simrt_gpio_v2.h'},source);
            buildInfo.addSourceFiles('simrt_dio.c',source);
            buildInfo.addLinkFlags('-lpthread');
        end
        function [token,status]=open(device,offsets,output,activeLow,initial)
            coder.cinclude('simrt_dio.h');
            token=uint32(0); status=int32(0); deviceC=[device char(0)];
            status=coder.ceval('simrt_dio_open',coder.rref(deviceC),coder.rref(offsets), ...
                uint32(numel(offsets)),uint8(output),uint8(activeLow),coder.rref(initial),coder.wref(token));
        end
        function [values,status]=read(token,count)
            coder.cinclude('simrt_dio.h');
            values=zeros(count,1,'uint8'); status=int32(0);
            status=coder.ceval('simrt_dio_read',token,coder.wref(values),uint32(count));
        end
        function status=write(token,values)
            coder.cinclude('simrt_dio.h');
            status=int32(0);
            status=coder.ceval('simrt_dio_write',token,coder.rref(values),uint32(numel(values)));
        end
        function close(token)
            coder.cinclude('simrt_dio.h');
            coder.ceval('simrt_dio_close',token);
        end
    end
end
