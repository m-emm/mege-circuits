from pathlib import Path

import pytest
import yaml

from mege_circuits.pinout.catalog import load_component_catalog

EXPECTED_TRANSISTOR_INVENTORY = {
    "BC547B": 28,
    "BC557B": 28,
    "BC337": 12,
    "BC327": 12,
    "BC517": 6,
    "BC516": 6,
    "BD139": 4,
    "BD140": 4,
}


def test_installed_component_catalog_records_packages_devices_and_inventory():
    catalog = load_component_catalog()

    assert set(catalog.packages) == {"TO-92", "TO-126"}
    assert catalog.packages["TO-92"].marked_face == "flat"
    assert catalog.packages["TO-92"].marked_face_lead_order == (1, 2, 3)
    assert catalog.packages["TO-92"].leads_direction == "down"
    assert catalog.packages["TO-92"].body_side == "right_of_pin1_to_pin3"
    assert set(catalog.devices) == {
        *EXPECTED_TRANSISTOR_INVENTORY,
        "UTC_LP2950L_33_T92",
    }

    inventory = catalog.inventories["whadda_k_trans1"]
    assert inventory.quantities == EXPECTED_TRANSISTOR_INVENTORY
    assert inventory.total_quantity == sum(inventory.quantities.values()) == 100
    assert inventory.source_id == "whadda_k_trans1"
    assert inventory.provenance["item_key"] == 655
    assert inventory.provenance["carrier_key"] == 5882


@pytest.mark.parametrize(
    ("part", "package", "kind", "pinout"),
    [
        ("BC547B", "TO-92", "bjt_npn", ("collector", "base", "emitter")),
        ("BC557B", "TO-92", "bjt_pnp", ("collector", "base", "emitter")),
        ("BC337", "TO-92", "bjt_npn", ("collector", "base", "emitter")),
        ("BC327", "TO-92", "bjt_pnp", ("collector", "base", "emitter")),
        (
            "BC517",
            "TO-92",
            "bjt_npn_darlington",
            ("collector", "base", "emitter"),
        ),
        (
            "BC516",
            "TO-92",
            "bjt_pnp_darlington",
            ("collector", "base", "emitter"),
        ),
        ("BD139", "TO-126", "bjt_npn", ("emitter", "collector", "base")),
        ("BD140", "TO-126", "bjt_pnp", ("emitter", "collector", "base")),
        (
            "UTC_LP2950L_33_T92",
            "TO-92",
            "voltage_regulator",
            ("output", "ground", "input"),
        ),
    ],
)
def test_catalog_default_pinouts(
    part: str,
    package: str,
    kind: str,
    pinout: tuple[str, str, str],
):
    device = load_component_catalog().devices[part]

    assert device.package == package
    assert device.kind == kind
    assert tuple(device.resolve_pinout().pins.values()) == pinout


def test_catalog_preserves_bc337_bc327_manufacturer_variants_and_utc_aliases():
    catalog = load_component_catalog()

    for part in ("BC337", "BC327"):
        device = catalog.devices[part]
        assert device.default_pinout == "cbe"
        assert tuple(device.resolve_pinout("cbe").pins.values()) == (
            "collector",
            "base",
            "emitter",
        )
        assert tuple(device.resolve_pinout("ebc").pins.values()) == (
            "emitter",
            "base",
            "collector",
        )
        assert device.resolve_pinout("ebc").manufacturer == "Nexperia"
        assert device.selection_note is not None

    regulator = catalog.resolve_device("LP2950L-3.3")
    assert regulator.id == "UTC_LP2950L_33_T92"
    assert regulator.marking == "UTC / LP2950L / 33"
    assert regulator.evidence == {
        "received_photo_repository": "mege-ender-3v3ke-idex",
        "received_photo_path": "resources/tmc5160TPlus/IMG_9785.png",
    }
    assert catalog.resolve_device("lp2950l-33-t92-k") == regulator
    assert tuple(regulator.resolve_pinout().pins.values()) == (
        "output",
        "ground",
        "input",
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda data: data["devices"]["BC547B"].update(package="UNKNOWN"),
            "unknown package",
        ),
        (
            lambda data: data["devices"]["BC547B"]["pinouts"]["cbe"].update(
                pins={1: "collector", 2: "base", 3: "base"}
            ),
            "must map exactly",
        ),
        (
            lambda data: data["devices"]["BC547B"].update(kind="voltage_regulator"),
            "must map exactly",
        ),
        (
            lambda data: data["inventories"]["whadda_k_trans1"].update(
                total_quantity=99
            ),
            "quantities total",
        ),
    ],
)
def test_catalog_validation_rejects_inconsistent_records(
    tmp_path: Path,
    mutation,
    message: str,
):
    installed_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "mege_circuits"
        / "pinout"
        / "component_catalog.yaml"
    )
    data = yaml.safe_load(installed_path.read_text(encoding="utf-8"))
    mutation(data)
    invalid_path = tmp_path / "invalid_catalog.yaml"
    invalid_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_component_catalog(invalid_path)
