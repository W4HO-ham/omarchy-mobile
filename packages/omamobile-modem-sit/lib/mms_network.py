# SPDX-License-Identifier: MIT
"""An isolated IPv4 MMS link. Never edits the main table or the resolver.

Only sockets bound to rmnet2 use table 625. mmsd uses SO_BINDTODEVICE
and c-ares with the bearer DNS. This first route rejects IPv6-only bearers.
"""
import ipaddress
import json
import struct
import subprocess

INTERFACE = 'rmnet2'
TABLE = '625'
PRIORITY = '1625'


def run(*args):
    result = subprocess.run(['ip', *args], capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError('MMS network operation failed')
    return result.stdout


def configuration(data):
    if len(data) < 132:
        raise ValueError('Short MMS bearer response')
    status, cid, active, pdp = struct.unpack_from('<HBBB', data)
    if status or cid != 3 or active not in (1, 2) or pdp not in (1, 3):
        raise ValueError('MMS needs an active IPv4 bearer')
    address = ipaddress.IPv4Address(data[5:9])
    dns = list(dict.fromkeys(str(ipaddress.IPv4Address(data[i:i+4]))
                            for i in (0x1a, 0x2e) if any(data[i:i+4])))
    if address.is_unspecified or address.is_multicast or not dns:
        raise ValueError('MMS needs an address and carrier DNS')
    return dict(interface=INTERFACE, address=str(address), prefix=32, dns=dns)


class Network:
    def __init__(self, config):
        self.config = config
        self.owned = []

    def start(self):
        info = json.loads(run('-j', 'address', 'show', 'dev', INTERFACE))[0]
        rules = json.loads(run('-j', 'rule', 'show'))
        routes = json.loads(run('-j', 'route', 'show', 'table', 'all'))
        if ('UP' in info['flags'] or info['addr_info']
                or any(str(r.get('priority')) == PRIORITY or str(r.get('table')) == TABLE for r in rules)
                or any(str(r.get('table')) == TABLE or r.get('dev') == INTERFACE for r in routes)):
            raise RuntimeError('MMS interface or policy table already in use')
        address = self.config['address']
        steps = [
            (('link', 'set', 'dev', INTERFACE, 'up'), ('link', 'set', 'dev', INTERFACE, 'down')),
            (('address', 'add', address + '/32', 'dev', INTERFACE),
             ('address', 'del', address + '/32', 'dev', INTERFACE)),
            (('route', 'add', 'table', TABLE, 'default', 'dev', INTERFACE, 'src', address),
             ('route', 'del', 'table', TABLE, 'default', 'dev', INTERFACE, 'src', address)),
            (('rule', 'add', 'priority', PRIORITY, 'oif', INTERFACE, 'lookup', TABLE),
             ('rule', 'del', 'priority', PRIORITY, 'oif', INTERFACE, 'lookup', TABLE)),
        ]
        try:
            for forward, undo in steps:
                # Record before sending: even an interrupted command may have
                # applied. Rollback failures keep ownership for attended repair.
                self.owned.append(undo)
                run(*forward)
        except BaseException:
            self.stop()
            raise
        return self.config

    def absent(self, undo):
        """A failed/timeout command may already have been undone. Inspect
        only our exact resource before treating a failed deletion as done."""
        kind = undo[0]
        if kind == 'link':
            info = json.loads(run('-j', 'link', 'show', 'dev', INTERFACE))[0]
            return 'UP' not in info['flags']
        if kind == 'address':
            info = json.loads(run('-j', 'address', 'show', 'dev', INTERFACE))[0]
            return not any(a.get('local') == self.config['address'] for a in info['addr_info'])
        if kind == 'route':
            return not any(str(r.get('table')) == TABLE and r.get('dev') == INTERFACE
                           for r in json.loads(run('-j', 'route', 'show', 'table', 'all')))
        return not any(str(r.get('priority')) == PRIORITY
                       for r in json.loads(run('-j', 'rule', 'show')))

    def stop(self):
        while self.owned:
            undo = self.owned[-1]
            try:
                run(*undo)
            except (RuntimeError, subprocess.SubprocessError):
                if not self.absent(undo):
                    raise
            self.owned.pop()
        return {}
