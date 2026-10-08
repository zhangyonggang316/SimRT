"""Shared A2L array and CAN payload checks for current target validation."""
from collections import Counter
from pathlib import Path
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from simrt_xcp.a2l import A2LDatabase, A2LScalar, _BLOCK_RE, _COMMENT_RE, _keyword_value, _tokens

def catalog_with_payload_bytes(a2l: Path, model: str, length: int) -> A2LCatalogService:
    catalog = A2LCatalogService()
    catalog.load(a2l)
    database = catalog.database
    elements = []
    text = _COMMENT_RE.sub(" ", a2l.read_text(encoding="utf-8-sig"))
    wanted = {model + "_B.CAN1_Data", model + "_B.CAN2_Data"}
    for kind, body in _BLOCK_RE.findall(text):
        tokens = _tokens(body)
        if kind.upper() != "MEASUREMENT" or not tokens or tokens[0] not in wanted:
            continue
        if tokens[2] != "UBYTE" or int(_keyword_value(tokens, "MATRIX_DIM")) != length:
            raise ValueError("Unexpected received payload type or length")
        address = int(_keyword_value(tokens, "ECU_ADDRESS"), 0)
        extension = int(_keyword_value(tokens, "ECU_ADDRESS_EXTENSION") or "0", 0)
        for index in range(length):
            elements.append(A2LScalar(tokens[0] + "[{}]".format(index), "MEASUREMENT",
                                      address + index, "UBYTE", database.byte_order, extension))
    if len(elements) != 2 * length:
        raise ValueError("Both complete received payloads must be described by the A2L")
    catalog.database = A2LDatabase(database.scalars + tuple(elements),
                                  database.byte_order, database.daq_events)
    return catalog

def evaluate_samples(samples: list, model: str, length: int) -> dict:
    result = {}
    prefix = model + "_B."
    for channel in (1, 2):
        name = "CAN{}".format(channel)
        valid = [sample for sample in samples if sample.values[prefix + name + "_Valid"]]
        expected = list(range(length, 0, -1)) if channel == 1 else list(range(1, length + 1))
        expected_id = 514 if channel == 1 else 257
        mismatches = []
        for sample in valid:
            values = sample.values
            actual = [values[prefix + name + "_Data[{}]".format(index)] for index in range(length)]
            if values[prefix + name + "_ID"] != expected_id or actual != expected:
                mismatches.append({"time": sample.timestamp_seconds, "id": values[prefix + name + "_ID"],
                                   "data": actual})
        statuses = {kind: dict(Counter(str(int(sample.values[prefix + name + "_" + kind]))
                                      for sample in samples)) for kind in ("TxStatus", "RxStatus")}
        errors = sum(count for counts in statuses.values() for status, count in counts.items()
                     if int(status) not in (0, -6))
        result[name] = {"valid_frames": len(valid), "expected_id": expected_id,
                        "expected_payload": expected, "mismatches": len(mismatches),
                        "mismatch_examples": mismatches[:5], "statuses": statuses,
                        "errors_excluding_trylock_busy": errors,
                        "passed": len(valid) >= 1000 and not mismatches and errors == 0}
    return result
