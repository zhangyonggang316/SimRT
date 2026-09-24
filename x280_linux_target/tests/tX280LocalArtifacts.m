classdef tX280LocalArtifacts < matlab.unittest.TestCase
    %TX280LOCALARTIFACTS Exercise real local builds and the deployment-only output.
    methods (Test, TestTags = {'Integration'})
        function buildPublishesOnlyMatchingDeploymentFiles(testCase)
            targetRoot = fileparts(fileparts(mfilename('fullpath')));
            projectRoot = fileparts(targetRoot);
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(targetRoot));
            temporary = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            model = 'x280_rt_single';
            testCase.assertFalse(bdIsLoaded(model), 'Preserve and close the model before this integration test.');
            snapshot = fullfile(temporary.Folder, [model '.slx']);
            copyfile(fullfile(projectRoot, 'Demo_XCP_Qt', 'models', model, [model '.slx']), snapshot);
            load_system(snapshot);
            testCase.addTeardown(@() close_system(model, 0));
            previous = Simulink.fileGenControl('getConfig');
            testCase.addTeardown(@() Simulink.fileGenControl('setConfig', 'config', previous));
            Simulink.fileGenControl('set', ...
                'CodeGenFolder', fullfile(temporary.Folder, 'codegen'), ...
                'CacheFolder', fullfile(temporary.Folder, 'cache'), 'createDir', true);

            exported = buildX280Local(snapshot, ...
                ArtifactDirectory=fullfile(temporary.Folder, 'deployment'));
            build = RTW.getBuildDir(model);
            original = jsondecode(fileread(fullfile(build.BuildDirectory, 'x280_local_build.json')));

            expected = sort(string(model) + [".a2l", ".elf", ".xcp-manifest.json"]);
            testCase.verifyEqual(string(original.payload), string(original.archive));
            testCase.verifyEqual(string(exported.payload), string(exported.archive));
            testCase.verifyFalse(isfolder(erase(string(original.archive), '.zip')));
            testCase.verifyFalse(isfolder(fullfile(temporary.Folder, 'deployment')));
            manifest = jsondecode(fileread(exported.manifest));
            testCase.verifyEqual(string(manifest.TargetHardware), "SimRT");
            testCase.verifyEqual(x280FileSHA256(exported.local_elf), string(manifest.ELFSHA256));
            testCase.verifyEqual(x280FileSHA256(exported.a2l), string(manifest.A2LSHA256));
            testCase.verifyEqual(x280FileSHA256(original.local_elf), string(manifest.ELFSHA256));
            testCase.verifyFalse(original.remote_operations_performed);
            testCase.verifyTrue(isfile(fullfile(original.evidence_directory, 'build_report.json')));
            testCase.verifyTrue(isfile(fullfile(original.realtime_source, 'build_spec.json')));
            testCase.verifyTrue(startsWith(string(original.evidence_directory), string(build.BuildDirectory) + filesep));
            testCase.verifyFalse(isfile(fullfile(fileparts(build.BuildDirectory), [model '.elf'])));
            testCase.verifyEqual(x280FileSHA256(original.archive), string(original.archive_sha256));
            testCase.verifyEqual(x280FileSHA256(exported.archive), string(exported.archive_sha256));
            testCase.verifyEqual(locateX280ELF(model), string(original.local_elf));
            extracted = fullfile(temporary.Folder, 'unzipped');
            unzip(exported.archive, extracted);
            testCase.verifyEqual(outputNames(fullfile(extracted, 'deployment')), expected);
            testCase.verifyEqual(x280FileSHA256(fullfile(extracted, 'deployment', [model '.elf'])), ...
                string(manifest.ELFSHA256));

            rebuilt = buildX280Local(snapshot);
            testCase.verifyEqual(string(rebuilt.payload), string(rebuilt.archive));
            testCase.verifyFalse(isfolder(erase(string(rebuilt.archive), '.zip')));
            testCase.verifyTrue(isfile(rebuilt.archive));
            testCase.verifyFalse(isfile(fullfile(fileparts(build.BuildDirectory), [model '.elf'])));
            testCase.verifyEqual(locateX280ELF(model), string(rebuilt.local_elf));
            delete(rebuilt.local_elf);
            restoredELF = locateX280ELF(model);
            testCase.verifyEqual(x280FileSHA256(restoredELF), string(rebuilt.elf_sha256));
            [exportedA2L, reexportedELF] = exportX280A2L(model, ...
                OutputFolder=string(fullfile(temporary.Folder, 'reexport')));
            testCase.verifyTrue(isfile(exportedA2L));
            testCase.verifyEqual(x280FileSHA256(reexportedELF), string(rebuilt.elf_sha256));
            testCase.verifyTrue(isfile(fullfile(build.BuildDirectory, 'buildInfo.mat')));
        end
    end
end

function names = outputNames(folder)
entries = dir(folder);
entries = entries(~ismember({entries.name}, {'.', '..'}));
names = sort(string({entries.name}));
assert(~any([entries.isdir]), 'Deployment output must not contain subdirectories.');
end
