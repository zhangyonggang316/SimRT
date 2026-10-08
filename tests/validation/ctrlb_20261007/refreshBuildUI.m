function report = refreshBuildUI
%REFRESHBUILDUI Reopen only a saved, stopped model to reload its target data.
model = 'simrt_rt_single';
assert(strcmp(get_param(model, 'Dirty'), 'off'), 'Save model edits before refreshing.');
assert(strcmp(get_param(model, 'SimulationStatus'), 'stopped'), 'Stop the model before refreshing.');
modelFile = get_param(model, 'FileName');
close_system(model, 0);
open_system(modelFile);
report = inspectBuildUI;
end
