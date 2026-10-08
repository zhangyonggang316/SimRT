function address = getDeviceAddress(hCS)
%GETDEVICEADDRESS Return the configured SimRT address for XCP transport.

data = codertarget.data.getData(hCS);
address = data.BoardParameters.DeviceAddress;
end
