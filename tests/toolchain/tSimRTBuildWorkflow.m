classdef tSimRTBuildWorkflow < matlab.unittest.TestCase
    methods (TestClassSetup)
        function setupTarget(~)
            setupSimRTLinuxTarget;
        end
    end
    methods (Test)
        function omittedEndpointPreservesModelConfiguration(testCase)
            model = freshModel(testCase);
            configureSimRTModel(model, Address="192.168.193.195", Username="operator", ...
                BuildDirectory="/tmp/my_simrt_model", Save=false);
            result = configureSimRTModel(model, Save=false);
            testCase.verifyEqual(result.Address, "192.168.193.195");
            testCase.verifyEqual(result.Username, "operator");
            testCase.verifyEqual(result.BuildDirectory, "/tmp/my_simrt_model");
            result = configureSimRTModel(model, Address="192.168.193.88", Save=false);
            testCase.verifyEqual(result.Address, "192.168.193.88");
            testCase.verifyEqual(result.Username, "operator");
        end

        function configurationEnforcesSupportedLanguage(testCase)
            model = freshModel(testCase);
            set_param(model, 'TargetLang', 'C++');
            configureSimRTModel(model, Save=false);
            testCase.verifyEqual(get_param(model, 'TargetLang'), 'C');
        end

        function otherFileWithSameModelNameIsRejected(testCase)
            model = freshModel(testCase);
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            other = fullfile(fixture.Folder, [model '.slx']);
            copyfile(get_param(model, 'FileName'), other);
            before = get_param(model, 'CoderTargetData');
            testCase.verifyError(@() configureSimRTModel(other, Address="10.1.2.3"), ...
                'simrtlinux:ModelNameConflict');
            testCase.verifyEqual(get_param(model, 'CoderTargetData'), before);
        end

        function incompleteToolchainReportsAllMissingFiles(testCase)
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            report = inspectSimRTToolchain(Root=fixture.Folder, ProbeCompiler=false);
            testCase.verifyFalse(report.Passed);
            testCase.verifyTrue(any(endsWith(report.Missing, 'linux-gcc.exe')));
            testCase.verifyTrue(any(endsWith(report.Missing, 'linux-g++.exe')));
            testCase.verifyTrue(any(endsWith(report.Missing, 'linux-readelf.exe')));
            testCase.verifyTrue(any(endsWith(report.Missing, 'stdio.h')));
            testCase.verifyError(@() inspectSimRTToolchain(Root=fixture.Folder, Strict=true), ...
                'simrtlinux:ToolchainPreflight');
        end

        function environmentReturnsReportForMissingCompiler(testCase)
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            previous = getenv('SIMRT_TOOLCHAIN_ROOT');
            testCase.addTeardown(@() setenv('SIMRT_TOOLCHAIN_ROOT', previous));
            setenv('SIMRT_TOOLCHAIN_ROOT', fixture.Folder);
            report = verifySimRTEnvironment(Strict=false);
            testCase.verifyFalse(report.AllLocalChecksPassed);
            testCase.verifyFalse(report.LocalBuildAvailable);
            testCase.verifyNotEmpty(report.RegistrationError);
            testCase.verifyNotEmpty(report.Toolchain.Missing);
        end

        function hardwareBuildTransientExtModeDoesNotHideBadPeriod(testCase)
            model = freshModel(testCase);
            set_param(model, 'ExtMode', 'off');
            save_system(model);
            report = validateSimRTRealtimeModel(model, CheckExternalMode=false);
            testCase.verifyEqual(report.period_seconds, 0.001);
            set_param(model, 'FixedStep', '0.005');
            save_system(model);
            testCase.verifyError(@() validateSimRTRealtimeModel(model, CheckExternalMode=false), ...
                'simrtlinux:RealtimeConfiguration');
            config = getActiveConfigSet(model);
            testCase.verifyError(@() codertarget.simrtlinuxssh.internal.onCodeGenEntry(config), ...
                'simrtlinux:RealtimeConfiguration');
            testCase.verifyEqual(get_param(config, 'ExtMode'), 'off');
        end

        function installedToolchainTargetsLinux(testCase)
            report = inspectSimRTToolchain(Strict=true);
            testCase.verifyTrue(report.Passed);
            testCase.verifyEqual(report.CompilerTarget, "x86_64-linux");
            config = simrtRealtimeConfiguration;
            testCase.verifyEqual(config.daq_reserved_blocks, 1024);
            testCase.verifyEqual(config.xcp_reserved_pool_bytes, 1048576);
        end

        function unchangedRegistrationIsNotRewritten(testCase)
            root = setupSimRTLinuxTarget;
            file = fullfile(root, 'registry', 'simrt_portable_toolchain.mat');
            before = simrtFileSHA256(file);
            stamp = dir(file);
            setupSimRTLinuxTarget;
            after = dir(file);
            testCase.verifyEqual(simrtFileSHA256(file), before);
            testCase.verifyEqual(after.datenum, stamp.datenum);
        end
    end
end

function model = freshModel(testCase)
fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
model = 'simrt_build_workflow_unit';
file = createSimRTExampleModel(OutputFolder=fixture.Folder, ModelName=model);
load_system(file);
testCase.addTeardown(@() close_system(model, 0));
end
