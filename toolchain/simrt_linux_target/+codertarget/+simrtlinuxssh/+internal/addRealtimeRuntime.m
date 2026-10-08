function addRealtimeRuntime(model, buildInfo)
%ADDREALTIMERUNTIME Keep generated algorithms and replace only runtime sources.
assert(strcmp(get_param(model, 'TargetLang'), 'C') && ...
    strcmp(get_param(model, 'EnableMultiTasking'), 'off') && ...
    strcmp(get_param(model, 'ConcurrentTasks'), 'off'), ...
    'simrtlinux:UnsupportedTasking', 'The local realtime target requires single-task C code.');
build = RTW.getBuildDir(model);
generatedMain = fullfile(build.BuildDirectory, 'ert_main.c');
original = fileread(generatedMain);
call = regexp(original, 'myRTOSInit\s*\(\s*([0-9.eE+-]+)\s*,\s*0\s*\)', 'tokens');
assert(numel(call) == 1 && ismember(str2double(call{1}{1}), [0.001, 0.01, 0.1]), ...
    'simrtlinux:RuntimeContract', 'Expected a 1/10/100 ms single-task generated main.');
defines = getDefines(buildInfo);
sampleTimes = regexp(strjoin(defines), '-DNUMST=([0-9]+)', 'tokens', 'once');
assert(~isempty(sampleTimes), 'simrtlinux:RuntimeContract', 'Missing NUMST definition.');
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
source = fullfile(root, 'src');
main = fileread(fullfile(source, 'simrt_rt_main.c.in'));
main = strrep(main, '@MODEL@', model);
main = strrep(main, '@PERIOD_SECONDS@', call{1}{1});
main = strrep(main, '@NUM_SAMPLE_TIMES@', sampleTimes{1});
fid = fopen(fullfile(build.BuildDirectory, 'simrt_rt_main.c'), 'w', 'n', 'UTF-8');
assert(fid >= 0, 'simrtlinux:RuntimeWrite', 'Cannot write the local realtime main.');
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, main, 'char');
clear cleanup;
buildInfo.removeSourceFiles('ert_main.c');
buildInfo.removeSourceFiles('linuxinitialize.c');
buildInfo.addSourceFiles('simrt_rt_main.c', build.BuildDirectory);
buildInfo.addSourceFiles('simrt_rt_runtime.c', source);
buildInfo.deleteDefines('MW_SCHED_OTHER');
% Buffer bounded network stalls inside the existing preallocated 1 MiB pool.
config = simrtRealtimeConfiguration;
buildInfo.updateDefines({'SIMRT_SINGLE_TASK_RT=1', ...
    sprintf('XCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=%d', config.daq_reserved_blocks), ...
    sprintf('XCP_MEM_RESERVED_POOLS_TOTAL_SIZE=%d', config.xcp_reserved_pool_bytes)}, 'create', true);
end
