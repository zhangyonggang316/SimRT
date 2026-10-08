classdef tSimRTNetworkObjects < matlab.unittest.TestCase
    methods (TestClassSetup)
        function targetPath(testCase)
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture( ...
                fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), ...
                'toolchain', 'simrt_linux_target')));
        end
    end
    methods (Test)
        function hostReportsDisabled(testCase)
            setupBlock = simrtlinux.net.TCPSetup;
            sender = simrtlinux.net.TCPSent;
            receiver = simrtlinux.net.TCPReceive('BufferSize', 32);
            testCase.addTeardown(@() release(setupBlock));
            testCase.addTeardown(@() release(sender));
            testCase.addTeardown(@() release(receiver));
            testCase.verifyEqual(setupBlock(), int32(-11));
            testCase.verifyEqual(sender(uint8((1:32)'), uint16(32), true), int32(-11));
            testCase.verifyEqual(sender(uint8((1:32)'), uint16(32), false), int32(0));
            [data, length, valid, status] = receiver();
            testCase.verifyEqual(data, zeros(32, 1, 'uint8'));
            testCase.verifyEqual(length, uint16(0));
            testCase.verifyFalse(valid);
            testCase.verifyEqual(status, int32(-11));
        end
        function lengthBoundsAreCheckedEveryStep(testCase)
            sender = simrtlinux.net.TCPSent;
            testCase.addTeardown(@() release(sender));
            testCase.verifyEqual(sender(uint8([1; 2]), uint16(2), false), int32(0));
            testCase.verifyEqual(sender(uint8([1; 2]), uint16(3), true), int32(-1));
            testCase.verifyEqual(sender(uint8([1; 2]), uint16(0), true), int32(-1));
        end
        function malformedAddressesAreRejected(testCase)
            invalid = {'1.2.3', '256.1.1.1', '01.2.3.4', '1.2..4', '1.2.3.4;command'};
            for index = 1:numel(invalid)
                testCase.verifyError(@() simrtlinux.net.validateIPv4(invalid{index}), 'simrt:net:IPv4');
            end
            testCase.verifyWarningFree(@() simrtlinux.net.validateIPv4('0.0.0.0'));
            testCase.verifyWarningFree(@() simrtlinux.net.validateIPv4('192.168.1.254'));
        end
        function serverRequiresLocalPort(testCase)
            block = simrtlinux.net.TCPSetup('Role', 'Server');
            testCase.addTeardown(@() release(block));
            testCase.verifyError(@() block(), 'simrt:net:LocalPort');
        end
        function udpRequiresDestination(testCase)
            block = simrtlinux.net.TCPSetup('Protocol', 'UDP', 'RemotePort', 0);
            testCase.addTeardown(@() release(block));
            testCase.verifyError(@() block(), 'simrt:net:RemoteEndpoint');
        end
    end
end
