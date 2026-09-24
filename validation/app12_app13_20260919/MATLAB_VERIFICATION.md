# MATLAB Build and Hierarchy Verification

Verified on MATLAB R2024b with Embedded Coder and the existing local X280 Linux cross compiler. No SSH deployment or target operation was performed.

## Repeated Local Builds

`x280_linux_target/tests/tX280LocalArtifacts.m` passed: one integration test, two real local builds, zero failures, zero incomplete tests, 91.6065911 seconds.

The test covers ZIP-only publication, three-file archive contents, artifact hashes, removal of the outer ELF, a second incremental build, restoring an ELF from the verified archive cache, and re-exporting A2L against that restored executable.

- Result: `matlab_local_artifacts.json`
- Complete MATLAB log: `matlab_local_artifacts.log`

## Nested Model

The isolated fixture `nested_model/x280_hierarchy_test.slx` is a copy of the production single-step model. Its additional branch contains two real subsystem levels:

```text
x280_hierarchy_test
  Outer_Control
    Inner_Controller
      DeepGain
```

All block, connection, signal, and subsystem changes were made through the Simulink Agentic Toolkit `model_read` and `model_edit` tools. The final `model_check` found no unconnected ports or signal lines. Production SLX files were not edited.

`verify_nested_hierarchy.m` builds the fixture and compares generated ASAP2 `GROUP`, `SUB_GROUP`, `REF_MEASUREMENT`, and `REF_CHARACTERISTIC` relationships with the source SID parent path. It passed for:

| Kind | A2L Identity | Model Parent Path |
| --- | --- | --- |
| Measurement | `x280_hierarchy_test_B.DeepSignal` | `x280_hierarchy_test/Outer_Control/Inner_Controller` |
| Calibration | `x280_hierarchy_test_P.DeepGain_Gain` | `x280_hierarchy_test/Outer_Control/Inner_Controller` |

`verify_nested_hierarchy.py` then loads the generated ZIP through the APP's `PayloadArchive` and `A2LCatalogService`. It confirms the same paths, eight measurements, thirteen calibrations, UDP port 17725, target address 192.168.219.86, and exactly ELF/A2L/JSON inside the archive. The timestamp directory outside the archive does not exist.

- Build result and source/model hashes: `nested_hierarchy_matlab.json`
- APP loader result: `nested_hierarchy_python.json`
- Complete build log: `nested_hierarchy_build.log`
- Deployment archive: `nested_model/x280_hierarchy_test_local/20260919_020918_330.zip`

The verification models were closed after completion. The MATLAB file-generation configuration was restored by cleanup handlers.

## Reproduction

In MATLAB, add this evidence directory to the path and run `verify_nested_hierarchy`. Then run the workspace Python interpreter with `validation/app12_app13_20260919/verify_nested_hierarchy.py`.

The implementation uses the documented [code descriptor data interface API](https://www.mathworks.com/help/rtw/ref/coder.codedescriptor.codedescriptor.getdatainterfaces.html) to obtain SIDs and the documented [ASAP2 Group API](https://www.mathworks.com/help/rtw/ref/coder.asap2.group.html) to emit hierarchy. It does not infer subsystems by splitting C identifiers.
