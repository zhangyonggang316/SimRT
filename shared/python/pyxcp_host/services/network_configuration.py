"""Online IPv4 changes with confirmation, Netplan persistence and rollback."""

import ipaddress
import json
import re
import shlex


def validate_ipv4(interface, address, mask, gateway=''):
    if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}', interface):
        raise ValueError('Invalid network interface name')
    if interface == 'lo':
        raise ValueError('The loopback interface cannot be configured')
    try:
        address = ipaddress.IPv4Address(address.strip())
        mask = mask.strip()
        if '.' in mask and str(ipaddress.IPv4Address(mask)) != str(ipaddress.IPv4Network('0.0.0.0/' + mask).netmask):
            raise ValueError('Use a contiguous subnet mask')
        network = ipaddress.IPv4Network(str(address) + '/' + mask, strict=False)
    except (ValueError, AttributeError) as error:
        raise ValueError('Invalid IPv4 address or subnet mask: ' + str(error)) from None
    if (address.is_unspecified or address.is_multicast or address.is_loopback
            or address == ipaddress.IPv4Address('255.255.255.255') or network.prefixlen == 0
            or network.prefixlen < 31 and address in (network.network_address, network.broadcast_address)):
        raise ValueError('Use a unicast IPv4 host address and a prefix between 1 and 32')
    gateway = gateway.strip()
    if gateway:
        try:
            router = ipaddress.IPv4Address(gateway)
        except ValueError:
            raise ValueError('Invalid IPv4 gateway') from None
        if (router not in network or router == address or router.is_multicast or router.is_unspecified
                or router.is_loopback or network.prefixlen < 31 and router in (network.network_address, network.broadcast_address)):
            raise ValueError('Gateway must be a different unicast host in the selected subnet')
        gateway = str(router)
    return dict(interface=interface, address=str(address), prefix=network.prefixlen, gateway=gateway)


