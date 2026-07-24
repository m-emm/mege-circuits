"""Installed physical package and component pinout catalog."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

SEMANTIC_TERMINALS_BY_KIND = {
    "bjt_npn": frozenset(("collector", "base", "emitter")),
    "bjt_pnp": frozenset(("collector", "base", "emitter")),
    "bjt_npn_darlington": frozenset(("collector", "base", "emitter")),
    "bjt_pnp_darlington": frozenset(("collector", "base", "emitter")),
    "voltage_regulator": frozenset(("input", "ground", "output")),
}


@dataclass(frozen=True)
class PackageDefinition:
    """Normalized marked-face convention for one physical package."""

    id: str
    marked_face: str
    marked_face_lead_order: tuple[int, ...]
    leads_direction: str
    body_side: str


@dataclass(frozen=True)
class DevicePinout:
    """One manufacturer/package pinout variant."""

    id: str
    pins: dict[int, str]
    source_ids: tuple[str, ...]
    manufacturer: str | None = None
    package_designation: str | None = None


@dataclass(frozen=True)
class DeviceDefinition:
    """Catalog entry for one orderable or commonly marked device."""

    id: str
    package: str
    kind: str
    description: str
    aliases: tuple[str, ...]
    default_pinout: str
    pinouts: dict[str, DevicePinout]
    marking: str | None = None
    selection_note: str | None = None
    evidence: dict[str, str] | None = None

    def resolve_pinout(self, variant: str | None = None) -> DevicePinout:
        """Resolve an optional named variant, defaulting to the catalog choice."""
        pinout_id = variant or self.default_pinout
        try:
            return self.pinouts[pinout_id]
        except KeyError as error:
            raise ValueError(
                f"Unknown pinout variant {pinout_id!r} for part {self.id}; "
                f"choose one of {sorted(self.pinouts)}"
            ) from error


@dataclass(frozen=True)
class InventoryDefinition:
    """Recorded quantities and provenance for one physical assortment."""

    id: str
    description: str
    total_quantity: int
    source_id: str
    provenance: dict[str, Any]
    quantities: dict[str, int]


@dataclass(frozen=True)
class ComponentCatalog:
    """Validated installed component catalog."""

    packages: dict[str, PackageDefinition]
    devices: dict[str, DeviceDefinition]
    inventories: dict[str, InventoryDefinition]
    sources: dict[str, dict[str, str]]
    aliases: dict[str, str]

    def resolve_device(self, part: str) -> DeviceDefinition:
        """Resolve a canonical device id or alias, case-insensitively."""
        normalized = part.strip().casefold()
        device_id = self.aliases.get(normalized)
        if device_id is None:
            raise ValueError(f"Unknown catalog part: {part!r}")
        return self.devices[device_id]


def _require_mapping(value: Any, *, context: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _require_nonempty_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} must not be empty")
    return text


def _normalize_sources(raw_sources: Any) -> dict[str, dict[str, str]]:
    sources = {}
    for source_id, raw_source in _require_mapping(
        raw_sources, context="sources"
    ).items():
        normalized_id = _require_nonempty_text(source_id, context="source id")
        source = _require_mapping(raw_source, context=f"sources.{normalized_id}")
        title = _require_nonempty_text(
            source.get("title"), context=f"sources.{normalized_id}.title"
        )
        url = _require_nonempty_text(
            source.get("url"), context=f"sources.{normalized_id}.url"
        )
        sources[normalized_id] = {"title": title, "url": url}
    return sources


def _normalize_packages(raw_packages: Any) -> dict[str, PackageDefinition]:
    packages = {}
    for package_id, raw_package in _require_mapping(
        raw_packages, context="packages"
    ).items():
        normalized_id = _require_nonempty_text(package_id, context="package id")
        package = _require_mapping(raw_package, context=f"packages.{normalized_id}")
        raw_order = package.get("marked_face_lead_order")
        if not isinstance(raw_order, list) or not raw_order:
            raise ValueError(
                f"packages.{normalized_id}.marked_face_lead_order "
                "must be a non-empty list"
            )
        if any(
            isinstance(number, bool) or not isinstance(number, int)
            for number in raw_order
        ):
            raise ValueError(
                f"packages.{normalized_id}.marked_face_lead_order "
                "must contain integers"
            )
        lead_order = tuple(raw_order)
        if sorted(lead_order) != list(range(1, len(lead_order) + 1)):
            raise ValueError(
                f"packages.{normalized_id}.marked_face_lead_order "
                "must contain consecutive lead numbers 1..N"
            )
        packages[normalized_id] = PackageDefinition(
            id=normalized_id,
            marked_face=_require_nonempty_text(
                package.get("marked_face"),
                context=f"packages.{normalized_id}.marked_face",
            ),
            marked_face_lead_order=lead_order,
            leads_direction=_require_nonempty_text(
                package.get("leads_direction"),
                context=f"packages.{normalized_id}.leads_direction",
            ),
            body_side=_require_nonempty_text(
                package.get("body_side"),
                context=f"packages.{normalized_id}.body_side",
            ),
        )
    return packages


def _normalize_pinout(
    raw_pinout: Any,
    *,
    context: str,
    pinout_id: str,
    expected_pin_numbers: tuple[int, ...],
    expected_terminals: frozenset[str],
    sources: dict[str, dict[str, str]],
) -> DevicePinout:
    pinout = _require_mapping(raw_pinout, context=context)
    raw_pins = _require_mapping(pinout.get("pins"), context=f"{context}.pins")
    pins = {}
    for raw_number, raw_terminal in raw_pins.items():
        if isinstance(raw_number, bool):
            raise ValueError(f"{context}.pins keys must be integer lead numbers")
        try:
            number = int(raw_number)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{context}.pins keys must be integer lead numbers"
            ) from error
        pins[number] = _require_nonempty_text(
            raw_terminal, context=f"{context}.pins[{number}]"
        )
    if tuple(sorted(pins)) != expected_pin_numbers:
        raise ValueError(
            f"{context}.pins must define exactly {list(expected_pin_numbers)}"
        )
    if set(pins.values()) != expected_terminals:
        raise ValueError(
            f"{context}.pins must map exactly {sorted(expected_terminals)}"
        )

    raw_source_ids = pinout.get("sources")
    if not isinstance(raw_source_ids, list) or not raw_source_ids:
        raise ValueError(f"{context}.sources must be a non-empty list")
    source_ids = tuple(
        _require_nonempty_text(source_id, context=f"{context}.sources")
        for source_id in raw_source_ids
    )
    unknown_sources = sorted(set(source_ids) - set(sources))
    if unknown_sources:
        raise ValueError(f"{context} references unknown sources: {unknown_sources}")

    raw_manufacturer = pinout.get("manufacturer")
    manufacturer = (
        _require_nonempty_text(raw_manufacturer, context=f"{context}.manufacturer")
        if raw_manufacturer is not None
        else None
    )
    raw_package_designation = pinout.get("package_designation")
    package_designation = (
        _require_nonempty_text(
            raw_package_designation,
            context=f"{context}.package_designation",
        )
        if raw_package_designation is not None
        else None
    )
    return DevicePinout(
        id=pinout_id,
        pins=pins,
        source_ids=source_ids,
        manufacturer=manufacturer,
        package_designation=package_designation,
    )


def _normalize_devices(
    raw_devices: Any,
    *,
    packages: dict[str, PackageDefinition],
    sources: dict[str, dict[str, str]],
) -> tuple[dict[str, DeviceDefinition], dict[str, str]]:
    devices = {}
    aliases = {}
    for device_id, raw_device in _require_mapping(
        raw_devices, context="devices"
    ).items():
        normalized_id = _require_nonempty_text(device_id, context="device id")
        device = _require_mapping(raw_device, context=f"devices.{normalized_id}")
        package_id = _require_nonempty_text(
            device.get("package"), context=f"devices.{normalized_id}.package"
        )
        if package_id not in packages:
            raise ValueError(
                f"devices.{normalized_id} references unknown package {package_id!r}"
            )
        kind = _require_nonempty_text(
            device.get("kind"), context=f"devices.{normalized_id}.kind"
        )
        try:
            expected_terminals = SEMANTIC_TERMINALS_BY_KIND[kind]
        except KeyError as error:
            raise ValueError(
                f"devices.{normalized_id} has unsupported kind {kind!r}"
            ) from error
        description = _require_nonempty_text(
            device.get("description"),
            context=f"devices.{normalized_id}.description",
        )
        default_pinout = _require_nonempty_text(
            device.get("default_pinout"),
            context=f"devices.{normalized_id}.default_pinout",
        )
        raw_aliases = device.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ValueError(f"devices.{normalized_id}.aliases must be a list")
        device_aliases = tuple(
            _require_nonempty_text(alias, context=f"devices.{normalized_id}.aliases")
            for alias in raw_aliases
        )

        package = packages[package_id]
        raw_pinouts = _require_mapping(
            device.get("pinouts"), context=f"devices.{normalized_id}.pinouts"
        )
        pinouts = {
            _require_nonempty_text(pinout_id, context="pinout id"): _normalize_pinout(
                raw_pinout,
                context=f"devices.{normalized_id}.pinouts.{pinout_id}",
                pinout_id=str(pinout_id),
                expected_pin_numbers=package.marked_face_lead_order,
                expected_terminals=expected_terminals,
                sources=sources,
            )
            for pinout_id, raw_pinout in raw_pinouts.items()
        }
        if default_pinout not in pinouts:
            raise ValueError(
                f"devices.{normalized_id}.default_pinout references "
                f"unknown pinout {default_pinout!r}"
            )

        raw_marking = device.get("marking")
        marking = (
            _require_nonempty_text(
                raw_marking, context=f"devices.{normalized_id}.marking"
            )
            if raw_marking is not None
            else None
        )
        raw_selection_note = device.get("selection_note")
        selection_note = (
            _require_nonempty_text(
                raw_selection_note,
                context=f"devices.{normalized_id}.selection_note",
            )
            if raw_selection_note is not None
            else None
        )
        raw_evidence = device.get("evidence")
        evidence = (
            {
                _require_nonempty_text(
                    key, context=f"devices.{normalized_id}.evidence key"
                ): _require_nonempty_text(
                    value,
                    context=f"devices.{normalized_id}.evidence.{key}",
                )
                for key, value in _require_mapping(
                    raw_evidence,
                    context=f"devices.{normalized_id}.evidence",
                ).items()
            }
            if raw_evidence is not None
            else None
        )
        devices[normalized_id] = DeviceDefinition(
            id=normalized_id,
            package=package_id,
            kind=kind,
            description=description,
            aliases=device_aliases,
            default_pinout=default_pinout,
            pinouts=pinouts,
            marking=marking,
            selection_note=selection_note,
            evidence=evidence,
        )

        for alias in (normalized_id, *device_aliases):
            alias_key = alias.casefold()
            prior_device = aliases.get(alias_key)
            if prior_device is not None:
                raise ValueError(
                    f"Catalog alias {alias!r} belongs to both "
                    f"{prior_device} and {normalized_id}"
                )
            aliases[alias_key] = normalized_id
    return devices, aliases


def _normalize_inventories(
    raw_inventories: Any,
    *,
    devices: dict[str, DeviceDefinition],
    sources: dict[str, dict[str, str]],
) -> dict[str, InventoryDefinition]:
    inventories = {}
    for inventory_id, raw_inventory in _require_mapping(
        raw_inventories, context="inventories"
    ).items():
        normalized_id = _require_nonempty_text(inventory_id, context="inventory id")
        inventory = _require_mapping(
            raw_inventory, context=f"inventories.{normalized_id}"
        )
        total_quantity = inventory.get("total_quantity")
        if (
            isinstance(total_quantity, bool)
            or not isinstance(total_quantity, int)
            or total_quantity <= 0
        ):
            raise ValueError(
                f"inventories.{normalized_id}.total_quantity must be "
                "a positive integer"
            )
        source_id = _require_nonempty_text(
            inventory.get("source"),
            context=f"inventories.{normalized_id}.source",
        )
        if source_id not in sources:
            raise ValueError(
                f"inventories.{normalized_id} references unknown source {source_id!r}"
            )
        raw_quantities = _require_mapping(
            inventory.get("quantities"),
            context=f"inventories.{normalized_id}.quantities",
        )
        quantities = {}
        for raw_device_id, raw_quantity in raw_quantities.items():
            device_id = _require_nonempty_text(
                raw_device_id,
                context=f"inventories.{normalized_id}.quantities device",
            )
            if device_id not in devices:
                raise ValueError(
                    f"inventories.{normalized_id} references unknown "
                    f"device {device_id!r}"
                )
            if (
                isinstance(raw_quantity, bool)
                or not isinstance(raw_quantity, int)
                or raw_quantity <= 0
            ):
                raise ValueError(
                    f"inventories.{normalized_id}.quantities.{device_id} "
                    "must be a positive integer"
                )
            quantities[device_id] = raw_quantity
        if sum(quantities.values()) != total_quantity:
            raise ValueError(
                f"inventories.{normalized_id} quantities total "
                f"{sum(quantities.values())}, expected {total_quantity}"
            )
        raw_provenance = inventory.get("provenance", {})
        provenance = _require_mapping(
            raw_provenance, context=f"inventories.{normalized_id}.provenance"
        )
        inventories[normalized_id] = InventoryDefinition(
            id=normalized_id,
            description=_require_nonempty_text(
                inventory.get("description"),
                context=f"inventories.{normalized_id}.description",
            ),
            total_quantity=total_quantity,
            source_id=source_id,
            provenance={str(key): value for key, value in provenance.items()},
            quantities=quantities,
        )
    return inventories


def _load_component_catalog(catalog_path: Path) -> ComponentCatalog:
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    data = _require_mapping(raw, context="catalog root")
    if data.get("catalog_version") != 1:
        raise ValueError("component catalog requires catalog_version: 1")
    sources = _normalize_sources(data.get("sources"))
    packages = _normalize_packages(data.get("packages"))
    devices, aliases = _normalize_devices(
        data.get("devices"), packages=packages, sources=sources
    )
    inventories = _normalize_inventories(
        data.get("inventories"), devices=devices, sources=sources
    )
    return ComponentCatalog(
        packages=packages,
        devices=devices,
        inventories=inventories,
        sources=sources,
        aliases=aliases,
    )


@lru_cache(maxsize=1)
def _load_installed_component_catalog() -> ComponentCatalog:
    catalog_resource = files("mege_circuits.pinout").joinpath("component_catalog.yaml")
    with catalog_resource.open("r", encoding="utf-8") as catalog_file:
        raw = yaml.safe_load(catalog_file)
    data = _require_mapping(raw, context="catalog root")
    if data.get("catalog_version") != 1:
        raise ValueError("component catalog requires catalog_version: 1")
    sources = _normalize_sources(data.get("sources"))
    packages = _normalize_packages(data.get("packages"))
    devices, aliases = _normalize_devices(
        data.get("devices"), packages=packages, sources=sources
    )
    inventories = _normalize_inventories(
        data.get("inventories"), devices=devices, sources=sources
    )
    return ComponentCatalog(
        packages=packages,
        devices=devices,
        inventories=inventories,
        sources=sources,
        aliases=aliases,
    )


def load_component_catalog(
    catalog_path: str | Path | None = None,
) -> ComponentCatalog:
    """Load the installed catalog or validate a supplied catalog file."""
    if catalog_path is None:
        return _load_installed_component_catalog()
    return _load_component_catalog(Path(catalog_path))
