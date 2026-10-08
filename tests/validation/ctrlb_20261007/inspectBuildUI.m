function report = inspectBuildUI(model)
%INSPECTBUILDUI Read the same build capabilities consumed by the Hardware tab.
if nargin == 0, model='simrt_rt_single'; end
report=struct('model',model,'build_options',{codertarget.parameter.getBuildOptionsEntries(model)});
report.dirty=get_param(model,'Dirty');
report.external_mode=get_param(model,'ExtMode');
report.handle_build_options=codertarget.parameter.getBuildOptionsEntries(get_param(model,'Handle'));
report.config_build_options=codertarget.parameter.getBuildOptionsEntries(getActiveConfigSet(model));
context=coder.internal.toolstrip.HardwareBoardContextManager.getContext(get_param(model,'Handle'));
if ~isempty(context)
    report.context_class=class(context);
    report.deploy_context=context.DeployContext;
    report.type_chain=context.TypeChain;
end
editors=GLUE2.Util.findAllEditors(model);
if ~isempty(editors)
    studio=editors(1).getStudio();
    service=studio.getToolStrip().getActionService();
    tag='buildHardwareBoardAction2';
    service.acquireAction(tag);
    cleanup=onCleanup(@() service.releaseAction(tag));
    service.refreshActionSync(tag);
    action=service.getAction(tag);
    report.build_action_found=~isempty(action);
    assert(report.build_action_found, 'Hardware build action was not registered.');
    report.build_action_enabled=action.enabled;
    report.build_action_tag=tag;
end
disp(jsonencode(report,PrettyPrint=true));
end
