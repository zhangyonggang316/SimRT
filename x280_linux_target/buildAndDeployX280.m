function result = buildAndDeployX280(model, options)
%BUILDANDDEPLOYX280 Compatibility entry point for the local build workflow.
arguments
    model (1,1) string
    options.Address (1,1) string = "192.168.219.86"
    options.Username (1,1) string = ""
    options.BuildDirectory (1,1) string = ""
    options.Run (1,1) logical = false
    options.ArtifactDirectory (1,1) string = ""
    options.RequireReachable (1,1) logical = false
end
assert(~options.Run, 'x280linux:UseSSHDeploymentApp', ...
    'Build locally with buildX280Local, then select its payload in the Qt SSH deployment APP.');
result = buildX280Local(model, Address=options.Address, ...
    ArtifactDirectory=options.ArtifactDirectory);
result.DeploymentCompleted = false;
end
