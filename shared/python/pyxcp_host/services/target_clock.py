"""One deferred, bounded clock synchronization per application SSH connection."""

from datetime import datetime
import json
import math
import re
import shlex
import threading
import time


CPU_LIMIT = 50.0
IDLE_SECONDS = 4.0
MAX_SAMPLE_GAP = 6.0
RETRY_SECONDS = 30.0
MAX_FAILURES = 3


_CLOCK_HELPER = r'''
import datetime, json, math, os, pathlib, re, subprocess, sys, time

def command(arguments):
    return subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=2, env=dict(os.environ, LC_ALL='C', TZ='UTC'))

def checked(arguments):
    result = command(arguments)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Clock command failed')
    return result.stdout.strip()

def model_running():
    for entry in pathlib.Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            executable = os.readlink(str(entry / 'exe'))
            if executable.endswith(' (deleted)'):
                executable = executable[:-10]
            if executable.lower().endswith('.elf'):
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return False

def cpu_times():
    answer = {}
    for line in pathlib.Path('/proc/stat').read_text().splitlines():
        fields = line.split()
        if fields and re.fullmatch(r'cpu\d*', fields[0]):
            values = [int(value) for value in fields[1:9]]
            answer[fields[0]] = (sum(values), values[3] + values[4])
    return answer

def idle():
    if model_running():
        return False
    before = cpu_times()
    time.sleep(.15)
    after = cpu_times()
    for name, (total, unused) in after.items():
        old_total, old_unused = before.get(name, (total, unused))
        elapsed, free = total - old_total, unused - old_unused
        if elapsed <= 0 or not 0 <= free <= elapsed or 100 * (elapsed - free) / elapsed >= 50:
            return False
    return bool(after) and not model_running()

def timezone_name():
    return checked(['timedatectl', 'show', '--property=Timezone', '--value'])

def apply(request):
    received = time.monotonic()
    epoch, zone = request['epoch'], request['timezone']
    if not isinstance(epoch, (int, float)) or not math.isfinite(epoch) or epoch <= 0:
        raise ValueError('Invalid host epoch')
    if (not isinstance(zone, str) or not re.fullmatch(r'[A-Za-z0-9_+\-/]+', zone)
            or zone.startswith('/') or '..' in zone.split('/')):
        raise ValueError('Invalid host timezone')
    zonefile = pathlib.Path('/usr/share/zoneinfo') / zone
    if not zonefile.is_file():
        raise ValueError('Host timezone is unavailable on target')
    if not idle():
        return dict(status='deferred', reason='target_busy')
    # TZ is process-local: compare the zone offset without changing the UTC epoch.
    os.environ['TZ'] = zone
    time.tzset()
    expected = epoch + time.monotonic() - received
    actual_offset = datetime.datetime.fromtimestamp(expected).astimezone().utcoffset().total_seconds()
    if actual_offset != request['utc_offset']:
        raise ValueError('Host and target timezone offsets differ')
    previous = timezone_name()
    if previous != zone:
        checked(['timedatectl', 'set-timezone', zone])
    expected = epoch + time.monotonic() - received
    offset = expected - time.time()
    method = 'already_aligned'
    if abs(offset) > 2.0:
        if model_running():
            return dict(status='deferred', reason='model_running')
        # Chrony keeps its configured NTP sources; never force a clock step.
        def settime():
            current = epoch + time.monotonic() - received
            stamp = datetime.datetime.fromtimestamp(current, datetime.timezone.utc)
            return command(['chronyc', '-n', '-t', '1', 'settime',
                            stamp.strftime('%Y-%m-%d %H:%M:%S UTC')])
        result = settime()
        enabled_here = result.stdout.startswith('505')
        if enabled_here:
            checked(['chronyc', '-n', '-t', '1', 'manual', 'on'])
            try:
                result = settime()
            finally:
                checked(['chronyc', '-n', '-t', '1', 'manual', 'off'])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Chrony rejected host time')
        method = 'chrony'
    return dict(status='synchronized', timezone=timezone_name(), method=method,
                offset_seconds=offset, ntp_preserved=True)

def main(request):
    if request['action'] == 'probe':
        available = idle()
        return dict(idle=available, epoch=time.time())
    if request['action'] == 'apply':
        if os.geteuid() != 0:
            raise PermissionError('Clock synchronization requires administrator privileges')
        return apply(request)
    raise ValueError('Unknown clock operation')

if __name__ == '__main__':
    print(json.dumps(main(json.loads(sys.argv[1]))))
'''


