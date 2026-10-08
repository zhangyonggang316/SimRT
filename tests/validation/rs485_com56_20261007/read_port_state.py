"""Read termios and modem/RS485 status for the authorized COM5/6 candidates."""
import json
from pathlib import Path

from preflight import SSHDeployment, credentials, sudo_python

PROGRAM = r'''
import array, fcntl, json, os, termios
result = []
for path in ('/dev/ttyS6', '/dev/ttyS7'):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        attributes = termios.tcgetattr(descriptor)
        record = dict(device=path, termios_flags=attributes[:4],
                      input_speed=attributes[4], output_speed=attributes[5])
        for name, request, words in (('rs485', 0x542e, 8), ('modem', termios.TIOCMGET, 1)):
            data = array.array('I', [0] * words)
            try:
                fcntl.ioctl(descriptor, request, data, True)
                record[name] = data.tolist()
            except OSError as error:
                record[name + '_errno'] = error.errno
        result.append(record)
    finally:
        os.close(descriptor)
print(json.dumps(result))
'''


def main():
    login = credentials()
    service = SSHDeployment()
    try:
        service.connect(**login)
        result = json.loads(sudo_python(service, login, PROGRAM))
        Path(__file__).with_name('port_state.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
