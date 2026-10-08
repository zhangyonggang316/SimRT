import unittest

from pyxcp_host.models import DEFAULT_PORTS
from pyxcp_host.viewmodel import HostViewModel
from qt_host.state import TCP_DEFAULT_PORT, UDP_DEFAULT_PORT
from simrt_xcp.client import TransportSettings


class PortDefaultTests(unittest.TestCase):
    def test_protocol_defaults_agree_across_ui_service_and_transport(self):
        ui_ports = {'TCP': TCP_DEFAULT_PORT, 'UDP': UDP_DEFAULT_PORT}
        for protocol, port in (('UDP', 5555), ('TCP', 17725)):
            with self.subTest(protocol=protocol):
                self.assertEqual(ui_ports[protocol], port)
                self.assertEqual(DEFAULT_PORTS[protocol], port)
                self.assertEqual(HostViewModel.default_port(protocol.lower()), port)
                self.assertEqual(TransportSettings('127.0.0.1', protocol=protocol).port, port)
