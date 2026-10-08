classdef Native < coder.ExternalDependency
    %NATIVE Code generation interface to the Linux TC1013 runtime.
    %#codegen
    methods (Static)
        function name = getDescriptiveName(~)
            name = 'TC1013 CAN Linux runtime';
        end

        function supported = isSupportedContext(context)
            supported = context.isCodeGenTarget('rtw');
        end

        function updateBuildInfo(buildInfo, ~)
            targetRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            sourceFolder = fullfile(targetRoot, 'drivers', 'tc1013', 'src');
            buildInfo.addIncludePaths(sourceFolder);
            buildInfo.addIncludeFiles('simrt_tc1013_can.h', sourceFolder);
            buildInfo.addSourceFiles('simrt_tc1013_can.c', sourceFolder);
            buildInfo.addLinkFlags('-ldl -lpthread');
        end

        function token = configure(directory, serial, channel, canfd, baud, dataBaud, termination)
            coder.cinclude('simrt_tc1013_can.h');
            token = uint32(0);
            directoryC = [directory char(0)];
            serialC = [serial char(0)];
            % The runtime logs failures and retains them for channel Status outputs.
            coder.ceval('simrt_can_configure_channel', ...
                coder.rref(directoryC), coder.rref(serialC), uint8(channel), ...
                uint8(canfd), double(baud), double(dataBaud), ...
                uint8(termination), coder.wref(token));
        end

        function release(token)
            coder.cinclude('simrt_tc1013_can.h');
            coder.ceval('simrt_can_release', token);
        end

        function status = send(channel, message)
            coder.cinclude('simrt_tc1013_can.h');
            status = int32(0);
            if ~simrtlinux.can.isValidMessage(message)
                status = int32(-1);
                return
            end
            status = coder.ceval('simrt_can_send', uint8(channel), ...
                message.ID, message.Extended, message.Remote, message.Length, ...
                coder.rref(message.Data));
        end

        function status = sendFD(channel, message)
            coder.cinclude('simrt_tc1013_can.h');
            status = int32(0);
            if ~simrtlinux.can.isValidFDMessage(message)
                status = int32(-1);
                return
            end
            status = coder.ceval('simrt_can_send_fd', uint8(channel), ...
                message.ID, message.Extended, message.BRS, message.ESI, ...
                message.Length, coder.rref(message.Data));
        end

        function [message, valid, status] = receive(channel)
            coder.cinclude('simrt_tc1013_can.h');
            message = simrtlinux.can.emptyMessage();
            received = uint8(0);
            status = int32(0);
            status = coder.ceval('simrt_can_receive', uint8(channel), ...
                coder.wref(message.ID), coder.wref(message.Extended), ...
                coder.wref(message.Remote), coder.wref(message.Error), ...
                coder.wref(message.Length), coder.wref(message.Timestamp), ...
                coder.wref(message.Data), coder.wref(received));
            valid = received ~= 0;
        end

        function [message, valid, status] = receiveFD(channel)
            coder.cinclude('simrt_tc1013_can.h');
            message = simrtlinux.can.emptyFDMessage();
            received = uint8(0);
            status = int32(0);
            status = coder.ceval('simrt_can_receive_fd', uint8(channel), ...
                coder.wref(message.ID), coder.wref(message.Extended), ...
                coder.wref(message.BRS), coder.wref(message.ESI), ...
                coder.wref(message.Error), coder.wref(message.Length), ...
                coder.wref(message.Timestamp), coder.wref(message.Data), ...
                coder.wref(received));
            valid = received ~= 0;
            if valid
                message.ProtocolMode = uint8(1);
                message.DLC = simrtlinux.can.fdLengthToDLC(message.Length);
            end
        end
    end
end
