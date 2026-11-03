# SPDX-License-Identifier: MIT
"""Opt-in CID 3 lifecycle, driven by sitd's single-owner event loop.

Only network commands run on a worker. SIT never crosses a thread. Unknown
setup/release outcomes retain the reservation and cannot be retried.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import struct
import subprocess

import data_call as data
from mms_network import Network, configuration


class MMS:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings
        self.state = 'unknown' if data.paths(3)[0].exists() else 'disconnected'
        self.error = ''
        self.token = None
        self.operation = None
        self.network = None
        self.future = None
        self.worker = None
        self.config = {}
        self.lost = False

    def status(self):
        return dict(state=self.state, error=self.error,
                    **(self.config if self.state == 'connected' else {}))

    def connect(self):
        if self.state == 'connected':
            return self.status()
        if self.state != 'disconnected':
            raise RuntimeError('MMS operation pending or uncertain; no automatic retry')
        apn = self.settings.get('apn', '').strip()
        data.check_apn(apn)
        ip_type = self.settings.get('ip_type', 'ipv4')
        if ip_type not in ('ipv4', 'ipv4v6'):
            raise ValueError('MMS host routing currently requires IPv4')
        ps = self.client.request(0x0701)
        if len(ps) < 4 or ps[0] not in (1, 5):
            raise RuntimeError('MMS needs PS registration')
        listed = self.client.request(0x0602)
        state_path, _ = data.paths(3)
        if state_path.exists() or data.call_ids(listed) != data.owned_ids():
            raise RuntimeError('MMS has unresolved bearer ownership')
        if 1 not in data.call_ids(listed, active_only=True):
            raise RuntimeError('MMS needs an active owned internet bearer')
        response = data.paths(1)[1].read_bytes()
        if len(response) < 132 or struct.unpack_from('<HBB', response) not in ((0, 1, 1), (0, 1, 2)):
            raise RuntimeError('MMS needs a confirmed internet bearer')
        if self.client.request(0x0711) != b'\x01':
            raise RuntimeError('MMS needs existing PS permission')
        data.private_write(state_path, json.dumps(dict(cid=3, session=0)).encode())
        self.state, self.operation, self.error = 'connecting', 'setup', ''
        try:
            self.token = self.client.begin(0x0600, data.setup_payload(3, ps[3], 0, apn,
                                          mms=True, ip_type=ip_type), timeout=45)
        except BaseException:
            self.state = 'unknown'
            self.error = 'MMS setup outcome unknown; attended recovery required'
            raise
        return self.status()

    def work(self, operation):
        if self.worker is None:
            self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mms-network')
        self.future = self.worker.submit(operation)

    def disconnect(self):
        if self.state == 'disconnected':
            return self.status()
        if self.state != 'connected':
            raise RuntimeError('MMS operation pending or uncertain; attended recovery required')
        self.state, self.operation = 'disconnecting', 'network-down'
        self.work(self.network.stop)
        return self.status()

    def tick(self):
        try:
            if self.future is not None and self.future.done():
                future, self.future = self.future, None
                result = future.result()
                if self.operation == 'network-up':
                    if self.lost:
                        self.operation = 'network-lost'
                        self.work(self.network.stop)
                    else:
                        self.config, self.state, self.operation = result, 'connected', None
                elif self.operation == 'network-lost':
                    self.operation = None
                elif self.operation == 'network-down':
                    self.operation = 'release'
                    self.token = self.client.begin(0x0601, b'\x03\0', timeout=30)
            if self.token is None:
                return
            result = self.client.finish(self.token)
            if result is None:
                return
            self.token = None
            if self.operation == 'setup':
                if len(result) < 132:
                    raise RuntimeError('Unknown MMS response layout')
                status, cid, active = struct.unpack_from('<HBB', result)
                if cid == 3 and active == 0:
                    for path in data.paths(3):
                        path.unlink(missing_ok=True)
                    self.state, self.operation = 'disconnected', None
                    self.error = 'MMS setup refused (status ' + str(status) + ')'
                    return
                if status or cid != 3 or active not in (1, 2):
                    raise RuntimeError('MMS setup not confirmed')
                listed = self.client.request(0x0602)
                if (3 not in data.call_ids(listed, active_only=True)
                        or data.call_ids(listed) != data.owned_ids()):
                    raise RuntimeError('MMS active bearer list not confirmed')
                data.private_write(data.paths(3)[1], result)
                self.network = Network(configuration(result))
                self.operation = 'network-up'
                self.work(self.network.start)
            elif self.operation == 'release':
                listed = data.call_ids(self.client.request(0x0602))
                if 3 in listed or listed != data.owned_ids() - {3}:
                    raise RuntimeError('MMS release not confirmed')
                for path in data.paths(3):
                    path.unlink(missing_ok=True)
                self.state, self.operation, self.config, self.error = 'disconnected', None, {}, ''
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
            # Do not log modem records, addresses or carrier settings.
            self.token = None
            self.state = 'unknown'
            self.error = 'MMS operation uncertain; reservation retained for attended recovery'
            print(self.error, flush=True)

    def observe_calls(self, listed):
        if self.state != 'connected' and self.operation != 'network-up':
            return
        try:
            present = 3 in data.call_ids(listed, active_only=True)
        except RuntimeError:
            # An unknown list layout cannot confirm the live bearer. Fail
            # only MMS closed, keeping the phone service/calls running.
            present = False
        if not present:
            self.state = 'unknown'
            self.error = 'MMS bearer lost; attended recovery required'
            self.config = {}
            if self.operation == 'network-up':
                # Let the worker finish before undoing its resources. Do not
                # replace its future or publish a late success as Connected.
                self.lost = True
            else:
                self.operation = 'network-lost'
                self.work(self.network.stop)

    def close(self):
        # Remove only our host route. Do not stop the CP or retry a release
        # during daemon shutdown. Its reservation survives until reboot.
        if self.worker:
            self.worker.shutdown(wait=True)
        if self.network:
            self.network.stop()
