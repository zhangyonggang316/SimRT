function validateChannel(channel)
%#codegen
validateattributes(channel, {'double'}, ...
    {'scalar', 'real', 'integer', '>=', 1, '<=', 16});
end
