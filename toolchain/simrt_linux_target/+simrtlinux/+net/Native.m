classdef Native < coder.ExternalDependency
    %NATIVE Build and call the bounded Linux socket runtime.
    %#codegen
    methods (Static)
        function name = getDescriptiveName(~), name = 'SimRT TCP UDP Linux runtime'; end
        function supported = isSupportedContext(context)
            supported = context.isCodeGenTarget('rtw');
        end
        function updateBuildInfo(buildInfo, ~)
            root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            source = fullfile(root, 'drivers', 'network', 'src');
            buildInfo.addIncludePaths(source);
            buildInfo.addIncludeFiles('simrt_network.h', source);
            buildInfo.addSourceFiles('simrt_network.c', source);
            buildInfo.addLinkFlags('-lpthread');
        end
        function [token, status] = configure(channel, udp, server, local, localPort, remote, remotePort)
            coder.cinclude('simrt_network.h');
            token = uint32(0); status = int32(0);
            localC = [local char(0)]; remoteC = [remote char(0)];
            status = coder.ceval('simrt_net_configure', uint8(channel), uint8(udp), ...
                uint8(server), coder.rref(localC), uint16(localPort), ...
                coder.rref(remoteC), uint16(remotePort), coder.wref(token));
        end
        function status = status(channel, token)
            coder.cinclude('simrt_network.h');
            status = int32(0);
            status = coder.ceval('simrt_net_status', uint8(channel), token);
        end
        function status = send(channel, data, length)
            coder.cinclude('simrt_network.h');
            status = int32(0);
            status = coder.ceval('simrt_net_send', uint8(channel), coder.rref(data), length);
        end
        function [data, length, valid, status] = receive(channel, capacity)
            coder.cinclude('simrt_network.h');
            data = zeros(capacity, 1, 'uint8');
            length = uint16(0); received = uint8(0); status = int32(0);
            status = coder.ceval('simrt_net_receive', uint8(channel), coder.wref(data), ...
                uint16(capacity), coder.wref(length), coder.wref(received));
            valid = received ~= 0;
        end
        function release(token)
            coder.cinclude('simrt_network.h');
            coder.ceval('simrt_net_release', token);
        end
    end
end
