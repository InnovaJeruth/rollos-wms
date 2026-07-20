"""
txt_parser.py
Parsea el export .txt de /SCWM/MON y publica el inventario en GitHub
en el mismo formato que espera la PWA WMS Rollos (inventario/actual.json).

Formato del wrapper en GitHub (igual que pushInventoryToGitHub en common.js):
  { "compressed": "gzip", "updated_at": "...", "count": N, "data": "<base64gzip>" }
  donde data es base64( gzip( JSON.stringify({ updated_at, items }) ) )

Campos del objeto rollo (mismos que parseExcel en common.js):
  { lote, producto, descripcion, ubicacion, cantidad, unidad }
"""

import base64
import datetime
import gzip
import json

import github_client as gh


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _norm_lote(lote: str) -> str:
    """Replica normLote() de common.js: trim solamente (preserva ceros SAP)."""
    return lote.strip() or "0"


def _parse_cantidad(s: str) -> float:
    """Parsea cantidad del .txt (puede tener punto como separador de miles)."""
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

def parsear_txt(ruta_txt: str) -> list:
    """
    Parsea el archivo .txt exportado por /SCWM/MON.
    Formato de cada fila de datos:
      |A001|A001-01-01-01 |  0 |  0 |  93 |  93 |M  |1000070511005|FORRO...|A1|...|PP30|PP30|15:28|18.07.2024|G2333|
    Indices tras split('|') y strip():
      [2] ubicacion  [5] CtdDispUMB (disponible)  [7] unidad
      [8] producto   [9] descripcion               [16] lote

    Devuelve lista de dicts; duplicados por lote se resuelven quedando el ultimo
    (igual que parseExcel en common.js).
    """
    por_lote: dict = {}

    with open(ruta_txt, encoding="latin-1") as f:
        for line in f:
            line = line.rstrip()
            partes = [p.strip() for p in line.split("|")]
            if len(partes) < 17 or not partes[1].startswith("A"):
                continue

            lote_raw = partes[16]
            if not lote_raw or lote_raw.startswith("-") or lote_raw == "Lote":
                continue

            lote = _norm_lote(lote_raw)
            if not lote or lote == "0":
                continue

            por_lote[lote] = {
                "lote":        lote,
                "producto":    partes[8],
                "descripcion": partes[9],
                "ubicacion":   partes[2],
                "cantidad":    _parse_cantidad(partes[5]),
                "unidad":      partes[7],
            }

    return list(por_lote.values())


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline completo: .txt → gzip JSON → GitHub
# ─────────────────────────────────────────────────────────────────────────────

def publicar_inventario(ruta_txt: str) -> dict:
    """
    Parsea ruta_txt, comprime con gzip y sube a GitHub como inventario/actual.json.
    Devuelve {"updated_at": ..., "count": N, "size_kb": N}.
    """
    items = parsear_txt(ruta_txt)
    if not items:
        raise ValueError(f"No se encontraron rollos en {ruta_txt}")

    updated_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    inner = json.dumps(
        {"updated_at": updated_at, "items": items},
        ensure_ascii=False, separators=(",", ":"),
    )
    gz_bytes = gzip.compress(inner.encode("utf-8"), compresslevel=9)
    data_b64 = base64.b64encode(gz_bytes).decode("ascii")

    wrapper = json.dumps({
        "compressed": "gzip",
        "updated_at": updated_at,
        "count":      len(items),
        "data":       data_b64,
    }, ensure_ascii=False)

    gh.subir_archivo(
        "inventario/actual.json",
        wrapper,
        f"inv: {len(items)} rollos, {round(len(wrapper) / 1024)} KB gzip — bot Python",
    )

    return {
        "updated_at": updated_at,
        "count":      len(items),
        "size_kb":    round(len(wrapper) / 1024),
    }
