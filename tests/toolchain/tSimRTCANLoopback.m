classdef tSimRTCANLoopback < sltest.TestCase
    %TSIMRTCANLOOPBACK Verify the delivered model through CAN Pack/Unpack.
    properties (TestParameter)
        channel = struct( ...
            'CAN1', struct('name', 'CAN1', 'id', uint32(514), ...
                'amplitude', 7, 'bias', -2, 'frequency', 20), ...
            'CAN2', struct('name', 'CAN2', 'id', uint32(257), ...
                'amplitude', 3, 'bias', 5, 'frequency', 40))
    end

    methods (TestClassSetup)
        function prepareModel(testCase)
            root = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), ...
                'toolchain', 'simrt_linux_target');
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(root));
            setupSimRTLinuxTarget;
            locations = setupSimRTCANLibrary;
            openForTest(testCase, locations.TestModel);
        end
    end

    methods (Test)
        function setupBlocksHaveNoPortsAndOwnSeparateChannels(testCase, channel)
            block = ['simrt_can_loopback/Setup_' channel.name];
            ports = get_param(block, 'PortHandles');
            testCase.verifyEmpty(ports.Inport);
            testCase.verifyEmpty(ports.Outport);
            testCase.verifyEqual(get_param(block, 'System'), 'simrtlinux.can.CANSetup');
            testCase.verifyEqual(get_param(block, 'Channel'), channel.name(end));
            testCase.verifyEqual(get_param(block, 'CANType'), 'CAN');
        end

        function executionOrderInitializesBothChannelsBeforeTransmission(testCase)
            names = {'Setup_CAN1', 'Setup_CAN2', 'Send_CAN1', ...
                'Send_CAN2', 'Receive_CAN1', 'Receive_CAN2'};
            priorities = cellfun(@(name) str2double(get_param( ...
                ['simrt_can_loopback/' name], 'Priority')), names);
            testCase.verifyEqual(priorities, [-100 -99 -50 -49 0 1]);
            testCase.verifyEqual(get_param('simrt_can_loopback', 'FixedStep'), '0.001');
        end

        function usesOfficialCanPackAndUnpackBlocks(testCase, channel)
            pack = ['simrt_can_loopback/Pack_' channel.name];
            unpack = ['simrt_can_loopback/Unpack_' channel.name];
            testCase.verifyEqual(get_param(pack, 'ReferenceBlock'), ...
                'canmsglib/CAN Pack');
            testCase.verifyEqual(get_param(unpack, 'ReferenceBlock'), ...
                'canmsglib/CAN Unpack');
            testCase.verifyEqual(get_param(pack, 'BusOutput'), 'on');
        end

        function receivesOtherChannelEveryMillisecond(testCase, channel)
            input = Simulink.SimulationInput('simrt_can_loopback');
            input = input.setModelParameter('StopTime', '0.02', ...
                'SimulationMode', 'normal');
            % Distinct double waveforms verify both payload integrity and routing.
            blocks = {'simrt_can_loopback/CAN1set', 'simrt_can_loopback/CAN2set'};
            parameters = {'Amplitude', 'Bias', 'Frequency', 'Phase', 'SampleTime'};
            values = {'3', '5', '40', '0', '0.001'; ...
                      '7', '-2', '20', '0', '0.001'};
            for source = 1:numel(blocks)
                for parameter = 1:numel(parameters)
                    input = input.setBlockParameter(blocks{source}, ...
                        parameters{parameter}, values{source, parameter});
                end
            end

            output = testCase.simulate(input);
            valid = samples(output, [channel.name '_Valid']);
            data = samples(output, [channel.name '_Data']);
            ids = samples(output, [channel.name '_ID']);
            times = output.yout.getElement([channel.name '_Valid']).Values.Time;

            testCase.verifyEqual(times, (0:0.001:0.02)', ...
                'AbsTol', 1e-12);
            testCase.verifyEqual(valid, true(21, 1));
            testCase.verifyEqual(ids, repmat(channel.id, 21, 1));
            expected = channel.bias + channel.amplitude * sin(channel.frequency * times);
            testCase.verifyEqual(data, expected, 'AbsTol', 1e-12);
            testCase.verifyEqual(samples(output, [channel.name '_TxStatus']), ...
                zeros(21, 1, 'int32'));
            testCase.verifyEqual(samples(output, [channel.name '_RxStatus']), ...
                zeros(21, 1, 'int32'));
            outputNames = string(output.yout.getElementNames);
            testCase.verifyEqual(sort(outputNames(:)), ...
                sort(["CAN1_TxStatus", "CAN2_TxStatus", "CAN1_RxStatus", ...
                "CAN2_RxStatus", "CAN1_Valid", "CAN2_Valid", ...
                "CAN1_ID", "CAN2_ID", "CAN1_Data", "CAN2_Data"]'));
        end
    end
end

function openForTest(testCase, file)
if ~bdIsLoaded('simrt_can_loopback')
    load_system(file);
    testCase.addTeardown(@() close_system('simrt_can_loopback', 0));
end
end

function values = samples(output, name)
series = output.yout.getElement(name).Values;
first = getdatasamples(series, 1);
values = zeros(numel(series.Time), numel(first), 'like', first);
for index = 1:numel(series.Time)
    value = getdatasamples(series, index);
    values(index, :) = value(:).';
end
end
