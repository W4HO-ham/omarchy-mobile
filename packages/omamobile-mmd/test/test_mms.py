# SPDX-License-Identifier: MIT
"""MMS-only MM bearer control and libmm-glib's mmsd discovery sequence."""
import env
from env import GLib, ROOT, registered_status, wait_until
import os
from pathlib import Path
import unittest
from test_bridge import BridgeTests, MODEM0
import mm_api as mm

try:
    import gi
    gi.require_version('ModemManager', '1.0')
    from gi.repository import ModemManager as MMLib, Gio
except (ValueError, ImportError):
    MMLib = None


class MMS(BridgeTests):
    status = staticmethod(lambda: registered_status(data=True))

    def before_mmd(self):
        config = Path(self.dir)/'mms.conf'
        config.write_text('[network]\napn=internet.example\n[mms]\napn=mms.example\nip_type=ipv4\n')
        self.mmd_args = ('--sit-config', str(config))
        self.sitd.status['mms'] = dict(state='disconnected', error='')

    def bearer(self):
        return self.modem('Bearers')[-1]

    def prop(self, key):
        return self.client.prop(self.bearer(), mm.BEARER, key)

    def connect(self):
        def connected(request):
            self.sitd.status['mms'] = dict(state='connected', error='', interface='rmnet2',
                                         address='192.0.2.3', dns=['192.0.2.53'])
            self.sitd.push()
            return self.sitd.status['mms']
        self.sitd.handlers['mms-connect'] = connected
        self.client.call(self.bearer(), mm.BEARER, 'Connect')
        wait_until(lambda: self.prop('Connected'), 5, 'connected MMS bearer')

    def test_list_create_connect_config_and_disconnect(self):
        paths = self.client.call(MODEM0, mm.MODEM, 'ListBearers')[0]
        self.assertEqual(len(paths), 2)
        self.assertEqual(self.prop('Properties')['apn-type'], 8)
        self.assertFalse(self.prop('Connected'))
        requested = {'apn': GLib.Variant('s', 'MMS.EXAMPLE'),
                     'apn-type': GLib.Variant('u', 8), 'ip-type': GLib.Variant('u', 1)}
        self.assertEqual(self.client.call(MODEM0, mm.MODEM, 'CreateBearer', 'a{sv}', (requested,))[0], self.bearer())
        self.connect()
        self.assertEqual(self.prop('Interface'), 'rmnet2')
        self.assertEqual(self.prop('Ip4Config'), dict(method=2, address='192.0.2.3', prefix=32, dns1='192.0.2.53'))
        self.assertEqual(self.prop('Ip6Config'), {})
        internet = self.client.prop(paths[0], mm.BEARER, 'Connected')
        self.sitd.handlers['mms-disconnect'] = lambda r: dict(state='disconnected', error='')
        self.client.call(self.bearer(), mm.BEARER, 'Disconnect')
        self.assertFalse(self.prop('Connected'))
        self.assertEqual(self.prop('Interface'), '')
        self.assertEqual(self.prop('Ip4Config'), {})
        self.assertEqual(self.client.prop(paths[0], mm.BEARER, 'Connected'), internet)
        self.assertEqual(self.sitd.actions(), ['mms-connect', 'mms-disconnect'])

    def test_connect_waits_for_private_status_while_other_methods_work(self):
        self.sitd.handlers['mms-connect'] = lambda r: dict(state='connecting', error='')
        result = self.client.call_async(self.bearer(), mm.BEARER, 'Connect')
        wait_until(lambda: 'mms-connect' in self.sitd.actions(), 5, 'MMS request')
        # The bridge remains responsive while the modem is making the bearer.
        self.assertEqual(self.client.call(MODEM0, mm.MESSAGING, 'List')[0], [])
        self.assertEqual(result, {})
        self.sitd.status['mms'] = dict(state='connected', error='', interface='rmnet2',
                                      address='192.0.2.3', dns=['192.0.2.53'])
        self.push()
        wait_until(lambda: result, 5, 'asynchronous Connect reply')
        self.assertIn('result', result)

    def test_connected_subscription_overtakes_connecting_reply(self):
        import time
        def delayed(request):
            self.sitd.status['mms'] = dict(state='connected', error='', interface='rmnet2',
                                          address='192.0.2.3', dns=['192.0.2.53'])
            self.sitd.push()
            time.sleep(.15)   # status is deliberately delivered first
            return dict(state='connecting', error='')
        self.sitd.handlers['mms-connect'] = delayed
        self.client.call(self.bearer(), mm.BEARER, 'Connect')
        self.assertTrue(self.prop('Connected'))
        self.assertEqual(self.prop('Interface'), 'rmnet2')

    def test_unknown_setup_and_unrelated_apns_never_retry(self):
        self.sitd.handlers['mms-connect'] = lambda r: dict(state='unknown', error='MMS outcome uncertain')
        error = self.error_of(self.bearer(), mm.BEARER, 'Connect')
        self.assertEqual(error, mm.ERROR_PREFIX + 'Failed')
        self.assertEqual(self.sitd.actions(), ['mms-connect'])
        for props in ({'apn': GLib.Variant('s', 'arbitrary.example')},
                      {'apn': GLib.Variant('s', 'mms.example'), 'apn-type': GLib.Variant('u', 2)}):
            self.assertEqual(self.error_of(MODEM0, mm.MODEM, 'CreateBearer', 'a{sv}', (props,)), mm.ERROR_PREFIX+'InvalidArgs')
        self.assertEqual(self.sitd.actions(), ['mms-connect'])

    def test_connection_loss_finishes_pending_method_without_retry(self):
        self.sitd.handlers['mms-connect'] = lambda r: dict(state='connecting', error='')
        result = self.client.call_async(self.bearer(), mm.BEARER, 'Connect')
        wait_until(lambda: 'mms-connect' in self.sitd.actions(), 5, 'MMS request')
        self.sitd.stop()
        wait_until(lambda: result, 5, 'failed Connect reply')
        self.assertIn('error', result)
        self.assertEqual(self.client.objects(), {})

    @unittest.skipUnless(MMLib, 'libmm-glib typelib not installed')
    def test_mmsd_tng_discovery_sequence_through_libmm_glib(self):
        self.connect()
        c = Gio.DBusConnection.new_for_address_sync(self.bus.address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        self.addCleanup(c.close_sync, None)
        manager = MMLib.Manager.new_sync(c, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START, None)
        modem = manager.get_objects()[0].get_modem()
        self.assertEqual(modem.get_state(), MMLib.ModemState.CONNECTED)
        bearers = modem.list_bearers_sync(None)
        selected = [b for b in bearers if b.get_properties().get_apn().lower() == 'mms.example'][0]
        self.assertTrue(selected.get_connected())
        self.assertEqual(selected.get_interface(), 'rmnet2')
        self.assertEqual(selected.get_ipv4_config().get_dns(), ['192.0.2.53'])
        self.assertEqual(selected.get_properties().get_apn_type(), MMLib.BearerApnType.MMS)


@unittest.skipUnless(os.environ.get('MMSD_TEST_BINARY'), 'set MMSD_TEST_BINARY to a built mmsdtng (or emulator wrapper)')
class MmsdProcess(BridgeTests):
    """Built daemon discovery on private buses, with fictional settings.

    Fake rmnet2 does not exist on the host; no HTTP transfer is attempted.
    """
    status = staticmethod(lambda: registered_status(data=True))

    def before_mmd(self):
        config = Path(self.dir)/'mms.conf'
        config.write_text('[network]\napn=mms.example\n[mms]\napn=mms.example\nip_type=ipv4\n')
        self.mmd_args = ('--sit-config', str(config))
        self.sitd.status['mms'] = dict(state='connected', error='', interface='rmnet2',
                                      address='192.0.2.3', dns=['192.0.2.53'])

    def test_built_mmsd_discovers_shared_apn_and_handles_redacted_identifiers(self):
        import subprocess
        import signal
        from gi.repository import Gio
        home = Path(self.dir)/'home'
        settings = home/'.mms/modemmanager'
        settings.mkdir(parents=True)
        (settings/'mms').write_text('[Modem Manager]\nCarrierMMSC=http://mmsc.example/\n'
            'MMS_APN=mms.example\nCarrierMMSProxy=NULL\nModemNumber=+12025550123\n'
            'AutoProcessOnConnection=true\nAutoProcessSMSWAP=true\n[Settings]\nForceCAres=true\n')
        log = Path(self.dir)/'mmsd.log'
        with log.open('w') as output:
            process = subprocess.Popen([os.environ['MMSD_TEST_BINARY'], '-d'],
                env=dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home/'.config'),
                         XDG_CACHE_HOME=str(home/'.cache'), DBUS_SYSTEM_BUS_ADDRESS=self.bus.address,
                         DBUS_SESSION_BUS_ADDRESS=self.bus.address), stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        def stop():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        self.addCleanup(stop)
        def services():
            if process.poll() is not None:
                self.fail('built mmsd exited: ' + log.read_text())
            try:
                return self.bus.connection.call_sync('org.ofono.mms', '/org/ofono/mms',
                    'org.ofono.mms.Manager', 'GetServices', None, None, Gio.DBusCallFlags.NONE,
                    1000, None).unpack()[0]
            except GLib.Error:
                return []
        wait_until(services, 20, 'mmsd service on the private bus')
        wait_until(lambda: 'Service own number set' in log.read_text(), 15, 'configured international own number')
        wait_until(lambda: 'interface rmnet2' in log.read_text(), 15, 'dedicated MMS interface')
        text = log.read_text()
        self.assertNotIn('interface rmnet0', text)
        self.assertNotIn('Country Code is NULL', text)
        self.assertNotIn('Error setting own number', text)
        self.assertEqual(self.sitd.actions(), [])
