function validateIPv4(address)
%VALIDATEIPV4 Accept unambiguous dotted-decimal IPv4 addresses without DNS.
%#codegen
validateattributes(address, {'char'}, {'row', 'nonempty'});
parts = 0; value = 0; digits = 0;
for index = 1:numel(address)
    character = address(index);
    if character == '.'
        assert(digits > 0 && parts < 3, 'simrt:net:IPv4', 'Invalid IPv4 address.');
        parts = parts + 1; value = 0; digits = 0;
    else
        assert(character >= '0' && character <= '9' && digits < 3 && ...
            ~(digits > 0 && value == 0), 'simrt:net:IPv4', 'Invalid IPv4 address.');
        value = value * 10 + double(character) - double('0');
        digits = digits + 1;
        assert(value <= 255, 'simrt:net:IPv4', 'Invalid IPv4 address.');
    end
end
assert(parts == 3 && digits > 0, 'simrt:net:IPv4', 'Invalid IPv4 address.');
end