_NETWORK_LIBRARY = r'''
import base64, fcntl, ipaddress, json, os, re, shutil, subprocess, sys, tempfile, time, uuid
from pathlib import Path

def run(args, required=True):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            timeout=15, env=dict(os.environ, LC_ALL='C'))
    if required and result.returncode:
        raise RuntimeError(' '.join(args[:3]) + ': ' + (result.stderr.strip() or result.stdout.strip()))
    return result

def ip(*args):
    return json.loads(run(['ip', '-j'] + list(args)).stdout)

def inventory():
    routes = ip('-4', 'route', 'show', 'default')
    connection = os.environ.get('SSH_CONNECTION', '').split()
    server = connection[2] if len(connection) == 4 else ''
    answer = []
    for item in ip('address', 'show'):
        addresses = [dict(address=value['local'], prefix=value['prefixlen'], family=value['family'])
                     for value in item.get('addr_info', []) if value.get('local')]
        name = item['ifname']
        answer.append(dict(name=name, state=item.get('operstate', 'UNKNOWN'),
            addresses=addresses, mac=item.get('address', ''),
            gateway=next((route.get('gateway', '') for route in routes if route.get('dev') == name), ''),
            management=any(value['address'] == server for value in addresses)))
    return dict(interfaces=answer, server_address=server)

def route_args(route, interface):
    if any(key in route for key in ('nexthops', 'encap', 'via', 'nhid', 'metrics', 'expires')):
        raise ValueError('Interface has advanced routes; configure it with the system network manager')
    args = ['ip', '-4', 'route', 'replace', route.get('dst', 'default')]
    if route.get('gateway'):
        args += ['via', route['gateway']]
    args += ['dev', interface]
    for key, flag in (('prefsrc', 'src'), ('metric', 'metric'), ('scope', 'scope'), ('protocol', 'proto')):
        if key in route:
            args += [flag, str(route[key])]
    if 'onlink' in route.get('flags', []):
        args += ['onlink']
    return args

def netplan_plan(interface, address, gateway, metric=100, mac=''):
    import yaml
    if not shutil.which('netplan'):
        raise RuntimeError('Persistent IPv4 requires Netplan on the target')
    documents = []
    matches = []
    global_renderer = 'networkd'
    interface_renderer = None
    paths = {}
    for folder in ('/lib/netplan', '/etc/netplan', '/run/netplan'):
        for path in Path(folder).glob('*.yaml'):
            paths[path.name] = (folder, path)
    for folder, path in sorted(paths.values(), key=lambda item: item[1].name):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Netplan symbolic links are not supported')
        content = path.read_bytes()
        try:
            document = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            raise ValueError('Invalid Netplan YAML: ' + path.name) from None
        network = document.get('network', {})
        global_renderer = network.get('renderer', global_renderer)
        for section in ('ethernets', 'wifis', 'bridges', 'bonds', 'vlans'):
            nodes = network.get(section, {}) or {}
            for name, node in nodes.items():
                if not isinstance(node, dict):
                    raise ValueError('Invalid Netplan interface definition')
                exact = (name == interface or node.get('set-name') == interface
                         or node.get('match', {}).get('name') == interface)
                if exact:
                    if folder != '/etc/netplan':
                        raise ValueError('This interface has a Netplan definition outside /etc/netplan')
                    match = node.get('match', {})
                    if ((match.get('name') and match['name'] != interface)
                            or (match.get('macaddress') and match['macaddress'].lower() != mac.lower())
                            or (match.get('driver') and not match.get('macaddress') and match.get('name') != interface)):
                        raise ValueError('A dedicated Netplan interface definition is required')
                    interface_renderer = node.get('renderer', interface_renderer)
                    matches.append((len(documents), section, name))
        documents.append((path, content, document))
    if not matches:
        raise ValueError('No dedicated Netplan definition matches the selected interface')
    identities = {(section, name) for _, section, name in matches}
    if len(identities) != 1:
        raise ValueError('Ambiguous Netplan interface definitions')
    if (interface_renderer or global_renderer) != 'networkd':
        raise ValueError('Persistent IPv4 currently requires the networkd renderer')
    changed = {}
    for index, section, name in matches:
        path, content, document = documents[index]
        node = document['network'][section][name]
        # Netplan merges address and route sequences across all fragments.
        node['addresses'] = [value for value in node.get('addresses', [])
                             if ipaddress.ip_interface(value).version == 6]
        node['dhcp4'] = False
        node.pop('gateway4', None)
        node['routes'] = [route for route in node.get('routes', [])
                          if not (route.get('to') in ('default', '0.0.0.0/0')
                                  and ':' not in str(route.get('via', '')))]
        changed[index] = dict(path=str(path), original=base64.b64encode(content).decode('ascii'),
                              mode=path.stat().st_mode & 0o777)
    owner, section, name = matches[-1]
    node = documents[owner][2]['network'][section][name]
    node['addresses'].append(str(address))
    if section == 'ethernets':
        # Restore static addresses at boot even when the cable is unplugged.
        node['ignore-carrier'] = True
    if gateway:
        node['routes'].append(dict(to='default', via=gateway, metric=metric))
    for index, record in changed.items():
        record['updated'] = yaml.safe_dump(documents[index][2], sort_keys=False)
    return list(changed.values())

def atomic_config(path, content, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.simrt-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def restore_netplan(saved):
    for record in saved.get('netplan_files', []):
        atomic_config(Path(record['path']), base64.b64decode(record['original']), record['mode'])
    if saved.get('netplan_files'):
        run(['netplan', 'generate'])

def persist_netplan(saved, directory=None):
    records = saved.get('netplan_files', [])
    if not records:
        return
    for record in records:
        path = Path(record['path'])
        if path.is_symlink() or path.read_bytes() != base64.b64decode(record['original']):
            raise RuntimeError('Netplan configuration changed during the transaction')
    saved['netplan_written'] = True
    if directory is not None:
        (directory / 'state.json').write_text(json.dumps(saved))
    try:
        for record in records:
            atomic_config(Path(record['path']), record['updated'].encode('utf-8'), 0o600)
        run(['netplan', 'generate'])
    except BaseException:
        restore_netplan(saved)
        raise

def restore(saved):
    errors = []
    if saved.get('netplan_written'):
        try:
            restore_netplan(saved)
        except Exception as error:
            errors.append(str(error))
    interface = saved['interface']
    commands = [['ip', '-4', 'address', 'flush', 'dev', interface, 'scope', 'global']]
    for address in saved['addresses']:
        args = ['ip', '-4', 'address', 'add', address['local'] + '/' + str(address['prefixlen']), 'dev', interface]
        if address.get('broadcast'):
            args += ['broadcast', address['broadcast']]
        commands.append(args)
    commands.append(['ip', '-4', 'route', 'flush', 'table', 'main', 'dev', interface])
    for route in sorted(saved['routes'], key=lambda item: bool(item.get('gateway'))):
        commands.append(route_args(route, interface))
    commands.append(['ip', 'link', 'set', 'dev', interface, 'up' if saved['up'] else 'down'])
    # A persistent-config failure must not prevent recovery of the live SSH path.
    for command in commands:
        try:
            run(command)
        except Exception as error:
            errors.append(str(error))
    if errors:
        raise RuntimeError('Network rollback incomplete: ' + '; '.join(errors))

def transaction_dir(token):
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Invalid network transaction')
    directory = Path('/run') / ('pyxcp-network-' + token)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != 0:
        raise ValueError('Network transaction expired')
    return directory

def rollback(token):
    directory = transaction_dir(token)
    saved = json.loads((directory / 'state.json').read_text())
    while time.monotonic() < saved['deadline']:
        if (directory / 'confirmed').exists():
            shutil.rmtree(str(directory))
            return
        time.sleep(0.2)
    with (directory / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (directory / 'confirmed').exists():
            try:
                saved = json.loads((directory / 'state.json').read_text())
                restore(saved)
            except Exception as error:
                (directory / 'rollback-error.txt').write_text(str(error))
                return
    shutil.rmtree(str(directory))

def configure(request):
    interface = request['interface']
    if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}', interface) or interface == 'lo':
        raise ValueError('Invalid network interface')
    address = ipaddress.IPv4Interface(request['address'] + '/' + str(request['prefix']))
    gateway = str(ipaddress.IPv4Address(request['gateway'])) if request.get('gateway') else ''
    management = str(ipaddress.IPv4Address(request['management_address'])) if request.get('management_address') else ''
    if gateway and ipaddress.IPv4Address(gateway) not in address.network:
        raise ValueError('Gateway is outside the interface subnet')
    # The IPv4-only query omits existing interfaces that have no IPv4 address.
    current = ip('address', 'show', 'dev', interface)
    if len(current) != 1:
        raise ValueError('Network interface no longer exists')
    if current[0].get('master'):
        raise ValueError('Configure the bridge or bond instead of its member interface')
    defaults = ip('-4', 'route', 'show', 'default')
    used_metrics = {int(route.get('metric', 0)) for route in defaults if route.get('dev') != interface}
    metric = next((int(route.get('metric', 0)) for route in defaults if route.get('dev') == interface), 100)
    while metric in used_metrics:
        metric += 1
    saved = dict(interface=interface, up='UP' in current[0].get('flags', []), deadline=time.monotonic() + 45,
        requested_address=str(address), requested_gateway=gateway,
        addresses=[item for item in current[0].get('addr_info', [])
                   if item.get('family') == 'inet' and item.get('scope') == 'global'],
        routes=ip('-4', 'route', 'show', 'table', 'main', 'dev', interface))
    if request.get('persistent'):
        saved['netplan_files'] = netplan_plan(interface, address, gateway, metric, current[0].get('address', ''))
    for route in saved['routes']:
        route_args(route, interface)
    retained = [item['local'] + '/' + str(item['prefixlen']) for item in saved['addresses']
                if item['local'] == management and management != str(address.ip)]
    token = uuid.uuid4().hex
    directory = Path('/run') / ('pyxcp-network-' + token)
    directory.mkdir(mode=0o700)
    (directory / 'state.json').write_text(json.dumps(saved))
    script = directory / 'rollback.py'
    script.write_text(request['rollback_source'])
    try:
        subprocess.Popen([sys.executable, str(script), token], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except BaseException:
        shutil.rmtree(str(directory))
        raise
    with (directory / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            run(['ip', 'link', 'set', 'dev', interface, 'up'])
            for previous in saved['addresses']:
                old = previous['local'] + '/' + str(previous['prefixlen'])
                if old != str(address) and old not in retained:
                    run(['ip', '-4', 'address', 'del', old, 'dev', interface])
            # Linux may remove secondary addresses when their primary is deleted.
            run(['ip', '-4', 'address', 'replace', str(address), 'broadcast', '+', 'dev', interface])
            # Default routes on other interfaces are outside this transaction.
            run(['ip', '-4', 'route', 'flush', 'default', 'dev', interface])
            if gateway:
                run(['ip', '-4', 'route', 'add', 'default', 'via', gateway, 'dev', interface, 'metric', str(metric)])
            addresses = ip('-4', 'address', 'show', 'dev', interface)[0].get('addr_info', [])
            if not any(item.get('local') == str(address.ip) and item.get('prefixlen') == address.network.prefixlen for item in addresses):
                raise RuntimeError('Target did not retain the requested IPv4 address')
        except BaseException:
            restore(saved)
            (directory / 'confirmed').touch()
            raise
    return dict(token=token, interface=interface, address=str(address), gateway=gateway,
                persistent=False, retained_management_addresses=retained)

def confirm(request):
    directory = transaction_dir(request['token'])
    with (directory / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = json.loads((directory / 'state.json').read_text())
        if time.monotonic() >= saved['deadline'] - 2:
            raise RuntimeError('Network confirmation expired; automatic rollback remains active')
        requested = ipaddress.IPv4Interface(request['address'])
        if str(requested) != saved['requested_address']:
            raise ValueError('Network confirmation does not match the pending configuration')
        addresses = ip('-4', 'address', 'show', 'dev', saved['interface'])[0].get('addr_info', [])
        if not any(item.get('local') == str(requested.ip) and item.get('prefixlen') == requested.network.prefixlen for item in addresses):
            raise RuntimeError('IPv4 verification failed; automatic rollback remains active')
        defaults = ip('-4', 'route', 'show', 'default', 'dev', saved['interface'])
        gateway = saved['requested_gateway']
        if (gateway and not any(route.get('gateway') == gateway for route in defaults)) or (not gateway and defaults):
            raise RuntimeError('Gateway verification failed; automatic rollback remains active')
        if saved.get('netplan_files'):
            persist_netplan(saved, directory)
            if time.monotonic() >= saved['deadline'] - 2:
                raise RuntimeError('Network save expired; automatic rollback remains active')
        (directory / 'confirmed').touch()
    return dict(confirmed=True, persistent=bool(saved.get('netplan_files')))
'''

