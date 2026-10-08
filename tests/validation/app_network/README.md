# APP-14 implementation verification

The target workspace has a Network interfaces / IPv4 command. Its dialog lists
every Linux interface and all IPv4/IPv6 addresses, including ports with no IP.
Users can set a runtime static IPv4 address, mask/prefix and optional gateway.
The current SSH management address is retained when adding a different address
on its interface; other global IPv4 addresses on that interface are replaced.

This is runtime configuration, not a persistent NetworkManager/netplan edit.
Reboot or a network manager may restore its own configuration. DHCP mode was not
added. This implementation supports the audited machine without NetworkManager.

The administrator password is sent only over SSH channel stdin for sudo; it is
not included in the command, saved, or logged. Configuration is serialized with
all other target SSH work. A privileged detached helper restores previous IPv4
addresses, main-table routes for the chosen interface, and link state after 45
seconds unless a second SSH command verifies and confirms the change. The UI
requires a concrete confirmation and reports unconfirmed outcomes as errors.
Other interfaces and IPv6 settings are not modified. Bridge/bond members and
advanced routes are rejected before changes.

API: `NetworkConfiguration(deployment).interfaces()` and
`configure(interface, address, mask, gateway='', password='')` in
`pyxcp_host/services/network_configuration.py`. Network writes are never invoked
by loading the dialog or refreshing it.

Validation uses mocked SSH and system network operations. No physical target IP
was changed. `network_dialog.png` is a rendered Qt fixture, not a target capture.
`test_report.json`, `qt_tests.json` and `baseline_tests.json` contain the complete
offline suite results. An initial invocation with a relative output directory
hit the existing tests/validation wrapper's working-directory mismatch; the final
invocation uses an absolute output path.
