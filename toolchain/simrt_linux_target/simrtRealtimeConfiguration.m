function config = simrtRealtimeConfiguration
%SIMRTREALTIMECONFIGURATION Shared native/bundle XCP memory limits.
config = jsondecode(fileread(fullfile(fileparts(mfilename('fullpath')), ...
    'registry', 'realtime_config.json')));
validateattributes(config.daq_reserved_blocks, {'double'}, {'scalar','integer','positive'});
validateattributes(config.xcp_reserved_pool_bytes, {'double'}, {'scalar','integer','positive'});
assert(config.daq_reserved_blocks * 512 <= config.xcp_reserved_pool_bytes, ...
    'simrtlinux:DAQPoolSize', 'The reserved pool cannot hold the configured DAQ blocks.');
end
