classdef tX280CANObjects < matlab.unittest.TestCase
    %TX280CANOBJECTS Channel ownership, bus contracts, and bounded simulation.
    properties (TestParameter)
        senderChannel = {1, 2}
        canType = {'CAN', 'CAN FD'}
        invalidMessage = struct( ...
            'length', struct('field', 'Length', 'value', uint8(9)), ...
            'standardID', struct('field', 'ID', 'value', uint32(2048)), ...
            'extendedFlag', struct('field', 'Extended', 'value', uint8(2)), ...
            'remoteFlag', struct('field', 'Remote', 'value', uint8(2)), ...
            'errorFrame', struct('field', 'Error', 'value', uint8(1)))
        invalidFDMessage = struct( ...
            'length', struct('field', 'Length', 'value', uint8(9)), ...
            'dlcMismatch', struct('field', 'DLC', 'value', uint8(14)), ...
            'protocol', struct('field', 'ProtocolMode', 'value', uint8(0)), ...
            'remote', struct('field', 'Remote', 'value', uint8(1)), ...
            'brs', struct('field', 'BRS', 'value', uint8(2)), ...
            'esi', struct('field', 'ESI', 'value', uint8(2)), ...
            'reserved', struct('field', 'Reserved', 'value', uint32(1)))
        fdLength = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64}
    end

    methods (TestClassSetup)
        function addTargetPath(testCase)
            root = fileparts(fileparts(mfilename('fullpath')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(root));
        end
    end

    methods (Test)
        function setupHasNoPorts(testCase)
            setup1 = x280linux.can.CANSetup;
            testCase.addTeardown(@() release(setup1));
            testCase.verifyEqual(getNumInputs(setup1), 0);
            testCase.verifyEqual(getNumOutputs(setup1), 0);
            testCase.verifyWarningFree(@() setup1());
            testCase.verifyTrue(isLocked(setup1));
        end

        function messagesCrossChannels(testCase, senderChannel, canType)
            [sender, receiver] = createObjects(testCase, senderChannel, canType);
            message = exampleMessage(canType);
            status = sender(message, true);
            [received, valid, receiveStatus] = receiver();
            [empty, emptyValid, emptyStatus] = receiver();
            testCase.verifyEqual(status, int32(0));
            testCase.verifyEqual(receiveStatus, int32(0));
            testCase.verifyTrue(valid);
            testCase.verifyEqual(received, message);
            testCase.verifyFalse(emptyValid);
            testCase.verifyEqual(emptyStatus, int32(0));
            testCase.verifyEqual(empty, blankMessage(canType));
        end

        function disabledSendDoesNotQueue(testCase)
            [sender, receiver] = createObjects(testCase, 1, 'CAN');
            status = sender(exampleMessage('CAN'), false);
            [~, valid, receiveStatus] = receiver();
            testCase.verifyEqual(status, int32(0));
            testCase.verifyFalse(valid);
            testCase.verifyEqual(receiveStatus, int32(0));
        end

        function boundedQueuePreservesFifo(testCase, canType)
            [sender, receiver] = createObjects(testCase, 1, canType);
            fillQueue(sender, canType);
            fullStatus = sender(exampleMessage(canType), true);
            [first, valid] = receiver();
            retryStatus = sender(exampleMessage(canType), true);
            [second, secondValid] = receiver();
            testCase.verifyEqual(fullStatus, int32(-7));
            testCase.verifyTrue(valid);
            testCase.verifyEqual(first.ID, uint32(1));
            testCase.verifyEqual(retryStatus, int32(0));
            testCase.verifyTrue(secondValid);
            testCase.verifyEqual(second.ID, uint32(2));
        end

        function invalidClassicFramesAreRejected(testCase, invalidMessage)
            [sender, receiver] = createObjects(testCase, 1, 'CAN');
            message = exampleMessage('CAN');
            message.(invalidMessage.field) = invalidMessage.value;
            status = sender(message, true);
            [~, valid] = receiver();
            testCase.verifyEqual(status, int32(-1));
            testCase.verifyFalse(valid);
        end

        function invalidFDFramesAreRejected(testCase, invalidFDMessage)
            [sender, receiver] = createObjects(testCase, 1, 'CAN FD');
            message = exampleMessage('CAN FD');
            message.(invalidFDMessage.field) = invalidFDMessage.value;
            status = sender(message, true);
            [~, valid] = receiver();
            testCase.verifyEqual(status, int32(-1));
            testCase.verifyFalse(valid);
        end

        function fdLengthsKeepExactDlcAndPayload(testCase, fdLength)
            [sender, receiver] = createObjects(testCase, 1, 'CAN FD');
            message = exampleMessage('CAN FD');
            message.Length = uint8(fdLength);
            [message.DLC, validLength] = x280linux.can.fdLengthToDLC(message.Length);
            expected = message;
            expected.Data(fdLength + 1:end) = 0;
            status = sender(message, true);
            [received, valid] = receiver();
            testCase.verifyTrue(validLength);
            testCase.verifyEqual(status, int32(0));
            testCase.verifyTrue(valid);
            testCase.verifyEqual(received, expected);
        end

        function fdDlcMappingMatchesIsoValues(testCase)
            lengths = uint8([0:8 12 16 20 24 32 48 64]);
            dlcs = arrayfun(@x280linux.can.fdLengthToDLC, lengths);
            testCase.verifyEqual(dlcs, uint8(0:15));
        end

        function extendedRemoteFrameHasNoPayload(testCase)
            [sender, receiver] = createObjects(testCase, 2, 'CAN');
            message = exampleMessage('CAN');
            message.ID = uint32(536870911);
            message.Extended = uint8(1);
            message.Remote = uint8(1);
            expected = message;
            expected.Data(:) = 0;
            status = sender(message, true);
            [received, valid] = receiver();
            testCase.verifyEqual(status, int32(0));
            testCase.verifyTrue(valid);
            testCase.verifyEqual(received, expected);
        end

        function duplicateSetupCannotReleaseExistingChannel(testCase)
            [sender, receiver] = createObjects(testCase, 1, 'CAN');
            duplicate = x280linux.can.CANSetup('Channel', 1);
            testCase.addTeardown(@() release(duplicate));
            testCase.verifyWarning(@() duplicate(), 'x280:can:SetupFailed');
            release(duplicate);
            pendingStatus = sender(exampleMessage('CAN'), true);
            status = sender(exampleMessage('CAN'), true);
            [~, valid] = receiver();
            testCase.verifyEqual(pendingStatus, int32(-2));
            testCase.verifyEqual(status, int32(0));
            testCase.verifyTrue(valid);
        end

        function releaseOnlyClosesItsOwnedChannel(testCase)
            [sender, receiver, setup1, ~] = createObjects(testCase, 1, 'CAN');
            sender(exampleMessage('CAN'), true);
            release(setup1);
            status = sender(exampleMessage('CAN'), true);
            [~, valid, peerStatus] = receiver();
            testCase.verifyEqual(status, int32(-5));
            testCase.verifyEqual(peerStatus, int32(0));
            testCase.verifyTrue(valid);
        end

        function staleAndZeroTokensCannotReleaseNewOwner(testCase)
            token = configureLoopback(testCase, 1, false);
            x280linux.can.Loopback.release(token);
            newToken = configureLoopback(testCase, 1, false);
            x280linux.can.Loopback.release(uint32(0));
            x280linux.can.Loopback.release(token);
            [~, valid, status] = x280linux.can.Loopback.receive(1, false);
            testCase.verifyNotEqual(token, newToken);
            testCase.verifyEqual(status, int32(0));
            testCase.verifyFalse(valid);
        end

        function modeMismatchReportsError(testCase)
            createObjects(testCase, 1, 'CAN');
            sender = x280linux.can.CanSent('Channel', 1, 'CANType', 'CAN FD');
            receiver = x280linux.can.CanReceive('Channel', 2, 'CANType', 'CAN FD');
            testCase.addTeardown(@() release(sender));
            testCase.addTeardown(@() release(receiver));
            sendStatus = sender(exampleMessage('CAN FD'), true);
            [message, valid, receiveStatus] = receiver();
            testCase.verifyEqual(sendStatus, int32(-13));
            testCase.verifyEqual(receiveStatus, int32(-13));
            testCase.verifyFalse(valid);
            testCase.verifyEqual(message, x280linux.can.emptyFDMessage());
        end

        function differentNominalRatesDoNotLoopback(testCase)
            [sender, receiver, ~, setup2] = createObjects(testCase, 1, 'CAN');
            release(setup2);
            setup2.BaudRate = 250;
            setup2();
            status = sender(exampleMessage('CAN'), true);
            [~, valid, receiveStatus] = receiver();
            testCase.verifyEqual(status, int32(0));
            testCase.verifyEqual(receiveStatus, int32(0));
            testCase.verifyFalse(valid);
        end

        function conflictingDeviceRetainsFailureStatus(testCase)
            configureLoopback(testCase, 1, false);
            [token, status] = x280linux.can.Loopback.configure( ...
                '/home/zh/.local/lib/tscan', 'different-adapter', ...
                2, false, 500, 2000, true, true);
            x280linux.can.Loopback.release(token);
            [~, valid, receiveStatus] = x280linux.can.Loopback.receive(2, false);
            configureLoopback(testCase, 2, false);
            [~, ~, correctedStatus] = x280linux.can.Loopback.receive(2, false);
            testCase.verifyEqual(token, uint32(0));
            testCase.verifyEqual(status, int32(-12));
            testCase.verifyEqual(receiveStatus, int32(-12));
            testCase.verifyFalse(valid);
            testCase.verifyEqual(correctedStatus, int32(0));
        end

        function disabledSimulationReportsItsState(testCase)
            setup1 = x280linux.can.CANSetup('HostTransport', 'Disabled');
            sender = x280linux.can.CanSent;
            receiver = x280linux.can.CanReceive;
            testCase.addTeardown(@() release(setup1));
            testCase.addTeardown(@() release(sender));
            testCase.addTeardown(@() release(receiver));
            setup1();
            status = sender(exampleMessage('CAN'), true);
            [~, valid, receiveStatus] = receiver();
            testCase.verifyEqual(status, int32(-15));
            testCase.verifyEqual(receiveStatus, int32(-15));
            testCase.verifyFalse(valid);
        end

        function linuxDriverPathMustBeAbsolute(testCase)
            setup1 = x280linux.can.CANSetup('DriverDirectory', 'drivers');
            testCase.addTeardown(@() release(setup1));
            testCase.verifyError(@() setup(setup1), 'x280:can:DriverDirectory');
        end

        function fdDataRateCannotBeBelowNominalRate(testCase)
            setup1 = x280linux.can.CANSetup('CANType', 'CAN FD', 'DataBitRate', 250);
            testCase.addTeardown(@() release(setup1));
            testCase.verifyError(@() setup(setup1), 'x280:can:DataBitRate');
        end

        function busLayoutMatchesVehicleNetworkToolbox(testCase, canType)
            bus = readOfficialBus(canType);
            message = blankMessage(canType);
            testCase.verifyEqual(fieldnames(message), {bus.Elements.Name}');
            actualTypes = structfun(@class, message, 'UniformOutput', false);
            testCase.verifyEqual(struct2cell(actualTypes), {bus.Elements.DataType}');
            testCase.verifySize(message.Data, [bus.Elements(end).Dimensions 1]);
        end
    end
end

function bus = readOfficialBus(canType)
if strcmp(canType, 'CAN FD')
    busName = 'CAN_FD_MESSAGE_BUS';
else
    busName = 'CAN_MESSAGE_BUS';
end
hadBus = evalin('base', sprintf('exist(''%s'', ''var'') == 1', busName));
previous = [];
if hadBus
    previous = evalin('base', busName);
end
cleanup = onCleanup(@() restoreBus(busName, hadBus, previous)); %#ok<NASGU>
if strcmp(canType, 'CAN FD')
    canFDMessageBusType;
else
    canMessageBusType;
end
bus = evalin('base', busName);
end

function restoreBus(busName, hadBus, previous)
if hadBus
    assignin('base', busName, previous);
else
    evalin('base', ['clear ' busName]);
end
end

function [sender, receiver, setup1, setup2] = createObjects(testCase, senderChannel, canType)
setup1 = x280linux.can.CANSetup('Channel', 1, 'CANType', canType);
setup2 = x280linux.can.CANSetup('Channel', 2, 'CANType', canType);
sender = x280linux.can.CanSent('Channel', senderChannel, 'CANType', canType);
receiver = x280linux.can.CanReceive('Channel', 3 - senderChannel, 'CANType', canType);
testCase.addTeardown(@() release(setup1));
testCase.addTeardown(@() release(setup2));
testCase.addTeardown(@() release(sender));
testCase.addTeardown(@() release(receiver));
setup1();
setup2();
end

function token = configureLoopback(testCase, channel, canfd)
[token, status] = x280linux.can.Loopback.configure( ...
    '/home/zh/.local/lib/tscan', '', channel, canfd, 500, 2000, true, true);
testCase.addTeardown(@() x280linux.can.Loopback.release(token));
testCase.assertEqual(status, int32(0));
end

function message = blankMessage(canType)
if strcmp(canType, 'CAN FD')
    message = x280linux.can.emptyFDMessage();
else
    message = x280linux.can.emptyMessage();
end
end

function message = exampleMessage(canType)
message = blankMessage(canType);
message.ID = uint32(291);
message.Timestamp = 0.125;
if strcmp(canType, 'CAN FD')
    message.ProtocolMode = uint8(1);
    message.BRS = uint8(1);
    message.Length = uint8(64);
    message.DLC = uint8(15);
    message.Data = uint8((1:64)');
else
    message.Length = uint8(8);
    message.Data = uint8((1:8)');
end
end

function fillQueue(sender, canType)
message = exampleMessage(canType);
for index = 1:256
    message.ID = uint32(index);
    status = sender(message, true);
    assert(status == 0);
end
end
