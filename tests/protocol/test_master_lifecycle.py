"""Exercise the real native pyxcp lifecycle without a target or XCP traffic."""

import gc
import unittest
from unittest.mock import patch
import weakref

from pyxcp.master import Master

from simrt_xcp.client import (
    TransportSettings,
    XcpClient,
    _create_master,
    build_pyxcp_config,
)


class MasterLifecycleTests(unittest.TestCase):
    def test_closed_native_masters_are_collectable(self):
        references = []
        for _ in range(32):
            master = _create_master('eth', build_pyxcp_config(TransportSettings('127.0.0.1')))
            references.append(weakref.ref(master))
            master.close()
            del master
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))

    def test_failed_connect_releases_real_native_master(self):
        references = []

        def factory(transport_name, config):
            master = _create_master(transport_name, config)
            references.append(weakref.ref(master))
            return master

        # Open and close real listener threads, replacing the protocol request
        # before it can transmit a network packet.
        with patch.object(Master, 'connect', side_effect=RuntimeError('CONNECT failed')):
            for _ in range(4):
                client = XcpClient(TransportSettings('127.0.0.1'), factory)
                with self.assertRaisesRegex(RuntimeError, 'CONNECT failed'):
                    client.connect()
                self.assertFalse(client.connected)
                del client
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))


if __name__ == '__main__':
    unittest.main()
