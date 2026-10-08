"""Extract one deployment ZIP into a private, process-owned directory."""

from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from .model_payload import file_hash, validate_payload


MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_PAYLOAD_BYTES = 1024 * 1024 * 1024


class PayloadArchive:
    def __init__(self):
        self._directories = []
        self._cached = None

    def load(self, source):
        source = Path(source).expanduser().absolute()
        if source.is_dir():
            payload = validate_payload(source)
            payload['source'] = str(source)
            return payload
        if (source.suffix.lower() != '.zip' or not source.is_file()
                or any(path.is_symlink() for path in [source] + list(source.parents))):
            raise ValueError('请选择模型 ZIP 文件或产物目录。')
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('模型 ZIP 文件超过 512 MiB 限制。')
        identity = (str(source), file_hash(source))
        if self._cached and identity == self._cached[0]:
            payload = validate_payload(self._cached[1])
            payload['source'] = str(source)
            return payload
        temporary = tempfile.TemporaryDirectory(prefix='qt-xcp-payload-')
        try:
            root = Path(temporary.name)
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if not 3 <= len(entries) <= 4:
                    raise ValueError('ZIP 必须只包含一个结果文件夹及 ELF、A2L、JSON 三个文件。')
                seen, files, folders, total = set(), [], set(), 0
                for entry in entries:
                    name = entry.filename
                    path = PurePosixPath(name)
                    parts = path.parts
                    canonical = path.as_posix() + ('/' if entry.is_dir() else '')
                    if (not parts or name.startswith('/') or '\\' in name
                            or any(char in name for char in ':<>"|?*')
                            or name != entry.orig_filename or canonical != name or len(parts) > 2
                            or any(part in ('.', '..') or part.endswith((' ', '.'))
                                   or any(ord(char) < 32 for char in part) for part in parts)):
                        raise ValueError('ZIP 含有不安全的路径。')
                    if any(part.split('.')[0].upper() in
                           {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % n for n in range(1, 10)),
                            *('LPT%d' % n for n in range(1, 10))} for part in parts):
                        raise ValueError('ZIP 含有系统保留文件名。')
                    key = path.as_posix().casefold()
                    if key in seen:
                        raise ValueError('ZIP 含有重复文件名。')
                    seen.add(key)
                    mode = stat.S_IFMT(entry.external_attr >> 16)
                    if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                        raise ValueError('ZIP 不支持链接、特殊文件或加密条目。')
                    if entry.is_dir():
                        if len(parts) != 1 or mode == stat.S_IFREG:
                            raise ValueError('ZIP 只能包含一层结果文件夹。')
                        folders.add(parts[0])
                        continue
                    if len(parts) != 2 or mode == stat.S_IFDIR:
                        raise ValueError('ZIP 中的三个文件必须位于同一个结果文件夹。')
                    folders.add(parts[0])
                    total += entry.file_size
                    if entry.file_size < 0 or total > MAX_PAYLOAD_BYTES:
                        raise ValueError('ZIP 解压内容超过 1 GiB 限制。')
                    files.append((entry, parts))
                if len(files) != 3 or len(folders) != 1:
                    raise ValueError('ZIP 必须包含一套 ELF、A2L、JSON。')
                copied = 0
                for entry, parts in files:
                    destination = root.joinpath(*parts)
                    destination.parent.mkdir(exist_ok=True)
                    with archive.open(entry) as incoming, destination.open('xb') as outgoing:
                        while True:
                            chunk = incoming.read(1024 * 1024)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > MAX_PAYLOAD_BYTES:
                                raise ValueError('ZIP 解压内容超过 1 GiB 限制。')
                            outgoing.write(chunk)
                payload = validate_payload(root / next(iter(folders)))
                names = set(payload['files'])
                expected = {Path(payload[key]).name for key in ('elf', 'a2l', 'manifest')}
                if names != expected or not payload['elf_name'].endswith('.elf') or not payload['a2l'].endswith('.a2l'):
                    raise ValueError('ZIP 必须只含匹配的 ELF、A2L、manifest JSON。')
            self._directories.append(temporary)
            self._cached = identity, payload['directory']
            payload['source'] = str(source)
            return payload
        except BaseException:
            temporary.cleanup()
            raise

    def close(self):
        for temporary in self._directories:
            temporary.cleanup()
        self._directories.clear()
        self._cached = None
