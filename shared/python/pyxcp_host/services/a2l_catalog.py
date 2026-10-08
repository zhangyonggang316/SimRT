"""Load the scalar subset of ASAP2 required by the host UI."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple

from ..models import CatalogInfo, ScalarView
from .backend import A2LDatabase, A2LScalar, parse_a2l
from .a2l_metadata import read_metadata


class A2LCatalogService:
    def __init__(self) -> None:
        self.database = None  # type: A2LDatabase
        self.info = None  # type: CatalogInfo

    def load(self, file_path: Path) -> CatalogInfo:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".a2l":
            raise ValueError("请选择存在的 .a2l 文件。")
        database = parse_a2l(path)
        if not database.scalars:
            raise ValueError(
                "A2L 中没有可直接访问的基础标量 CHARACTERISTIC 或 MEASUREMENT。"
            )
        paths, transports, ports, hosts = read_metadata(path)
        info = CatalogInfo(
            path=path,
            byte_order=database.byte_order,
            measurements=self._views(database.measurements, paths),
            calibrations=self._views(database.characteristics, paths),
            declared_transports=transports,
            declared_ports=ports,
            declared_hosts=hosts,
        )
        self.database = database
        self.info = info
        return info

    def scalar(self, name: str, kind: str) -> A2LScalar:
        if self.database is None:
            raise RuntimeError("请先加载 A2L 文件。")
        return self.database.get(name, kind)

    @staticmethod
    def _views(scalars: Iterable[A2LScalar], paths) -> Tuple[ScalarView, ...]:
        return tuple(
            ScalarView(
                name=item.name,
                kind=item.kind,
                address=item.address,
                address_extension=item.address_extension,
                data_type=item.data_type,
                size=item.size,
                model_path=paths.get((item.kind, item.name), ()),
            )
            for item in scalars
        )

    @staticmethod
    def _transport_metadata(path: Path) -> Tuple[Tuple[str, ...], Dict[str, int]]:
        _, transports, ports, _ = read_metadata(path)
        return transports, ports
