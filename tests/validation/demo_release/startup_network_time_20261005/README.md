# Network, Clock and Startup Verification

Date: 2026-10-05. Target: `ark2120`, `192.168.193.195`.

## Changes

- Ethernet addresses were already saved in Netplan, but networkd waited for
  carrier before assigning them. The application now writes `ignore-carrier:
  true` for the selected Ethernet definition. The existing three ports were
  restored to `192.168.7.1/24`, `192.168.8.1/24`, and `192.168.9.1/24`; they are
  also marked optional for startup. Wi-Fi credentials and DHCP remain unchanged.
- The local display hides wireless link-local IPv6 rows, retains IP/MAC rows,
  and reloads the system timezone on each refresh. The 16x32 font is retained.
- Each application SSH connection queues time synchronization. It waits for the
  model to stop and three CPU samples below 50% on all cores spanning four
  seconds. Remote idle state is checked again. Current host UTC epoch and IANA
  timezone are used; NTP is retained, large offsets are submitted to chrony,
  and no forced time-step command is used. Disconnect clears the pending job.
- The target timezone was changed from UTC to `Asia/Shanghai`. Model timing
  remains based on the existing runtime implementation.
- Unused ModemManager and automatic crash-report startup were disabled. The
  network dispatcher was retained because system hook symlinks exist. The tty1
  getty uses `Type=simple`; existing Wi-Fi, SSH, storage and model settings remain.
- A host-only initramfs was generated for the local SSD/LVM installation,
  excluding early network-boot modules. It shrank from 62,683,082 bytes to
  35,733,160 bytes. AHCI, LVM, device-mapper and ext4 support were checked before
  installation. The PREEMPT_RT kernel was not replaced.

## Evidence

- [before.json](before.json): initial saved/live network state, clock and startup.
- [target_changes.json](target_changes.json): saved Ethernet repair and boot settings.
- [console_deployment.json](console_deployment.json) and
  [console_after.txt](console_after.txt): deployed console hash and terminal capture.
- [reboot_1_after.json](reboot_1_after.json): actual reboot with all three static IPs
  retained, PREEMPT_RT active, and the same model restored.
- [reboot_2_after.json](reboot_2_after.json): second successful reboot using the
  smaller initramfs; IPs, timezone, console and model recovery checked again.
- [reboot_2_before.json](reboot_2_before.json): real clock workflow rejected the
  running-model state, then succeeded during the stopped/idle interval. Windows
  and Linux UTC epochs differed by about 0.313 seconds, within the two-second
  tolerance. Timezone and NTP were confirmed. The drift/chrony branch is covered
  by tests; an artificial incorrect clock was not introduced on the target.
- [fast_initrd.json](fast_initrd.json): initramfs sizes, hashes, required drivers
  and original-image backup.
- [qt_tests.txt](qt_tests.txt): 172 tests passed. [service_tests.txt](service_tests.txt):
  192 tests passed. These logs contain PowerShell's stderr wrapper around unittest
  progress; the unittest results themselves are `OK`.
- Console tests: 26 passed, including wireless address filtering and timezone refresh.
- [app_delivery.json](app_delivery.json): packaged application started successfully,
  window title `SimRT`, responding. The existing SLX and ZIP hashes are unchanged.

The initial Linux startup measurement was 31.944 seconds, excluding BIOS/firmware.
The first service-only optimization measured 31.682 seconds. The host-only
initramfs boot measured 30.736 seconds, about 1.208 seconds (3.8%) faster than the
initial boot. This is a single reboot per configuration, not a statistical cold
boot benchmark. A two-second cold boot has not been achieved. Reboot-to-SSH elapsed time includes shutdown,
firmware, Wi-Fi association and polling, and must not be substituted for Linux
startup or physical power-on timing. The model was manually running before this
work; verification restores it manually without changing its disabled autostart.

| Measurement | Initial Boot | Final Boot |
| --- | ---: | ---: |
| Kernel | 2.721 s | 2.468 s |
| Initramfs | 9.685 s | 8.556 s |
| Userspace complete | 19.537 s | 19.711 s |
| Total Linux startup | 31.944 s | 30.736 s |
| tty1 service active since kernel start | 29.644 s | 28.742 s |

The tty1 service timestamp is not a photographed first-frame time. Firmware and
physical power-on timing are outside this SSH test. No suspend/hibernate shortcut,
kernel replacement, root filesystem migration, or model algorithm change was used.
The remaining 2-second objective requires separate firmware/kernel/root-filesystem
work; the current general-purpose Ubuntu boot path does not meet it.

## Recovery

The original Netplan files and enabled-service states are backed up in
`/var/backups/simrt-startup-20261005-071543`. The original boot image is
`/boot/initrd.img-7.0.0-34-realtime.before-simrt-20261005-154332`.
The host-only policy is `/etc/dracut.conf.d/90-simrt-local-boot.conf`; it is specific
to this local-disk target, not a network-root or encrypted-root deployment.
The previous Windows application is in `tests/validation/startup_network_time_20261005_previous_app/app`.

References: [Netplan ignore-carrier](https://github.com/canonical/netplan/blob/main/doc/netplan-yaml.md),
[dracut host-only configuration](https://dracut-ng.github.io/dracut/man/dracut.conf.5.html),
[chrony manual time input](https://chrony-project.org/doc/4.6/chronyc.html).
