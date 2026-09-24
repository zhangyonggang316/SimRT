"""Prepare an Ubuntu X280 for MATLAB SSH builds.

The password is read from X280_SSH_PASSWORD or prompted without echo. It is
never written to a file or included in a remote command line.
"""

import argparse
import base64
import getpass
import hashlib
import os
import shlex
import sys
import time

import paramiko


SUDOERS_PATH = "/etc/sudoers.d/90-zh-nopasswd"
SUDOERS_CONTENT = "zh ALL=(ALL:ALL) NOPASSWD: ALL\n"


def _run(client, argv, password=None, check=True):
    command = shlex.join(argv)
    if password is not None:
        command = "sudo -S -p '' -- " + command
    stdin, stdout, stderr = client.exec_command(command, timeout=600)
    if password is not None:
        stdin.write(password + "\n")
        stdin.flush()
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if check and status:
        raise RuntimeError(
            "Remote command failed ({}): {}\n{}".format(
                status, command.replace("sudo -S -p '' -- ", "sudo -- "), error
            )
        )
    return status, output, error


def _host_key_sha256(client):
    key = client.get_transport().get_remote_server_key().asbytes()
    digest = hashlib.sha256(key).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _synchronize_clock(client, password):
    """Try NTP first, then set a close UTC value if the target is far behind."""
    _run(client, ["timedatectl", "set-ntp", "true"], password=password)
    for _ in range(5):
        _, synchronized, _ = _run(
            client,
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
        )
        if synchronized.strip() == "yes":
            return
        time.sleep(2)

    local_epoch = str(int(time.time()))
    _run(client, ["timedatectl", "set-ntp", "false"], password=password)
    _run(client, ["date", "-u", "-s", "@" + local_epoch], password=password)
    _run(client, ["timedatectl", "set-ntp", "true"], password=password)


def bootstrap(host, username, password, allow_xcp_udp=False):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=username,
        password=password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        print("Connected host key {}".format(_host_key_sha256(client)))
        _, actual_user, _ = _run(client, ["id", "-un"])
        if actual_user.strip() != username or username != "zh":
            raise RuntimeError("Refusing sudoers setup for unexpected remote user.")

        remote_temp = "/tmp/90-zh-nopasswd.{}.tmp".format(os.getpid())
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_temp, "w") as handle:
                handle.write(SUDOERS_CONTENT)
                handle.flush()
            sftp.chmod(remote_temp, 0o600)

            _run(client, ["visudo", "-cf", remote_temp], password=password)
            _run(
                client,
                [
                    "install",
                    "-o",
                    "root",
                    "-g",
                    "root",
                    "-m",
                    "0440",
                    remote_temp,
                    SUDOERS_PATH,
                ],
                password=password,
            )
            try:
                _run(client, ["visudo", "-cf", "/etc/sudoers"], password=password)
            except Exception:
                _run(client, ["rm", "-f", SUDOERS_PATH], password=password)
                raise
        finally:
            try:
                sftp.remove(remote_temp)
            except OSError:
                pass
            sftp.close()

        _run(client, ["sudo", "-n", "true"])
        _synchronize_clock(client, password)
        update_status, _, update_error = _run(
            client, ["apt-get", "update"], password=password, check=False
        )
        if update_status:
            print(
                "apt-get update reported a pre-existing repository error; "
                "continuing with valid package indexes:\n{}".format(update_error.strip())
            )
        _run(
            client,
            [
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "apt-get",
                "install",
                "-y",
                "build-essential",
                "tar",
            ],
            password=password,
        )

        if allow_xcp_udp:
            status, output, _ = _run(client, ["sudo", "-n", "ufw", "status"], check=False)
            if status == 0 and output.lstrip().startswith("Status: active"):
                _run(client, ["ufw", "allow", "17725/udp"], password=password)

        _, tools, _ = _run(
            client,
            [
                "sh",
                "-c",
                "command -v gcc && command -v g++ && command -v make && command -v tar",
            ],
        )
        _, sudo_rule, _ = _run(
            client,
            ["sudo", "-n", "visudo", "-cf", SUDOERS_PATH],
        )
        print("Toolchain ready:\n{}".format(tools.strip()))
        print(sudo_rule.strip())
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.0.106")
    parser.add_argument("--username", default="zh")
    parser.add_argument("--allow-xcp-udp", action="store_true")
    args = parser.parse_args()
    password = os.environ.get("X280_SSH_PASSWORD")
    if password is None:
        password = getpass.getpass("X280 SSH/sudo password: ")
    if not password:
        parser.error("A non-empty SSH password is required.")
    bootstrap(args.host, args.username, password, args.allow_xcp_udp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
