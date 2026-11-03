# SPDX-License-Identifier: MIT
"""Runtime MMS lifecycle, routing isolation and ambiguous outcomes."""
import env  # noqa: F401
from concurrent.futures import Future
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

import data_call
import mms
import mms_network
from test_mms_bearer import Modem, record


def response():
    result = bytearray(record(3))
    result[5:9] = bytes([192, 0, 2, 3])
    result[0x1a:0x1e] = bytes([192, 0, 2, 53])
    return bytes(result)


class Runtime(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, path in [('STATE', root/'data-session.json'), ('RESPONSE', root/'data-call-response.bin')]:
            p = patch.object(data_call, name, path)
            p.start(); self.addCleanup(p.stop)
        self.client = Modem()
        self.client.begin = Mock(return_value=42)
        self.client.finish = Mock(return_value=None)
        for cid in (1, 2):
            a, b = data_call.paths(cid)
            a.write_text(json.dumps(dict(cid=cid, session=0)))
            b.write_bytes(record(cid))
        self.mms = mms.MMS(self.client, dict(apn='mms.example', ip_type='ipv4'))
        self.network = Mock()
        self.network.start.return_value = mms_network.configuration(response())
        p = patch.object(mms, 'Network', return_value=self.network)
        p.start(); self.addCleanup(p.stop)
        # A completed future makes the worker's completion deterministic.
        def work(operation):
            f = Future()
            try: f.set_result(operation())
            except Exception as e: f.set_exception(e)
            self.mms.future = f
        self.mms.work = work

    def activate(self):
        self.assertEqual(self.mms.connect()['state'], 'connecting')
        self.mms.tick()
        self.assertEqual(self.mms.state, 'connecting')
        self.client.finish.return_value = response()
        self.client.records[3] = record(3)
        self.mms.tick(); self.mms.tick()
        self.assertEqual(self.mms.state, 'connected')

    def test_pending_setup_then_connect_and_release_only_mms(self):
        self.activate()
        setup = self.client.begin.call_args
        self.assertEqual(setup.args[0], 0x0600)
        self.assertEqual(struct.unpack_from('<I', setup.args[1], 0xf1 - 12)[0], 2)
        self.assertTrue(all(ident not in (0x0625, 0x0710) for ident, _ in self.client.sent))
        self.client.finish.return_value = None
        self.mms.disconnect(); self.mms.tick()
        self.client.begin.assert_called_with(0x0601, b'\x03\0', timeout=30)
        self.client.records.pop(3)
        self.client.finish.return_value = b''
        self.mms.tick()
        self.assertEqual(self.mms.state, 'disconnected')
        self.assertTrue(data_call.paths(1)[0].exists())
        self.assertTrue(data_call.paths(2)[0].exists())
        self.assertFalse(data_call.paths(3)[0].exists())

    def test_timeout_retains_ownership_and_refuses_repeat(self):
        self.mms.connect()
        self.client.finish.side_effect = TimeoutError()
        self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.assertTrue(data_call.paths(3)[0].exists())
        with self.assertRaises(RuntimeError): self.mms.connect()
        self.assertEqual(self.client.begin.call_count, 1)

    def test_explicit_refusal_allows_owner_to_decide_next_attempt(self):
        self.mms.connect()
        self.client.finish.return_value = record(3, 0, 36)
        self.mms.tick()
        self.assertEqual(self.mms.state, 'disconnected')
        self.assertFalse(data_call.paths(3)[0].exists())
        self.assertIn('36', self.mms.error)

    def test_network_failure_is_not_published_connected_or_retried(self):
        self.network.start.side_effect = RuntimeError()
        self.mms.connect(); self.client.finish.return_value = response()
        self.client.records[3] = record(3)
        self.mms.tick(); self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.assertNotIn('address', self.mms.status())
        self.assertTrue(data_call.paths(3)[0].exists())

    def test_unsolicited_loss_drops_host_route_without_modem_release(self):
        self.activate()
        count = self.client.begin.call_count
        self.mms.observe_calls(b'\0')
        self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.network.stop.assert_called_once()
        self.assertEqual(self.client.begin.call_count, count)
        self.assertTrue(data_call.paths(3)[0].exists())

    def test_unknown_indication_layout_fails_only_mms_closed(self):
        self.activate()
        self.mms.observe_calls(b'\xff')
        self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.network.stop.assert_called_once()

    def test_loss_during_host_setup_never_publishes_late_connection(self):
        self.mms.connect()
        self.client.records[3] = record(3)
        self.client.finish.return_value = response()
        self.mms.tick()
        # The worker completed, but the actor has not consumed its result.
        self.mms.observe_calls(b'\0')
        self.assertEqual(self.mms.state, 'unknown')
        self.mms.tick(); self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.assertNotIn('address', self.mms.status())
        self.network.stop.assert_called_once()

    def test_setup_without_active_list_confirmation_is_unknown(self):
        self.mms.connect()
        self.client.finish.return_value = response()
        self.mms.tick()
        self.assertEqual(self.mms.state, 'unknown')
        self.network.start.assert_not_called()

    def test_shutdown_removes_host_route_without_stopping_or_releasing_cp(self):
        self.activate()
        before = self.client.begin.call_count
        self.mms.close()
        self.network.stop.assert_called_once()
        self.assertEqual(self.client.begin.call_count, before)
        self.assertTrue(data_call.paths(3)[0].exists())


class Routing(unittest.TestCase):
    def run_network(self, fail=None):
        commands = []
        def run(*args):
            commands.append(args)
            if args[:3] == ('-j', 'address', 'show'):
                return b'[{"flags": [], "addr_info": []}]'
            if args[:2] == ('-j', 'rule') or args[:2] == ('-j', 'route'): return b'[]'
            if fail and args[:2] == fail: raise RuntimeError('test failure')
            return b''
        network = mms_network.Network(mms_network.configuration(response()))
        with patch.object(mms_network, 'run', side_effect=run):
            if fail:
                with self.assertRaises(RuntimeError): network.start()
            else:
                network.start(); network.stop()
        return commands, network

    def test_only_bound_sockets_get_a_default_route_and_no_dns_is_changed(self):
        commands, _ = self.run_network()
        self.assertIn(('rule', 'add', 'priority', '1625', 'oif', 'rmnet2', 'lookup', '625'), commands)
        for args in commands:
            if args[:2] in (('route', 'add'), ('route', 'del')):
                self.assertEqual(args[2:4], ('table', '625'))
        self.assertFalse(any('rmnet0' in a or 'rmnet1' in a for a in commands))

    def test_failure_restores_only_owned_link_and_address(self):
        commands, network = self.run_network(('route', 'add'))
        self.assertIn(('address', 'del', '192.0.2.3/32', 'dev', 'rmnet2'), commands)
        self.assertIn(('link', 'set', 'dev', 'rmnet2', 'down'), commands)
        self.assertEqual(network.owned, [])

    def test_foreign_policy_or_link_is_never_replaced(self):
        for answer in (b'[{"flags":["UP"],"addr_info":[]}]', b'[{"flags":[],"addr_info":[{}]}]'):
            with patch.object(mms_network, 'run', side_effect=[answer, b'[]', b'[]']) as run:
                with self.assertRaises(RuntimeError):
                    mms_network.Network(mms_network.configuration(response())).start()
                self.assertEqual(run.call_count, 3)

    def test_ipv6_only_and_bad_addresses_refused(self):
        for data in (b'', record(1), record(3), response()[:4]+b'\2'+response()[5:]):
            with self.assertRaises(ValueError): mms_network.configuration(data)
