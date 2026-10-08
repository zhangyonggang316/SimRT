function onCodeGenEntry(hCS)
%ONCODEGENENTRY Validate the target before TLC and retain the standalone XCP server.
% R2024b temporarily disables ExtMode for its ordinary Build action.
model = getModel(hCS);
validateSimRTRealtimeModel(get_param(model, 'Name'), CheckExternalMode=false);
inspectSimRTToolchain(Strict=true);
preserveDirty = Simulink.PreserveDirtyFlag(model); %#ok<NASGU>
configset.internal.setParam(hCS, 'ExtMode', 'on', 'Apply', 'off');
end
