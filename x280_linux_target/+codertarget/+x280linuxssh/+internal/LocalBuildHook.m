classdef LocalBuildHook < coder.coverage.BuildHook
    %LOCALBUILDHOOK R2024b build lifecycle hook, invoked only after local linking.
    methods
        function entry(this)
            model = this.getModelName;
            assert(strcmp(get_param(model, 'Dirty'), 'off'), ...
                'x280linux:UnsavedModel', 'Save the model before generating matched local artifacts.');
        end

        function after_make(this)
            model = this.getModelName;
            if strcmp(get_param(model, 'GenCodeOnly'), 'on'), return; end
            codertarget.x280linuxssh.internal.completeLocalBuild(model);
        end
    end
end
