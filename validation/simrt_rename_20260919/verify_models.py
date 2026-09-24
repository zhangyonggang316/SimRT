"""Compare model contents before and after the SimRT hardware rename."""
import difflib
import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODELS = (
    "Demo_XCP_Qt/models/x280_rt_single/x280_rt_single.slx",
    "x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback.slx",
)
SAVE_METADATA = {"Open", "ModelVersionFormat"}


def tree_value(element):
    return (
        element.tag,
        sorted(element.attrib.items()),
        (element.text or "").strip(),
        # Saving updates window state and the automatic model version.
        [tree_value(child) for child in element
         if not (child.tag == "P" and child.get("Name") in SAVE_METADATA)],
    )


def main():
    reports = []
    for relative in MODELS:
        current = ROOT / relative
        before = HERE / "models_before" / current.name
        with zipfile.ZipFile(before) as old, zipfile.ZipFile(current) as new:
            assert set(old.namelist()) == set(new.namelist()), relative
            changed = [name for name in old.namelist() if old.read(name) != new.read(name)]
            protected = [name for name in old.namelist() if
                         name.startswith("simulink/systems/") or
                         name.startswith("simulink/stateflow/") or
                         name in ("simulink/blockdiagram.xml", "simulink/modelWorkspace.mxarray")]
            for name in protected:
                if name.endswith(".xml"):
                    if tree_value(ET.fromstring(old.read(name))) != tree_value(ET.fromstring(new.read(name))):
                        print("".join(difflib.unified_diff(
                            old.read(name).decode().splitlines(True),
                            new.read(name).decode().splitlines(True),
                            fromfile="before/" + name, tofile="after/" + name)))
                        raise AssertionError((relative, name))
                else:
                    assert old.read(name) == new.read(name), (relative, name)
            reports.append(dict(model=relative, changed_entries=changed,
                                protected_entries=protected,
                                configuration_diff=list(difflib.unified_diff(
                                    old.read("simulink/configSet0.xml").decode().splitlines(),
                                    new.read("simulink/configSet0.xml").decode().splitlines(),
                                    fromfile="before", tofile="after", lineterm="")),
                                before_sha256=hashlib.sha256(before.read_bytes()).hexdigest(),
                                after_sha256=hashlib.sha256(current.read_bytes()).hexdigest()))
    output = dict(passed=True, ignored_save_metadata=sorted(SAVE_METADATA), models=reports)
    (HERE / "model_comparison.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
