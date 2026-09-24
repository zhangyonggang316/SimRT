function validateMessage(message)
%VALIDATEMESSAGE Require the CAN Pack bus layout without implicit coercion.
%#codegen
assert(isstruct(message) && isscalar(message), ...
    'x280:can:InvalidMessage', 'Message must be a scalar CAN_MESSAGE_BUS.');
assert(isfield(message, 'Extended') && isfield(message, 'Length') && ...
    isfield(message, 'Remote') && isfield(message, 'Error') && ...
    isfield(message, 'ID') && isfield(message, 'Timestamp') && ...
    isfield(message, 'Data'), 'x280:can:InvalidMessage', ...
    'Use the CAN Pack block with Output as bus enabled.');
validateattributes(message.Extended, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Length, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Remote, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Error, {'uint8'}, {'scalar', 'real'});
validateattributes(message.ID, {'uint32'}, {'scalar', 'real'});
validateattributes(message.Timestamp, {'double'}, {'scalar', 'real'});
validateattributes(message.Data, {'uint8'}, {'size', [8 1], 'real'});
end
