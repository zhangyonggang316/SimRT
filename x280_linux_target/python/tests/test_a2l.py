import tempfile
import unittest
from pathlib import Path

from x280_xcp.a2l import A2LError, A2LScalar, parse_a2l


FIXTURE = r'''
/begin MODULE Demo ""
  /begin MOD_COMMON ""
    BYTE_ORDER MSB_LAST
  /end MOD_COMMON

  /begin CHARACTERISTIC
    CalGain "gain" VALUE 0x00001000 LayoutDouble 0 NoConversion -100 100
    ECU_ADDRESS_EXTENSION 2
  /end CHARACTERISTIC

  /begin CHARACTERISTIC
    Curve "not scalar" CURVE 0x00002000 LayoutU16 0 NoConversion 0 100
  /end CHARACTERISTIC

  /begin MEASUREMENT
    MeasuredOutput "output" FLOAT32_IEEE NoConversion 0 0 -100 100
    ECU_ADDRESS 0x00003000
  /end MEASUREMENT

  /begin MEASUREMENT
    Vector "not scalar" UBYTE NoConversion 0 0 0 255
    MATRIX_DIM 4
    ECU_ADDRESS 0x00004000
  /end MEASUREMENT

  /begin MEASUREMENT
    Matrix "also not scalar" UBYTE NoConversion 0 0 0 255
    MATRIX_DIM 1 2
    ECU_ADDRESS 0x00005000
  /end MEASUREMENT

  /begin RECORD_LAYOUT LayoutDouble
    FNC_VALUES 1 FLOAT64_IEEE COLUMN_DIR DIRECT
  /end RECORD_LAYOUT
  /begin RECORD_LAYOUT LayoutU16
    FNC_VALUES 1 UWORD COLUMN_DIR DIRECT
  /end RECORD_LAYOUT
/end MODULE
'''


class A2LParserTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "demo.a2l"
        self.path.write_text(FIXTURE, encoding="latin-1")

    def test_parses_supported_scalar_characteristic_and_measurement(self):
        database = parse_a2l(self.path)

        gain = database.get("CalGain", kind="characteristic")
        self.assertEqual(gain.address, 0x1000)
        self.assertEqual(gain.address_extension, 2)
        self.assertEqual(gain.data_type, "FLOAT64_IEEE")
        self.assertEqual(gain.byte_order, "little")
        self.assertEqual(gain.size, 8)

        measured = database.get("MeasuredOutput", kind="measurement")
        self.assertEqual(measured.address, 0x3000)
        self.assertEqual(measured.data_type, "FLOAT32_IEEE")
        self.assertEqual(len(database.characteristics), 1)
        self.assertEqual(len(database.measurements), 1)

    def test_excludes_curve_and_vector_objects(self):
        database = parse_a2l(self.path)
        with self.assertRaises(A2LError):
            database.get("Curve")
        with self.assertRaises(A2LError):
            database.get("Vector")
        with self.assertRaises(A2LError):
            database.get("Matrix")

    def test_scalar_encodes_and_decodes_with_declared_byte_order(self):
        scalar = A2LScalar("Count", "MEASUREMENT", 1, "ULONG", "big")
        payload = scalar.encode("0x10203040")
        self.assertEqual(payload, b"\x10\x20\x30\x40")
        self.assertEqual(scalar.decode(payload), 0x10203040)

    def test_invalid_value_is_rejected(self):
        scalar = A2LScalar("Count", "CHARACTERISTIC", 1, "UBYTE")
        with self.assertRaises(A2LError):
            scalar.encode(256)
        floating = A2LScalar("Gain", "CHARACTERISTIC", 2, "FLOAT32_IEEE")
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(A2LError):
                floating.encode(value)

    def test_daq_events_are_scoped_to_xcp_and_keep_quoted_strings(self):
        metadata = r'''
        /begin A2ML block "EVENT" struct { char[101]; uint; }; /end A2ML
        /begin IF_DATA OTHER /begin DAQ
          /begin EVENT "ignored" "ignored" 0 DAQ 1 2 7 0 /end EVENT
        /end DAQ /end IF_DATA
        /begin IF_DATA XCP /begin DAQ
          /begin EVENT "/end" "1ms" 0 DAQ 255 1 6 0 /end EVENT
          /begin EVENT "slow \" /begin" "10ms" 1 DAQ 255 1 7 0 /end EVENT
        /end DAQ /end IF_DATA
        '''
        self.path.write_text(FIXTURE.replace("/end MODULE", metadata + "/end MODULE"), encoding="ascii")
        events = parse_a2l(self.path).daq_events
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].name, "/end")
        self.assertEqual(events[1].name, 'slow " /begin')
        self.assertEqual([event.period_seconds for event in events], [.001, .01])

    def test_daq_event_invalid_or_duplicate_fields_are_rejected(self):
        for event in (
            '"bad" "bad" 0 DAQ 255 1 99 0',
            '"bad" "bad" 65536 DAQ 255 1 6 0',
            '"bad" "bad" 0 BOTH 255 1 6 0',
            '"short" "short" 0 DAQ',
            '"a" "a" 0 DAQ 255 1 6 0 /end EVENT /begin EVENT "b" "b" 0 DAQ 255 1 6 0',
        ):
            with self.subTest(event=event):
                block = '/begin IF_DATA XCP /begin DAQ /begin EVENT ' + event + ' /end EVENT /end DAQ /end IF_DATA '
                self.path.write_text(FIXTURE.replace("/end MODULE", block + "/end MODULE"), encoding="ascii")
                with self.assertRaises(A2LError):
                    parse_a2l(self.path)


if __name__ == "__main__":
    unittest.main()
