classdef LocalBuildHook < coder.coverage.BuildHook
    %LOCALBUILDHOOK Verify saved state and package artifacts after local linking.
    methods
        function entry(this)
            model = this.getModelName;
            assert(strcmp(get_param(model, 'Dirty'), 'off'), ...
                'simrtlinux:UnsavedModel', 'Save the model before generating matched local artifacts.');
        end

        function after_make(this)
            model = this.getModelName;
            if strcmp(get_param(model, 'GenCodeOnly'), 'on'), return; end
            codertarget.simrtlinuxssh.internal.completeLocalBuild(model);
        end
    end
end
