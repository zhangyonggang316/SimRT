# Communication implementation coordination

- Root owns console, MATLAB SLX generation, main registration, target tests/validation and final docs.
- network_library agent owns TCP/UDP C and System object source; its first implementation is complete.
- serial_ethercat agent owns serial and EtherCAT C/System sources and their docs/tests.
- ip_configuration agent owns APP-14 in qt_xcp_host: implement a network interface list and static IPv4 configuration through the existing SSH worker, with validation, precise errors and tests. Interpret this as configuring real-time target interfaces from the Qt host. Do not mutate actual network addresses during verification without a chosen user IP.
- Target audit is in target_inventory.json: actual host is ark2120 at 192.168.219.195. It has no nmcli/NetworkManager, three DOWN Ethernet interfaces enp1s0/enp3s0/enp4s0, Wi-Fi active. sudo -n is not available. Network configuration must support this actual environment, and can request admin password in the UI for privileged apply, never persist/log it. Prefer a focused runtime IPv4 apply if persistence isn't implementable; label persistence honestly. Current SSH interface changes must account for disconnection and not falsely report success.
- MATLAB library.settingsLookup() returned found=false, enabled=false, gatePass=true. Root has added genpath(toolchain/development/simulink-agentic-toolkit/tools) to restore missing MCP tool paths. Model editing tests/tools/scripts now work. Do not run concurrent MATLAB commands.
- TCP/UDP SLX has been created via model_edit, saved at drivers/network/simrt_network_library.slx; five object tests pass.
- Hardware official manual: https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf . Target DMI doesn't identify L/F, three physical Ethernet interfaces suggest F, but not confirmed by nameplate. No BIOS/jumper/physical serial wiring has been verified.
