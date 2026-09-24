classdef tX280LinuxTarget < matlab.unittest.TestCase
    %TX280LINUXTARGET Offline regression tests for the R2024b target package.

    methods (TestClassSetup)
        function registerTarget(testCase)
            root = testCase.targetRoot;
            addpath(root);
            testCase.addTeardown(@() removePath(root));
            setupX280LinuxTarget;
        end
    end

    methods (Test)
        function targetAndBoardAreRegistered(testCase)
            testCase.verifyTrue( ...
                codertarget.target.isTargetRegistered('x280linux'));
            boards = codertarget.target.getAllHardwareBoards('x280linux');
            names = string({boards.Name});
            testCase.verifyTrue(any(names == "SimRT"));
            testCase.verifyFalse(any(names == "X280 Linux (SSH)"));
            board = boards(names == "SimRT");
            testCase.verifyEqual(string(board.ToolChainInfo.Name), ...
                "X280 portable-linux-toolchain");
        end

        function registryUsesX8664AndNoRaspberryPiRuntime(testCase)
            root = testCase.targetRoot;
            hardware = fileread(fullfile(root, 'registry', ...
                'targethardware', 'x280_linux_ssh.xml'));
            attributes = fileread(fullfile(root, 'registry', ...
                'attributes', 'x280_linux_ssh_attributes.xml'));
            testCase.verifySubstring(hardware, ...
                'Intel-&gt;x86-64 (Linux 64)');
            testCase.verifySubstring(hardware, '<numofcores>4</numofcores>');
            testCase.verifySubstring(hardware, ...
                'codertarget.x280linuxssh.internal.deploymentManagedByApp');
            testCase.verifySubstring(attributes, 'MW_SCHED_OTHER');
            testCase.verifySubstring(attributes, ...
                'codertarget.x280linuxssh.internal.onAfterCodeGen');
            testCase.verifySubstring(attributes, ...
                '<transport type="tcp/ip" name="XCP on TCP/IP">');
            testCase.verifySubstring(attributes, ...
                'R2024b has no XCP/UDP External Mode registry type');
            testCase.verifyFalse(contains(attributes, 'mwRaspiInit'));
            testCase.verifyFalse(contains(attributes, 'ARM_PROJECT'));
        end

        function udpAdapterReplacesTheR2024bTcpDefaults(testCase)
            root = testCase.targetRoot;
            hook = fileread(fullfile(root, '+codertarget', ...
                '+x280linuxssh', '+internal', 'onAfterCodeGen.m'));
            adapter = fileread(fullfile(root, 'src', ...
                'xcp_ext_param_x280_udp.c'));
            config = x280XCPConfiguration;

            testCase.verifySubstring(hook, ...
                "removeSourceFiles('xcp_ext_param_default_tcp.c')");
            testCase.verifySubstring(hook, ...
                "'xcp_ext_param_x280_udp.c'");
            testCase.verifySubstring(adapter, '"-protocol", "UDP"');
            testCase.verifySubstring(adapter, '"-port", "17725"');
            testCase.verifyEqual(config.Transport, "UDP");
            testCase.verifyEqual(config.Port, 17725);
            testCase.verifyEqual(config.MaxDTOBytes, 508);
            testCase.verifyEqual(config.MaxDatagramBytes, 512);
        end

        function passwordIsNeverStoredInBoardParameters(testCase)
            root = testCase.targetRoot;
            parameters = fileread(fullfile(root, 'registry', ...
                'parameters', 'x280_linux_ssh_parameters.xml'));
            testCase.verifyFalse(contains(parameters, 'Password'));
            testCase.verifyFalse(contains(parameters, 'remotebuild'));
            testCase.verifySubstring(parameters, 'Value="Build"');
        end

        function generatedModelHasDeploymentAndCalibrationSettings(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            modelName = "x280_unit_demo";
            modelPath = createX280ExampleModel( ...
                OutputFolder=fixture.Folder, ...
                ModelName=modelName, ...
                Overwrite=true);
            load_system(modelPath);
            testCase.addTeardown(@() closeModel(modelName));

            testCase.verifyEqual(string( ...
                codertarget.target.getHardwareName(char(modelName))), ...
                "SimRT");
            testCase.verifyEqual(string(get_param(modelName, 'Toolchain')), ...
                "X280 portable-linux-toolchain");
            testCase.verifyEqual(string(get_param(modelName, ...
                'ProdHWDeviceType')), "Intel->x86-64 (Linux 64)");
            testCase.verifyEqual(string(get_param(modelName, ...
                'GenerateASAP2')), "off");
            testCase.verifyEqual(string(get_param(modelName, 'ExtMode')), "on");

            xcpConfig = x280XCPConfiguration;
            modelConfig = configureX280Model(modelName, Save=false);
            testCase.verifyEqual(modelConfig.XCPTransport, ...
                xcpConfig.Transport);
            testCase.verifyEqual(modelConfig.XCPPort, xcpConfig.Port);

            data = get_param(modelName, 'CoderTargetData');
            testCase.verifyEqual(string(data.BoardParameters.DeviceAddress), ...
                "192.168.219.86");
            testCase.verifyEqual(string(data.BoardParameters.BuildDir), ...
                "/tmp/matlab_x280");
            testCase.verifyFalse(isfield(data.BoardParameters, 'Password'));

            workspace = get_param(modelName, 'ModelWorkspace');
            gain = getVariable(workspace, 'CalGain');
            testCase.verifyClass(gain, 'Simulink.Parameter');
            testCase.verifyEqual(string(gain.CoderInfo.StorageClass), ...
                "ExportedGlobal");
        end

        function a2lMetadataIsSynchronizedWithUdpRuntime(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            a2lFile = writeA2LFixture(fixture.Folder);

            rewriteX280A2LForUDP(a2lFile, ...
                TargetAddress="192.168.0.106");
            firstRewrite = fileread(a2lFile);
            rewriteX280A2LForUDP(a2lFile, ...
                TargetAddress="192.168.0.106");
            secondRewrite = fileread(a2lFile);

            testCase.verifySubstring(firstRewrite, ...
                '/begin XCP_ON_UDP_IP');
            testCase.verifyFalse(contains(firstRewrite, ...
                '/begin XCP_ON_TCP_IP'));
            testCase.verifySubstring(firstRewrite, '0x453D');
            testCase.verifySubstring(firstRewrite, ...
                'ADDRESS "192.168.0.106"');
            testCase.verifySubstring(firstRewrite, '0x01FC');
            testCase.verifyEqual(secondRewrite, firstRewrite);
        end

        function a2lRewriteRejectsRuntimeConfigurationDrift(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            a2lFile = writeA2LFixture(fixture.Folder);

            testCase.verifyError(@() rewriteX280A2LForUDP( ...
                a2lFile, Port=17726), ...
                'x280linux:FixedXCPConfigurationRequired');
        end

        function localEnvironmentChecksPassWithoutNetwork(testCase)
            report = verifyX280Environment(ProbeTarget=false, Strict=true);
            testCase.verifyTrue(report.AllLocalChecksPassed);
            testCase.verifyTrue(isnan(report.TargetPortReachable));
        end

        function legacyBuildCannotStartRemoteExecution(testCase)
            testCase.verifyError(@() buildAndDeployX280("not_loaded", Run=true), ...
                'x280linux:UseSSHDeploymentApp');
        end

        function a2lExportRejectsArmExecutable(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            elfFile = fullfile(fixture.Folder, 'arm-image.elf');
            header = zeros(20, 1, 'uint8');
            header(1:6) = uint8([127 69 76 70 2 1]);
            header(19:20) = uint8([183 0]);
            fileID = fopen(elfFile, 'wb');
            testCase.assertGreaterThan(fileID, 0);
            fileCleanup = onCleanup(@() fclose(fileID));
            fwrite(fileID, header, 'uint8');
            clear fileCleanup;

            model = fullfile(testCase.targetRoot, 'models', ...
                'x280_calibration_demo.slx');
            testCase.verifyError(@() exportX280A2L(model, ...
                MapFile=elfFile, OutputFolder=fixture.Folder), ...
                'x280linux:WrongELFArchitecture');
        end
    end

    methods (Static, Access = private)
        function root = targetRoot
            root = fileparts(fileparts(mfilename('fullpath')));
        end
    end
end

function a2lFile = writeA2LFixture(folder)
a2lFile = fullfile(folder, 'generated.a2l');
contents = strjoin({ ...
    '/begin IF_DATA XCP', ...
    '  /begin PROTOCOL_LAYER', ...
    '    0x0100', ...
    '    0x03E8', ...
    '    0x00C8', ...
    '    0x0000', ...
    '    0x0000', ...
    '    0x0000', ...
    '    0x0000', ...
    '    0x0000', ...
    '    0xFF', ...
    '    0xFFFC', ...
    '    BYTE_ORDER_MSB_LAST', ...
    '    ADDRESS_GRANULARITY_BYTE', ...
    '  /end PROTOCOL_LAYER', ...
    '  /begin XCP_ON_TCP_IP', ...
    '    0x0100', ...
    '    0x453D', ...
    '    HOST_NAME "localhost"', ...
    '  /end XCP_ON_TCP_IP', ...
    '/end IF_DATA'}, newline);
fileID = fopen(a2lFile, 'w', 'n', 'UTF-8');
cleanup = onCleanup(@() fclose(fileID));
fwrite(fileID, contents, 'char');
clear cleanup;
end

function closeModel(modelName)
if bdIsLoaded(modelName)
    close_system(modelName, 0);
end
end

function removePath(root)
if contains([path pathsep], [root pathsep])
    rmpath(root);
end
end
