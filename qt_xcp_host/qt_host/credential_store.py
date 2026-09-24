"""Optional current-user Windows DPAPI storage for the last SSH login."""

import ctypes
import json
import os
from pathlib import Path
import tempfile


class _DataBlob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(value, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Secure credential storage requires Windows DPAPI')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p if decrypt else ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
    function.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    try:
        # UI_FORBIDDEN, without LOCAL_MACHINE, binds protection to this user.
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise OSError('Windows credential protection failed (error {})'.format(ctypes.get_last_error()))
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(buffer, 0, len(buffer))
        if output.data:
            if decrypt:
                ctypes.memset(output.data, 0, output.size)
            kernel.LocalFree(output.data)


def _credentials(value):
    if (not isinstance(value, dict) or value.get('schema') != 1
            or set(value) != {'schema', 'host', 'username', 'password', 'port'}
            or type(value['port']) is not int or not 1 <= value['port'] <= 65535):
        raise ValueError('Invalid saved credential record')
    for name in ('host', 'username', 'password'):
        text = value[name]
        if not isinstance(text, str) or len(text) > 4096 or '\0' in text:
            raise ValueError('Invalid saved credential record')
        if name != 'password' and (not text.strip() or any(char in text for char in '\r\n')):
            raise ValueError('Invalid saved credential record')
    return {name: value[name] for name in ('host', 'username', 'password', 'port')}


class CredentialStore:
    def __init__(self, path=None, protect=None, unprotect=None):
        self.path = Path(path) if path is not None else (
            Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
            / 'X280XcpHost' / 'ssh_credentials.dpapi')
        self.available = os.name == 'nt' or protect is not None and unprotect is not None
        self._protect = protect or _dpapi
        self._unprotect = unprotect or (lambda value: _dpapi(value, decrypt=True))

    def _regular_path(self):
        if any(path.is_symlink() for path in [self.path] + list(self.path.parents)):
            raise ValueError('Credential path cannot contain symbolic links')

    def load(self):
        if not self.available:
            return None
        self._regular_path()
        if not self.path.exists():
            return None
        if not self.path.is_file() or not 0 < self.path.stat().st_size <= 65536:
            raise ValueError('Invalid encrypted credential file')
        try:
            value = json.loads(self._unprotect(self.path.read_bytes()).decode('utf-8'))
            return _credentials(value)
        except (ValueError, UnicodeError) as error:
            raise ValueError('Saved SSH credentials could not be restored') from error

    def save(self, host, username, password, port):
        if not self.available:
            raise RuntimeError('Secure credential storage is unavailable')
        value = dict(schema=1, host=host, username=username, password=password, port=port)
        _credentials(value)
        encrypted = self._protect(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if not isinstance(encrypted, bytes) or not encrypted:
            raise ValueError('Credential encryption returned no data')
        self._regular_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.ssh_credentials.', suffix='.dpapi', dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def clear(self):
        self._regular_path()
        if self.path.exists():
            self.path.unlink()
