"""One-off helper to migrate legacy configuration files to the typed schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    default_storage_settings,
    load_station_config,
    load_storage_settings,
    save_station_config,
    save_storage_settings,
    storage_settings_from_env,
)
from .store import CONFIG_DIR, load_env_file


def migrate_station_config(path: Path) -> bool:
    """Rewrite sensors.yaml using the canonical schema."""

    try:
        station = load_station_config(path)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"✗ No se pudo leer {path}: {exc}")
        return False

    save_station_config(station, path)
    print(f"✓ Archivo {path.name} migrado al nuevo esquema")
    return True


def migrate_storage_config(path: Path, env_path: Path | None) -> bool:
    """Ensure storage.yaml exists and follows the typed schema."""

    if path.exists():
        try:
            load_storage_settings(path)
        except ValueError as exc:
            print(f"✗ storage.yaml existe pero es inválido: {exc}")
            return False
        print("✓ storage.yaml ya utiliza el nuevo formato; no se realizaron cambios")
        return True

    env_values = {}
    if env_path and env_path.exists():
        try:
            env_values = dict(load_env_file(env_path))
        except Exception as exc:  # pragma: no cover - optional dependency ausente
            print(f"! No se pudo leer {env_path}: {exc}")

    if env_values:
        settings = storage_settings_from_env(env_values)
        print(f"✓ Generando storage.yaml desde {env_path}")
    else:
        settings = default_storage_settings()
        print("! No se encontraron credenciales; se generó un storage.yaml de ejemplo")

    save_storage_settings(settings, path)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=CONFIG_DIR,
        help="Directorio donde residen sensors.yaml y storage.yaml",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="Ruta opcional a un archivo .env con credenciales de InfluxDB",
    )
    args = parser.parse_args(argv)

    cfg_dir = args.config_dir
    sensors_path = cfg_dir / "sensors.yaml"
    storage_path = cfg_dir / "storage.yaml"

    ok = True
    if sensors_path.exists():
        ok &= migrate_station_config(sensors_path)
    else:
        print(f"! {sensors_path} no existe; omitiendo migración de sensores")

    ok &= migrate_storage_config(storage_path, args.env)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

