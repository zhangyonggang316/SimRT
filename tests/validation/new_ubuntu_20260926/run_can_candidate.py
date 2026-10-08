"""Run the reusable CAN verifier with this deployment's pinned SSH identity."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_can_target
import target_session


class PinnedDeployment(verify_can_target.SSHDeployment):
    def connect(self, host, username, password='', port=22, key_filename=''):
        if (host, username, port) != (target_session.HOST, target_session.USER, 22):
            raise ValueError('This evidence runner requires the pinned target identity')
        if key_filename:
            raise ValueError('This evidence runner uses interactive password authentication')
        self.close()
        self._cancelled.clear()
        self._client = target_session.connect(password)
        self._identity = (host, port, username)
        self._host, self._username, self._port = host, username, port
        self._remote_elf, self._pid = '', None
        home = self._request('home')
        self._home = home['home']
        return dict(home, host=host, username=username, port=port)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--baseline' not in sys.argv:
        raise SystemExit('The installed generic kernel requires explicit --baseline evidence')
    verify_can_target.SSHDeployment = PinnedDeployment
    raise SystemExit(verify_can_target.main())
