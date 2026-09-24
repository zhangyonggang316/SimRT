function validateFDMessage(message)
%VALIDATEFDMESSAGE Require the official CAN FD Pack bus types and dimensions.
%#codegen
assert(isstruct(message) && isscalar(message), ...
    'x280:can:InvalidMessage', 'Message must be a scalar CAN_FD_MESSAGE_BUS.');
assert(isfield(message, 'ProtocolMode') && isfield(message, 'Extended') && ...
    isfield(message, 'Length') && isfield(message, 'Remote') && ...
    isfield(message, 'Error') && isfield(message, 'BRS') && ...
    isfield(message, 'ESI') && isfield(message, 'DLC') && ...
    isfield(message, 'ID') && isfield(message, 'Reserved') && ...
    isfield(message, 'Timestamp') && isfield(message, 'Data'), ...
    'x280:can:InvalidMessage', 'Use CAN FD Pack with Output as bus enabled.');
validateattributes(message.ProtocolMode, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Extended, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Length, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Remote, {'uint8'}, {'scalar', 'real'});
validateattributes(message.Error, {'uint8'}, {'scalar', 'real'});
validateattributes(message.BRS, {'uint8'}, {'scalar', 'real'});
validateattributes(message.ESI, {'uint8'}, {'scalar', 'real'});
validateattributes(message.DLC, {'uint8'}, {'scalar', 'real'});
validateattributes(message.ID, {'uint32'}, {'scalar', 'real'});
validateattributes(message.Reserved, {'uint32'}, {'scalar', 'real'});
validateattributes(message.Timestamp, {'double'}, {'scalar', 'real'});
validateattributes(message.Data, {'uint8'}, {'size', [64 1], 'real'});
end
