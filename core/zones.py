"""
Geofence zones — named circular areas the user defines (Home, Work, Gym).

The mobile app polls location while foreground (or via Android background
geofence APIs later) and POSTs an event to /api/mobile/geofence-event when
it crosses a zone boundary. The server fires routines whose triggers match.

Schema (SQLite):
    zones(id, name, latitude, longitude, radius_m, created_at)
"""

from __future__ import annotations

import math
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger


_DB = Path(__file__).resolve().parent.parent / "data" / "zones.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB, check_same_thread=False)


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                latitude    REAL NOT NULL,
                longitude   REAL NOT NULL,
                radius_m    INTEGER NOT NULL DEFAULT 200,
                created_at  TEXT NOT NULL
            )
        """)
        c.commit()


_init()


# ── CRUD ────────────────────────────────────────────────────────
def create(name: str, latitude: float, longitude: float,
           radius_m: int = 200) -> int:
    name = name.strip()
    if not name:
        raise ValueError("zone name required")
    radius_m = max(50, min(int(radius_m), 5000))
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO zones (name, latitude, longitude, radius_m, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 latitude=excluded.latitude,
                 longitude=excluded.longitude,
                 radius_m=excluded.radius_m""",
            (name, float(latitude), float(longitude), radius_m, now),
        )
        zid = int(cur.lastrowid or 0)
        if zid == 0:
            row = c.execute("SELECT id FROM zones WHERE name=?", (name,)).fetchone()
            zid = row[0] if row else 0
        c.commit()
    logger.info(f"zone[{zid}] '{name}' at ({latitude:.5f}, {longitude:.5f}) r={radius_m}m")
    return zid


def delete(zone_id: int) -> bool:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM zones WHERE id=?", (zone_id,))
        c.commit()
        return (cur.rowcount or 0) > 0


def get_by_name(name: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, name, latitude, longitude, radius_m, created_at "
            "FROM zones WHERE LOWER(name)=LOWER(?)",
            (name,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_all() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, latitude, longitude, radius_m, created_at "
            "FROM zones ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r) -> dict:
    return {
        "id": r[0],
        "name": r[1],
        "latitude": r[2],
        "longitude": r[3],
        "radius_m": r[4],
        "created_at": r[5],
    }


# ── Distance helper (haversine, used by API to find which zone is near) ──
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0  # earth radius (m)
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def find_containing(latitude: float, longitude: float) -> list[dict]:
    """Return zones whose radius contains the given coordinates."""
    out: list[dict] = []
    for z in list_all():
        d = haversine_m(latitude, longitude, z["latitude"], z["longitude"])
        if d <= z["radius_m"]:
            out.append({**z, "distance_m": int(d)})
    return out