_ROLLBACK_HELPER = _NETWORK_LIBRARY + "\nrollback(sys.argv[1])\n"
_NETWORK_HELPER = _NETWORK_LIBRARY + r'''
if __name__ == '__main__':
    try:
        request = json.loads(sys.argv[1])
        if request['action'] == 'list':
            result = inventory()
        elif os.geteuid() != 0:
            raise PermissionError('Administrator privileges are required')
        elif request['action'] == 'configure':
            result = configure(request)
        elif request['action'] == 'confirm':
            result = confirm(request)
        else:
            raise ValueError('Invalid network operation')
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
'''


class NetworkConfiguration:
    def __init__(self, deployment):
        self.deployment = deployment

    def _request(self, action, password=None, **values):
        payload = dict(values, action=action)
        command = 'python3 -c {} {}'.format(shlex.quote(_NETWORK_HELPER), shlex.quote(json.dumps(payload)))
        if password is not None:
            if any(value in password for value in ('\r', '\n', '\x00')):
                raise ValueError('Administrator password contains an invalid control character')
            command = ('sudo -S -p ' + shlex.quote('') + ' -- ' if password else 'sudo -n -- ') + command
        try:
            result = json.loads(self.deployment._execute(command, timeout=30.0,
                input_data=(password + '\n').encode('utf-8') if password else None))
        except Exception as error:
            message = str(error).replace(password, '[redacted]') if password else str(error)
            raise RuntimeError(message) from None
        if not isinstance(result, dict):
            raise ValueError('Invalid network response from target')
        return result

    def interfaces(self):
        with self.deployment._operation_lock:
            self.deployment._begin()
            result = self._request('list')
        if not isinstance(result.get('interfaces'), list):
            raise ValueError('Target did not return a network interface list')
        return result

    def configure(self, interface, address, mask, gateway='', password='', persistent=True):
        values = validate_ipv4(interface, address, mask, gateway)
        with self.deployment._operation_lock:
            self.deployment._begin()
            try:
                inventory = self._request('list')
                server = inventory.get('server_address', '')
                values['management_address'] = server if server and ':' not in server else ''
                result = self._request('configure', password=password, rollback_source=_ROLLBACK_HELPER,
                                       persistent=bool(persistent), **values)
                token = result.get('token', '')
                if not re.fullmatch('[a-f0-9]{32}', token):
                    raise ValueError('Target did not return a valid network transaction')
                confirmed = self._request('confirm', password=password, token=token, address=result['address'])
                if confirmed.get('confirmed') is not True:
                    raise RuntimeError('Target did not confirm the new IPv4 address')
                if persistent and confirmed.get('persistent') is not True:
                    raise RuntimeError('Target did not save the new IPv4 configuration')
            except Exception as error:
                message = str(error).replace(password, '[redacted]') if password else str(error)
                raise RuntimeError(message + '\nIPv4 result is unconfirmed. If a change began, the target will '
                    'restore the previous configuration after 45 seconds unless confirmation already completed. '
                    'Reconnect and refresh the interfaces before retrying.') from None
        result['confirmed'] = True
        result['persistent'] = confirmed.get('persistent', False)
        return result
