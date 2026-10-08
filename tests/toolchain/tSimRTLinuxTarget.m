classdef tSimRTLinuxTarget < matlab.unittest.TestCase
    %TSIMRTLINUXTARGET Offline regression tests for the R2024b target package.

    methods (TestClassSetup)
        function registerTarget(testCase)
            root = testCase.targetRoot;
            addpath(root);
            testCase.addTeardown(@() removePath(root));
            setupSimRTLinuxTarget;
        end
    end

    methods (Test)
        function targetAndBoardAreRegistered(testCase)
            testCase.verifyTrue( ...
                codertarget.target.isTargetRegistered('simrtlinux'));
            boards = codertarget.target.getAllHardwareBoards('simrtlinux');
            names = string({boards.Name});
            testCase.verifyTrue(any(names == "SimRT"));
            testCase.verifyFalse(any(names == "SimRT Linux (SSH)"));
            board = boards(names == "SimRT");
            testCase.verifyEqual(string(board.ToolChainInfo.Name), ...
                "SimRT portable-linux-toolchain");
        end

        function registryUsesX8664AndSharedLinuxRuntime(testCase)
            root = testCase.targetRoot;
            hardware = fileread(fullfile(root, 'registry', ...
                'targethardware', 'simrt_linux_ssh.xml'));
            attributes = fileread(fullfile(root, 'registry', ...
                'attributes', 'simrt_linux_ssh_attributes.xml'));
            testCase.verifySubstring(hardware, ...
                'Intel-&gt;x86-64 (Linux 64)');
            testCase.verifySubstring(hardware, '<numofcores>4</numofcores>');
            testCase.verifySubstring(hardware, ...
                'codertarget.simrtlinuxssh.internal.deploymentManagedByApp');
            testCase.verifySubstring(attributes, 'MW_SCHED_OTHER');
            testCase.verifySubstring(attributes, ...
                'codertarget.simrtlinuxssh.internal.onAfterCodeGen');
            testCase.verifySubstring(attributes, ...
                '<transport type="tcp/ip" name="XCP on TCP/IP">');
            testCase.verifySubstring(attributes, ...
                'R2024b has no XCP/UDP External Mode registry type');
            testCase.verifySubstring(attributes, '<port value="5555" visible="true"/>');
            testCase.verifySubstring(hardware, '$(MATLAB_ROOT)/toolbox/target/codertarget/rtos/registry/linux.xml');
        end

        function udpAdapterReplacesTheR2024bTcpDefaults(testCase)
            root = testCase.targetRoot;
            hook = fileread(fullfile(root, '+codertarget', ...
                '+simrtlinuxssh', '+internal', 'onAfterCodeGen.m'));
            adapter = fileread(fullfile(root, 'src', ...
                'xcp_ext_param_simrt_udp.c'));
            config = simrtXCPConfiguration;

            testCase.verifySubstring(hook, ...
                "removeSourceFiles('xcp_ext_param_default_tcp.c')");
            testCase.verifySubstring(hook, ...
                "'xcp_ext_param_simrt_udp.c'");
            testCase.verifySubstring(adapter, '"-protocol", "UDP"');
            testCase.verifySubstring(adapter, '"-port", "5555"');
            testCase.verifyEqual(config.Transport, "UDP");
            testCase.verifyEqual(config.Port, 5555);
            testCase.verifyEqual(config.MaxDTOBytes, 508);
            testCase.verifyEqual(config.MaxDatagramBytes, 512);
        end

        function passwordIsNeverStoredInBoardParameters(testCase)
            root = testCase.targetRoot;
            parameters = fileread(fullfile(root, 'registry', ...
                'parameters', 'simrt_linux_ssh_parameters.xml'));
            testCase.verifyFalse(contains(parameters, 'Password'));
            testCase.verifySubstring(parameters, 'Value="Build"');
        end

        function hardwareTabOffersLocalBuild(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            modelName = 'simrt_build_ui_test';
            modelPath = createSimRTExampleModel( ...
                OutputFolder=fixture.Folder, ModelName=modelName, Overwrite=true);
            load_system(modelPath);
            testCase.addTeardown(@() closeModel(modelName));

            % The Hardware tab resolves this list independently of slbuild.
            entries = codertarget.parameter.getBuildOptionsEntries( ...
                get_param(modelName, 'Handle'));
            testCase.verifyEqual(string(entries), "Build");
            context = coder.internal.toolstrip.HardwareBoardContextManager ...
                .getContext(modelName);
            testCase.assertNotEmpty(context);
            testCase.verifyEqual(string(context.DeployContext), ...
                "HWBoardBuildSelectedBuildContext");

            config = getActiveConfigSet(modelName);
            set_param(config, 'ExtMode', 'off');
            save_system(modelName);
            dirty = get_param(modelName, 'Dirty');
            codertarget.simrtlinuxssh.internal.onCodeGenEntry(config);
            testCase.verifyEqual(get_param(config, 'ExtMode'), 'on');
            testCase.verifyEqual(get_param(modelName, 'Dirty'), dirty);
            data = get_param(modelName, 'CoderTargetData');
            testCase.verifyEqual(data.Runtime.BuildAction, 'Build');
        end

        function generatedModelHasDeploymentAndCalibrationSettings(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            modelName = "simrt_unit_demo";
            modelPath = createSimRTExampleModel( ...
                OutputFolder=fixture.Folder, ...
                ModelName=modelName, ...
                Overwrite=true);
            load_system(modelPath);
            testCase.addTeardown(@() closeModel(modelName));

            testCase.verifyEqual(string( ...
                codertarget.target.getHardwareName(char(modelName))), ...
                "SimRT");
            testCase.verifyEqual(string(get_param(modelName, 'HardwareBoard')), ...
                "SimRT");
            testCase.verifyEqual(string(get_param(modelName, 'Toolchain')), ...
                "SimRT portable-linux-toolchain");
            testCase.verifyEqual(string(get_param(modelName, ...
                'ProdHWDeviceType')), "Intel->x86-64 (Linux 64)");
            testCase.verifyEqual(string(get_param(modelName, ...
                'GenerateASAP2')), "off");
            testCase.verifyEqual(string(get_param(modelName, 'ExtMode')), "on");

            xcpConfig = simrtXCPConfiguration;
            for oldPort = ["17725", "55555"]
                data = get_param(modelName, 'CoderTargetData');
                data.ConnectionInfo.XCPonTCPIP.Port = char(oldPort);
                set_param(modelName, 'CoderTargetData', data);
                modelConfig = configureSimRTModel(modelName, Save=false);
                testCase.verifyEqual(modelConfig.XCPTransport, ...
                    xcpConfig.Transport);
                testCase.verifyEqual(modelConfig.XCPPort, xcpConfig.Port);
                data = get_param(modelName, 'CoderTargetData');
                testCase.verifyEqual(string(data.ConnectionInfo.XCPonTCPIP.Port), ...
                    string(xcpConfig.Port));
            end

            data = get_param(modelName, 'CoderTargetData');
            testCase.verifyEqual(string(data.BoardParameters.DeviceAddress), ...
                "192.168.219.86");
            testCase.verifyEqual(string(data.BoardParameters.BuildDir), ...
                "/tmp/matlab_simrt");
            testCase.verifyFalse(isfield(data.BoardParameters, 'Password'));

            workspace = get_param(modelName, 'ModelWorkspace');
            gain = getVariable(workspace, 'CalGain');
            testCase.verifyClass(gain, 'Simulink.Parameter');
            testCase.verifyEqual(string(gain.CoderInfo.StorageClass), ...
                "ExportedGlobal");
        end

        function canModelUsesCurrentHardwareBoard(testCase)
            modelName = 'simrt_can_loopback';
            modelPath = fullfile(simrtProjectRoot, 'demos', 'io', 'tc1013', modelName, ...
                [modelName '.slx']);
            setupSimRTCANLibrary;
            open_system(modelPath);
            testCase.addTeardown(@() closeModel(modelName));
            configureSimRTModel(modelName, Save=false);
            testCase.verifyEqual(string(get_param(modelName, 'HardwareBoard')), "SimRT");
            testCase.verifyEqual(string(codertarget.target.getHardwareName(modelName)), "SimRT");
        end

        function a2lMetadataIsSynchronizedWithUdpRuntime(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            a2lFile = writeA2LFixture(fixture.Folder);

            rewriteSimRTA2LForUDP(a2lFile, ...
                TargetAddress="192.168.0.106");
            firstRewrite = fileread(a2lFile);
            rewriteSimRTA2LForUDP(a2lFile, ...
                TargetAddress="192.168.0.106");
            secondRewrite = fileread(a2lFile);

            testCase.verifySubstring(firstRewrite, ...
                '/begin XCP_ON_UDP_IP');
            testCase.verifyFalse(contains(firstRewrite, ...
                '/begin XCP_ON_TCP_IP'));
            testCase.verifySubstring(firstRewrite, '0x15B3');
            testCase.verifySubstring(firstRewrite, ...
                'ADDRESS "192.168.0.106"');
            testCase.verifySubstring(firstRewrite, '0x01FC');
            testCase.verifyEqual(secondRewrite, firstRewrite);
        end

        function a2lRewriteRejectsRuntimeConfigurationDrift(testCase)
            fixture = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            a2lFile = writeA2LFixture(fixture.Folder);

            testCase.verifyError(@() rewriteSimRTA2LForUDP( ...
                a2lFile, Port=17726), ...
                'simrtlinux:FixedXCPConfigurationRequired');
        end

        function localEnvironmentChecksPassWithoutNetwork(testCase)
            report = verifySimRTEnvironment(ProbeTarget=false, Strict=true);
            testCase.verifyTrue(report.AllLocalChecksPassed);
            testCase.verifyTrue(isnan(report.TargetPortReachable));
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

            model = fullfile(simrtProjectRoot, 'demos', 'calibration', ...
                'simrt_calibration_demo.slx');
            testCase.verifyError(@() exportSimRTA2L(model, ...
                MapFile=elfFile, OutputFolder=fixture.Folder), ...
                'simrtlinux:WrongELFArchitecture');
        end
    end

    methods (Static, Access = private)
        function root = targetRoot
            root = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), ...
                'toolchain', 'simrt_linux_target');
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
