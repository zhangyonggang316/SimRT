function valid = isValidMessage(message)
%ISVALIDMESSAGE Validate values which may change for each classic CAN frame.
%#codegen
valid = message.Length <= 8 && message.Extended <= 1 && ...
    message.Remote <= 1 && message.Error == 0 && ...
    message.ID <= 536870911 && (message.Extended ~= 0 || message.ID <= 2047);
end