class TargetClockSync:
    def __init__(self, deployment, timezone_provider, monotonic=time.monotonic, epoch=time.time):
        self.deployment = deployment
        self.timezone_provider = timezone_provider
        self.monotonic = monotonic
        self.epoch = epoch
        self._cancelled = threading.Event()
        self.cancel()

    def cancel(self):
        self._cancelled.set()
        self._password = ''
        self.pending = False
        self._idle_since = self._last_sample = None
        self._samples = self._failures = 0
        self._retry_at = 0.0

    def arm(self, password):
        self.cancel()
        self._cancelled = threading.Event()
        self._password = password
        self.pending = True

    def observe(self, snapshot, process):
        if not self.pending:
            return
        now = self.monotonic()
        values = [snapshot.get('cpu_percent')] + list(snapshot.get('core_percents', []))
        idle = (process.get('running') is False and all(
            isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value < CPU_LIMIT
            for value in values))
        if (not idle or self._last_sample is not None and now - self._last_sample > MAX_SAMPLE_GAP):
            self._idle_since = None
            self._samples = 0
        if idle:
            if self._idle_since is None:
                self._idle_since = now
            self._samples += 1
        self._last_sample = now

    @property
    def ready(self):
        now = self.monotonic()
        return (self.pending and self._samples >= 3 and self._idle_since is not None
                and now - self._idle_since >= IDLE_SECONDS and now >= self._retry_at
                and self._last_sample is not None and now - self._last_sample <= MAX_SAMPLE_GAP)

    def _request(self, action, password=None, **values):
        payload = json.dumps(dict(values, action=action), allow_nan=False)
        command = 'nice -n 10 python3 -c {} {}'.format(shlex.quote(_CLOCK_HELPER), shlex.quote(payload))
        if password is not None:
            if any(character in password for character in '\r\n\x00'):
                raise ValueError('Administrator password contains an invalid control character')
            command = ('sudo -S -p ' + shlex.quote('') + ' -- ' if password else 'sudo -n -- ') + command
        result = json.loads(self.deployment._execute(command, timeout=10.0,
            input_data=(password + '\n').encode('utf-8') if password else None))
        if not isinstance(result, dict):
            raise ValueError('Invalid clock response from target')
        return result

    def synchronize(self):
        if not self.ready:
            return dict(status='deferred', reason='waiting_for_idle')
        cancelled, password = self._cancelled, self._password
        result = dict(status='cancelled')
        try:
            with self.deployment._operation_lock:
                if cancelled.is_set():
                    return result
                self.deployment._begin()
                if self.deployment.status().get('running') is not False:
                    return dict(status='deferred', reason='model_running')
                started = self.monotonic()
                probe = self._request('probe')
                elapsed = self.monotonic() - started
                if probe.get('idle') is not True or elapsed > 1.0:
                    return dict(status='deferred', reason='target_or_link_busy')
                zone = self.timezone_provider()
                if not isinstance(zone, str) or not re.fullmatch(r'[A-Za-z0-9_+\-/]+', zone):
                    raise ValueError('Windows timezone could not be mapped to an IANA timezone')
                # Read only after acquiring the worker/SSH lock and passing idle checks.
                current = self.epoch()
                offset = datetime.fromtimestamp(current).astimezone().utcoffset().total_seconds()
                if cancelled.is_set():
                    return result
                result = self._request('apply', password=password, epoch=current,
                                       timezone=zone, utc_offset=offset)
                if result.get('status') not in ('deferred', 'synchronized'):
                    raise ValueError('Target did not confirm clock synchronization')
                if result['status'] == 'synchronized' and not cancelled.is_set():
                    self.cancel()
                return result
        except Exception as error:
            if cancelled.is_set():
                return dict(status='cancelled')
            self._failures += 1
            message = str(error).replace(password, '[redacted]') if password else str(error)
            exhausted = self._failures >= MAX_FAILURES
            if exhausted:
                self.cancel()
            return dict(status='failed', error=message, retry=not exhausted)
        finally:
            password = None
            if self.pending and self._cancelled is cancelled:
                self._retry_at = self.monotonic() + RETRY_SECONDS
                self._idle_since = self._last_sample = None
                self._samples = 0
