function deploymentManagedByApp(varargin) %#ok<INUSD>
%DEPLOYMENTMANAGEDBYAPP Prevent implicit remote execution from Simulink builds.
error('simrtlinux:UseSSHDeploymentApp', ...
    'The local build is complete. Select its payload folder in the Qt APP to deploy and run over SSH.');
end
