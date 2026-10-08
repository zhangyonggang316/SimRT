function report = buildFromHardwareTab
%BUILDFROMHARDWARETAB Exercise the registered Hardware-tab action in R2024b.
folder = fileparts(mfilename('fullpath'));
report = inspectBuildUI;
assert(report.build_action_enabled, 'Hardware build action is disabled.');
model = report.model;
assert(strcmp(get_param(model, 'Dirty'), 'off'), 'Save model edits before building.');
data = get_param(model, 'CoderTargetData');
assert(strcmp(data.Runtime.BuildAction, 'Build'), 'Only local Build is allowed.');
editors = GLUE2.Util.findAllEditors(model);
studio = editors(1).getStudio();
service = studio.getToolStrip().getActionService();
diary(fullfile(folder, 'hardware_build.log'));
cleanup = onCleanup(@() diary('off'));
sldiagviewer.diary(fullfile(folder, 'hardware_diagnostics.log'));
diagnosticCleanup = onCleanup(@() sldiagviewer.diary('off'));
timer = tic;
started = now;
service.executeActionSync(report.build_action_tag);
report.action_duration_seconds = toc(timer);
build = RTW.getBuildDir(model);
receiptFile = fullfile(build.BuildDirectory, 'simrt_local_build.json');
receiptInfo = dir(receiptFile);
assert(~isempty(receiptInfo) && receiptInfo.datenum >= started - 1/86400, ...
    'Hardware action did not publish a new build receipt; inspect diagnostics.');
receipt = jsondecode(fileread(receiptFile));
assert(receipt.success && ~receipt.remote_operations_performed);
assert(isfile(receipt.archive));
assert(strcmpi(simrtFileSHA256(receipt.archive), receipt.archive_sha256));
report.build_receipt = receipt;
copyfile(receiptFile, fullfile(folder, 'build_report.json'));
report.after_build = inspectBuildUI;
file = fopen(fullfile(folder, 'hardware_action.json'), 'w', 'n', 'UTF-8');
fileCleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
end
