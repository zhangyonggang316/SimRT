function address = getDeviceAddress(hCS)
%GETDEVICEADDRESS Return the configured X280 address for XCP transport.

data = codertarget.data.getData(hCS);
address = data.BoardParameters.DeviceAddress;
end
