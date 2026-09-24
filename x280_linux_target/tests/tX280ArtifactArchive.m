classdef tX280ArtifactArchive < matlab.unittest.TestCase
    %TX280ARTIFACTARCHIVE Check the deployment ZIP contract without code generation.
    properties
        Folder
        Payload
    end

    methods (TestMethodSetup)
        function createPayload(testCase)
            root = fileparts(fileparts(mfilename('fullpath')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(root));
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.Folder = string(fixture.Folder);
            testCase.Payload = fullfile(testCase.Folder, '20260919_123456_789');
            mkdir(testCase.Payload);
            writeText(fullfile(testCase.Payload, 'test_model.elf'), 'ELF fixture');
            writeText(fullfile(testCase.Payload, 'test_model.a2l'), 'A2L fixture');
            manifest = struct('ModelName', 'test_model', 'ELFFile', 'test_model.elf', ...
                'A2LFile', 'test_model.a2l', ...
                'ELFSHA256', x280FileSHA256(fullfile(testCase.Payload, 'test_model.elf')), ...
                'A2LSHA256', x280FileSHA256(fullfile(testCase.Payload, 'test_model.a2l')));
            writeText(fullfile(testCase.Payload, 'test_model.xcp-manifest.json'), jsonencode(manifest));
        end
    end

    methods (Test)
        function archiveContainsOneFolderAndThreeMatchingFiles(testCase)
            originalHash = x280FileSHA256(fullfile(testCase.Payload, 'test_model.elf'));
            [archive, hash] = packageX280Artifacts(testCase.Payload);
            testCase.verifyEqual(archive, testCase.Payload + '.zip');
            testCase.verifyEqual(x280FileSHA256(archive), hash);
            unpacked = fullfile(testCase.Folder, 'unpacked');
            files = string(unzip(archive, unpacked));
            expected = fullfile(unpacked, '20260919_123456_789', ...
                "test_model" + [".a2l", ".elf", ".xcp-manifest.json"]);
            testCase.verifyEqual(sort(files(:)), sort(expected(:)));
            testCase.verifyEqual(x280FileSHA256(fullfile(unpacked, '20260919_123456_789', 'test_model.elf')), ...
                originalHash);
            testCase.verifyFalse(isfolder(testCase.Payload));
            cached = unpackX280Artifacts(archive, fullfile(testCase.Folder, 'cache'), ExpectedSHA256=hash);
            testCase.verifyEqual(x280FileSHA256(fullfile(cached, 'test_model.elf')), originalHash);
        end

        function rejectsChangedArtifactsBeforePublishing(testCase)
            writeText(fullfile(testCase.Payload, 'test_model.elf'), 'Different ELF');
            testCase.verifyError(@() packageX280Artifacts(testCase.Payload), ...
                'x280linux:ArtifactHashMismatch');
            testCase.verifyFalse(isfile(testCase.Payload + '.zip'));
        end

        function rejectsExtraFiles(testCase)
            writeText(fullfile(testCase.Payload, 'build_report.json'), '{}');
            testCase.verifyError(@() packageX280Artifacts(testCase.Payload), ...
                'x280linux:UnexpectedArtifacts');
            testCase.verifyFalse(isfile(testCase.Payload + '.zip'));
        end

        function preservesExistingArchive(testCase)
            [archive, hash] = packageX280Artifacts(testCase.Payload, RemoveSource=false);
            testCase.verifyError(@() packageX280Artifacts(testCase.Payload), 'x280linux:ArchiveExists');
            testCase.verifyEqual(x280FileSHA256(archive), hash);
            testCase.verifyTrue(isfolder(testCase.Payload));
        end

        function rejectsArchiveChangedSinceBuild(testCase)
            [archive, hash] = packageX280Artifacts(testCase.Payload);
            writeText(archive, 'not the published archive');
            testCase.verifyError(@() unpackX280Artifacts(archive, ...
                fullfile(testCase.Folder, 'cache'), ExpectedSHA256=hash), ...
                'x280linux:ArchiveHashMismatch');
        end

        function rejectsModifiedInternalCache(testCase)
            [archive, hash] = packageX280Artifacts(testCase.Payload);
            cache = fullfile(testCase.Folder, 'cache');
            payload = unpackX280Artifacts(archive, cache, ExpectedSHA256=hash);
            writeText(fullfile(payload, 'test_model.elf'), 'modified cache');
            testCase.verifyError(@() unpackX280Artifacts(archive, cache, ExpectedSHA256=hash), ...
                'x280linux:ArtifactHashMismatch');
        end
    end
end

function writeText(path, contents)
file = fopen(path, 'w', 'n', 'UTF-8');
assert(file >= 0, 'Cannot write test fixture.');
cleanup = onCleanup(@() fclose(file));
fwrite(file, contents, 'char');
end
