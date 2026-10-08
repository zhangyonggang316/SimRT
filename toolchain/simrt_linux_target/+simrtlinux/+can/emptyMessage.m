function message = emptyMessage()
%EMPTYMESSAGE Classic CAN bus compatible with Vehicle Network Toolbox.
%#codegen
message = struct('Extended', uint8(0), 'Length', uint8(0), ...
    'Remote', uint8(0), 'Error', uint8(0), 'ID', uint32(0), ...
    'Timestamp', 0.0, 'Data', zeros(8, 1, 'uint8'));
end
