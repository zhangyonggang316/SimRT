"""Read model groups and concrete XCP endpoints from ASAP2 blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Tuple


# Comments and quoted strings must be consumed before recognizing block tokens.
_TOKEN = re.compile(r'/\*.*?\*/|//[^\r\n]*|"(?:\\.|[^"\\])*"|(?:(?!/\*|//)[^\s"])+', re.DOTALL)
_MODEL_GROUP = re.compile(r'X280_ModelHierarchy_[0-9]+\Z')


@dataclass
class _Block:
    kind: str
    tokens: List[str] = field(default_factory=list)
    children: List['_Block'] = field(default_factory=list)


def _blocks(text: str) -> _Block:
    root = _Block('DOCUMENT')
    stack = [root]
    tokens = iter(_TOKEN.finditer(text))
    for match in tokens:
        token = match.group()
        if token.startswith(('/*', '//')):
            continue
        if token.lower() in ('/begin', '/end'):
            following = next(tokens, None)
            while following and following.group().startswith(('/*', '//')):
                following = next(tokens, None)
            if following is None:
                raise ValueError('Truncated ASAP2 block boundary')
            kind = following.group().upper()
            if token.lower() == '/begin':
                child = _Block(kind)
                stack[-1].children.append(child)
                stack.append(child)
            elif len(stack) < 2 or stack.pop().kind != kind:
                raise ValueError('Mismatched ASAP2 block boundary')
        else:
            if token.startswith('"'):
                token = re.sub(r'\\(["\\])', r'\1', token[1:-1])
            stack[-1].tokens.append(token)
    if len(stack) != 1:
        raise ValueError('Unclosed ASAP2 block')
    return root


def _walk(block):
    if block.kind == 'A2ML':
        return
    yield block
    for child in block.children:
        yield from _walk(child)


def _group_paths(blocks):
    groups = {}
    parents = {}
    for block in blocks:
        if block.kind != 'GROUP':
            continue
        if len(block.tokens) < 2:
            raise ValueError('Truncated ASAP2 GROUP')
        name = block.tokens[0]
        if name in groups:
            raise ValueError('Duplicate ASAP2 GROUP: ' + name)
        groups[name] = block
        for child in block.children:
            if child.kind == 'SUB_GROUP':
                for subgroup in child.tokens:
                    if subgroup in parents and parents[subgroup] != name:
                        raise ValueError('ASAP2 GROUP has multiple parents: ' + subgroup)
                    parents[subgroup] = name

    paths = {}

    def path_for(name, visiting):
        if name in paths:
            return paths[name]
        if name in visiting:
            raise ValueError('Cyclic ASAP2 GROUP hierarchy: ' + name)
        group = groups[name]
        label = group.tokens[1] if _MODEL_GROUP.fullmatch(name) else name
        parent = parents.get(name)
        if parent and parent not in groups:
            raise ValueError('Unknown ASAP2 parent GROUP: ' + parent)
        prefix = path_for(parent, visiting | {name}) if parent else ()
        paths[name] = prefix + (label,)
        return paths[name]

    membership = {}
    for name, group in groups.items():
        path = path_for(name, set())
        for child in group.children:
            kind = {'REF_MEASUREMENT': 'MEASUREMENT',
                    'REF_CHARACTERISTIC': 'CHARACTERISTIC'}.get(child.kind)
            if kind:
                for scalar in child.tokens:
                    key = (kind, scalar)
                    if key not in membership:
                        membership[key] = path
                    else:
                        # Shared data belongs at its common model ancestor.
                        previous = membership[key]
                        length = 0
                        for first, second in zip(previous, path):
                            if first != second:
                                break
                            length += 1
                        membership[key] = previous[:length]
    return membership


def read_metadata(path: Path):
    blocks = tuple(_walk(_blocks(Path(path).read_text(encoding='utf-8-sig', errors='replace'))))
    ports: Dict[str, int] = {}
    hosts: Dict[str, str] = {}
    for block in blocks:
        protocol = {'XCP_ON_TCP_IP': 'TCP', 'XCP_ON_UDP_IP': 'UDP'}.get(block.kind)
        if protocol is None:
            continue
        if len(block.tokens) < 2:
            raise ValueError('Truncated XCP transport metadata')
        port_text = block.tokens[1]
        try:
            port = int(port_text, 16 if port_text.lower().startswith('0x') else 10)
        except ValueError as exc:
            raise ValueError('Invalid XCP port: ' + port_text) from exc
        if not 1 <= port <= 65535:
            raise ValueError('XCP port must be between 1 and 65535')
        host = ''
        for keyword in ('ADDRESS', 'HOST_NAME'):
            for index, value in enumerate(block.tokens[2:-1], 2):
                if value.upper() == keyword:
                    host = block.tokens[index + 1].strip()
                    break
            if host:
                break
        if protocol in ports and (ports[protocol] != port or hosts.get(protocol, '') != host):
            raise ValueError('Conflicting XCP {} endpoints'.format(protocol))
        ports[protocol] = port
        if host:
            hosts[protocol] = host
    transports = tuple(item for item in ('TCP', 'UDP') if item in ports)
    return _group_paths(blocks), transports, ports, hosts
