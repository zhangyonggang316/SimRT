import tempfile
import unittest
from pathlib import Path

from pyxcp_host.services import A2LCatalogService
from pyxcp_host.services.a2l_metadata import read_metadata


SCALARS = '''
/begin RECORD_LAYOUT FLOAT FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT
/begin MEASUREMENT model_B.left_signal "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100
 ECU_ADDRESS 0x10 /end MEASUREMENT
/begin MEASUREMENT model_B.right_signal "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100
 ECU_ADDRESS 0x14 /end MEASUREMENT
/begin CHARACTERISTIC model_P.left_gain "" VALUE 0x20 FLOAT 0 NO_COMPU_METHOD -100 100
/end CHARACTERISTIC
'''


class A2LMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'model.a2l'

    def load(self, metadata):
        self.path.write_text('/begin PROJECT P "" /begin MODULE M ""\n' +
                             SCALARS + metadata + '\n/end MODULE /end PROJECT', encoding='utf-8')
        return A2LCatalogService().load(self.path)

    def test_nested_model_groups_preserve_duplicate_leaf_group_labels(self):
        info = self.load('''
        /begin GROUP X280_ModelHierarchy_1 "model" ROOT
          /begin SUB_GROUP X280_ModelHierarchy_2 X280_ModelHierarchy_3 /end SUB_GROUP
        /end GROUP
        /begin GROUP X280_ModelHierarchy_2 "left" /begin SUB_GROUP X280_ModelHierarchy_4 /end SUB_GROUP /end GROUP
        /begin GROUP X280_ModelHierarchy_3 "right" /begin SUB_GROUP X280_ModelHierarchy_5 /end SUB_GROUP /end GROUP
        /begin GROUP X280_ModelHierarchy_4 "PID / value" 
          /begin REF_MEASUREMENT model_B.left_signal /end REF_MEASUREMENT
          /begin REF_CHARACTERISTIC model_P.left_gain /end REF_CHARACTERISTIC
        /end GROUP
        /begin GROUP X280_ModelHierarchy_5 "PID / value"
          /begin REF_MEASUREMENT model_B.right_signal /end REF_MEASUREMENT
        /end GROUP
        ''')
        by_name = {item.name: item for item in info.measurements}
        self.assertEqual(by_name['model_B.left_signal'].model_path, ('model', 'left', 'PID / value'))
        self.assertEqual(by_name['model_B.right_signal'].model_path, ('model', 'right', 'PID / value'))
        self.assertEqual(info.calibrations[0].model_path, ('model', 'left', 'PID / value'))

    def test_external_groups_use_declared_names_and_do_not_split_c_identifiers(self):
        info = self.load('''
        /begin GROUP Powertrain "Description, not a subsystem name" ROOT
          /begin SUB_GROUP Speed_Controller /end SUB_GROUP
        /end GROUP
        /begin GROUP Speed_Controller "PID"
          /begin REF_MEASUREMENT model_B.left_signal /end REF_MEASUREMENT
        /end GROUP
        ''')
        self.assertEqual(info.measurements[0].model_path, ('Powertrain', 'Speed_Controller'))
        self.assertEqual(info.measurements[1].model_path, ())
        self.assertEqual(info.calibrations[0].model_path, ())

    def test_shared_scalar_is_shown_at_common_parent(self):
        info = self.load('''
        /begin GROUP Root "" ROOT /begin SUB_GROUP Left Right /end SUB_GROUP /end GROUP
        /begin GROUP Left "" /begin REF_MEASUREMENT model_B.left_signal /end REF_MEASUREMENT /end GROUP
        /begin GROUP Right "" /begin REF_MEASUREMENT model_B.left_signal /end REF_MEASUREMENT /end GROUP
        ''')
        self.assertEqual(info.measurements[0].model_path, ('Root',))

    def test_group_cycle_and_duplicate_identifiers_are_rejected(self):
        for metadata in (
            '/begin GROUP A "" /begin SUB_GROUP B /end SUB_GROUP /end GROUP '
            '/begin GROUP B "" /begin SUB_GROUP A /end SUB_GROUP /end GROUP',
            '/begin GROUP A "" /end GROUP /begin GROUP A "" /end GROUP',
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.load(metadata)

    def test_transport_ignores_comments_a2ml_schema_and_quoted_block_text(self):
        info = self.load('''
        /* /begin XCP_ON_TCP_IP 0x0100 5555 ADDRESS "wrong" /end XCP_ON_TCP_IP */
        // /begin XCP_ON_TCP_IP 0x0100 1111 /end XCP_ON_TCP_IP
        /begin A2ML block "XCP_ON_TCP_IP" struct { uint; uint; "ADDRESS" char[15]; }; /end A2ML
        /begin GROUP External "/begin XCP_ON_TCP_IP 0x100 2222 /end XCP_ON_TCP_IP" ROOT /end GROUP
        /begin IF_DATA XCP
          /begin XCP_ON_UDP_IP /* version */ 0x0100/* port */017725
            ADDRESS "192.168.219.86"
          /end XCP_ON_UDP_IP
        /end IF_DATA
        ''')
        self.assertEqual(info.declared_transports, ('UDP',))
        self.assertEqual(info.declared_ports, {'UDP': 17725})
        self.assertEqual(info.declared_hosts, {'UDP': '192.168.219.86'})

    def test_host_name_and_address_precedence(self):
        info = self.load('''
        /begin XCP_ON_TCP_IP 0x100 0x15B3 HOST_NAME "target.example" /end XCP_ON_TCP_IP
        /begin XCP_ON_UDP_IP 0x100 17725 HOST_NAME "unused.example" ADDRESS "192.0.2.5" /end XCP_ON_UDP_IP
        ''')
        self.assertEqual(info.declared_hosts, {'TCP': 'target.example', 'UDP': '192.0.2.5'})

    def test_conflicting_or_invalid_ports_are_rejected(self):
        for metadata in (
            '/begin XCP_ON_UDP_IP 0x100 0 /end XCP_ON_UDP_IP',
            '/begin XCP_ON_UDP_IP 0x100 65536 /end XCP_ON_UDP_IP',
            '/begin XCP_ON_UDP_IP 0x100 17725 /end XCP_ON_UDP_IP '
            '/begin XCP_ON_UDP_IP 0x100 17726 /end XCP_ON_UDP_IP',
            '/begin XCP_ON_UDP_IP 0x100 17725 ADDRESS "a" /end XCP_ON_UDP_IP '
            '/begin XCP_ON_UDP_IP 0x100 17725 ADDRESS "b" /end XCP_ON_UDP_IP',
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.load(metadata)

    def test_metadata_reader_preserves_comment_symbols_in_quoted_names(self):
        self.path.write_text('''/begin GROUP X280_ModelHierarchy_1 "root/*name*/" ROOT
        /begin REF_MEASUREMENT s /end REF_MEASUREMENT /end GROUP''', encoding='utf-8')
        paths, transports, ports, hosts = read_metadata(self.path)
        self.assertEqual(paths, {('MEASUREMENT', 's'): ('root/*name*/',)})
        self.assertEqual((transports, ports, hosts), ((), {}, {}))
