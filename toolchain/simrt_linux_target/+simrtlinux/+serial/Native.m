classdef Native < coder.ExternalDependency
    %#codegen
    methods (Static)
        function name = getDescriptiveName(~), name = 'SimRT POSIX serial'; end
        function yes = isSupportedContext(context), yes = context.isCodeGenTarget('rtw'); end
        function updateBuildInfo(buildInfo, ~)
            root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            source = fullfile(root, 'drivers', 'serial', 'src');
            buildInfo.addIncludePaths(source);
            buildInfo.addIncludeFiles('simrt_serial.h', source);
            buildInfo.addSourceFiles('simrt_serial.c', source);
            buildInfo.addLinkFlags('-lpthread');
        end
        function [token, status] = open(device, baud, bits, parity, stops, mode, rts, before, after)
            coder.cinclude('simrt_serial.h');
            token = uint32(0); status = int32(0);
            deviceC = [device char(0)];
            status = coder.ceval('simrt_serial_open', coder.rref(deviceC), ...
                uint32(baud), uint8(bits), uint8(parity), uint8(stops), ...
                uint8(mode), uint8(rts), uint32(before), uint32(after), coder.wref(token));
        end
        function [sent, status] = send(token, data, length)
            coder.cinclude('simrt_serial.h');
            sent = uint32(0); status = int32(0);
            status = coder.ceval('simrt_serial_send', token, coder.rref(data), ...
                length, uint32(numel(data)), coder.wref(sent));
        end
        function [data, count, status] = receive(token, capacity)
            coder.cinclude('simrt_serial.h');
            data = zeros(capacity, 1, 'uint8'); count = uint32(0); status = int32(0);
            status = coder.ceval('simrt_serial_receive', token, coder.wref(data), ...
                uint32(capacity), coder.wref(count));
        end
        function close(token)
            coder.cinclude('simrt_serial.h');
            coder.ceval('simrt_serial_close', token);
        end
    end
end
