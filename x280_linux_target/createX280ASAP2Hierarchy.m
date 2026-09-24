function descriptions = createX280ASAP2Hierarchy(model, descriptions)
%CREATEX280ASAP2HIERARCHY Export source-model groups through public ASAP2 APIs.
% C names identify data; SID parent chains identify model hierarchy.
arguments
    model (1,1) string
    descriptions = []
end

if isempty(descriptions)
    descriptions = coder.asap2.getEcuDescriptions(char(model));
end
build = RTW.getBuildDir(char(model));
descriptor = coder.getCodeDescriptor(build.BuildDirectory);
measurements = string(descriptions.find('Measurement'));
characteristics = string(descriptions.find('Characteristic'));
measurementPaths = containers.Map('KeyType', 'char', 'ValueType', 'any');
characteristicPaths = containers.Map('KeyType', 'char', 'ValueType', 'any');
collectInterfaces(descriptor, model, model);

existingGroups = string(descriptions.find('Group'));
for index = 1:numel(existingGroups)
    descriptions.delete('Group', char(existingGroups(index)));
end
groups = containers.Map('KeyType', 'char', 'ValueType', 'any');
groupOrder = strings(1, 0);
ensureGroup(model);
attach(measurements, measurementPaths, 'RefMeasurement');
attach(characteristics, characteristicPaths, 'RefCharacteristic');
for index = 1:numel(groupOrder)
    descriptions.add(groups(char(groupOrder(index))));
end

    function collectInterfaces(codeDescriptor, owner, prefix)
        categories = codeDescriptor.getDataInterfaceTypes();
        for categoryIndex = 1:numel(categories)
            interfaces = codeDescriptor.getDataInterfaces(categories{categoryIndex});
            for dataIndex = 1:numel(interfaces)
                data = interfaces(dataIndex);
                implementation = data.Implementation;
                if isempty(implementation) || ~ismethod(implementation, 'getExpression')
                    continue;
                end
                expression = string(implementation.getExpression());
                if expression == ""
                    continue;
                end
                modelPath = sourceParent(data, owner);
                modelPath = [prefix, modelPath(2:end)];
                assignMatches(measurements, measurementPaths, expression, modelPath);
                assignMatches(characteristics, characteristicPaths, expression, modelPath);
            end
        end
        references = codeDescriptor.getReferencedModelNames();
        for referenceIndex = 1:numel(references)
            reference = string(references{referenceIndex});
            referencedDescriptor = codeDescriptor.getReferencedModelCodeDescriptor(char(reference));
            instances = find_system(char(owner), 'LookUnderMasks', 'all', ...
                'FollowLinks', 'on', 'BlockType', 'ModelReference', 'ModelName', char(reference));
            loadedHere = ~bdIsLoaded(reference);
            if loadedHere
                load_system(reference);
            end
            referenceCleanup = onCleanup(@() closeReference(reference, loadedHere));
            for instanceIndex = 1:numel(instances)
                instance = instances{instanceIndex};
                instancePath = [blockParent(instance), string(get_param(instance, 'Name'))];
                collectInterfaces(referencedDescriptor, reference, [prefix, instancePath(2:end)]);
            end
            clear referenceCleanup;
        end
    end

    function assignMatches(names, mapping, expression, modelPath)
        matches = names(names == expression | startsWith(names, expression + ".") | ...
            startsWith(names, expression + "["));
        for matchIndex = 1:numel(matches)
            name = char(matches(matchIndex));
            if isKey(mapping, name)
                mapping(name) = commonParent(mapping(name), modelPath);
            else
                mapping(name) = modelPath;
            end
        end
    end

    function attach(names, mapping, property)
        for nameIndex = 1:numel(names)
            name = char(names(nameIndex));
            modelPath = model;
            if isKey(mapping, name)
                modelPath = mapping(name);
            end
            key = ensureGroup(modelPath);
            group = groups(key);
            group.(property)(end + 1) = string(name);
            groups(key) = group;
        end
    end

    function key = ensureGroup(modelPath)
        key = char(jsonencode(cellstr(modelPath)));
        if isKey(groups, key)
            return;
        end
        parentKey = '';
        if numel(modelPath) > 1
            parentKey = ensureGroup(modelPath(1:end - 1));
        end
        group = coder.asap2.Group;
        group.Name = sprintf('X280_ModelHierarchy_%06d', numel(groupOrder) + 1);
        group.LongIdentifier = char(modelPath(end));
        group.Root = isscalar(modelPath);
        groups(key) = group;
        groupOrder(end + 1) = string(key);
        if ~isempty(parentKey)
            parent = groups(parentKey);
            parent.SubGroup(end + 1) = string(group.Name);
            groups(parentKey) = parent;
        end
    end
end

function closeReference(reference, loadedHere)
if loadedHere && bdIsLoaded(reference)
    close_system(reference, 0);
end
end

function modelPath = sourceParent(data, owner)
modelPath = owner;
sid = string(data.SID);
if contains(sid, '#var:')
    % Workspace data is scoped to the model, even when used in many blocks.
    return;
elseif sid ~= ""
    source = Simulink.ID.getFullName(char(sid));
    modelPath = blockParent(source);
end
if isempty(modelPath)
    modelPath = owner;
end
end

function modelPath = blockParent(block)
parent = get_param(block, 'Parent');
modelPath = strings(1, 0);
while ~isempty(parent)
    modelPath = [string(get_param(parent, 'Name')), modelPath]; %#ok<AGROW>
    parent = get_param(parent, 'Parent');
end
end

function shared = commonParent(first, second)
count = 0;
for index = 1:min(numel(first), numel(second))
    if first(index) ~= second(index)
        break;
    end
    count = index;
end
shared = first(1:count);
end
