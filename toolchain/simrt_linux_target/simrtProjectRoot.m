function root = simrtProjectRoot
%SIMRTPROJECTROOT Resolve the workspace containing the functional directories.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
end
