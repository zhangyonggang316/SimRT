# Existing Artifact Migration

All 10 timestamp folders passed three-file manifest/hash validation and ZIP
round-trip validation. Each sibling ZIP contains the timestamp folder and exactly
the original ELF, A2L, and XCP manifest JSON files. Existing ZIPs were verified
without overwriting them. A separate Python `zipfile` check confirmed ZIP CRC,
entry names, byte-for-byte contents, and the recorded archive hashes.

| Model | Timestamp folders / verified ZIPs | Redundant outer ELF |
| --- | ---: | --- |
| `x280_rt_single` | 4 | Matched published ELF hash, then removed |
| `x280_can_loopback` | 6 | Matched published ELF hash, then removed |

The SLX hashes before and after migration match. Generated sources and caches
were preserved. No build, target deployment, or hardware operation was performed
during this migration.

## Artifact Locations

- `Demo_XCP_Qt/models/x280_rt_single/x280_rt_single_local/`: ZIPs for
  `20260915_165556_150`, `20260915_170645_545`, `20260915_170738_507`,
  `20260917_155814_118`.
- `x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback_local/`:
  ZIPs for `20260917_174928_321`, `20260918_170543_260`, `20260918_171258_917`,
  `20260918_171529_950`, `20260918_172542_635`, `20260918_180447_738`.

The ZIP name is `<timestamp>.zip`, next to its matching `<timestamp>` folder.

## Evidence

- [artifact_migration.json](artifact_migration.json) records every absolute folder
  and ZIP path, SHA-256 values for all three files and each archive, model hashes,
  and the matching published ZIP used to authorize each outer ELF removal.
- [migrate_existing_artifacts.m](migrate_existing_artifacts.m) implements the
  bounded migration and refuses to overwrite this completed report.
