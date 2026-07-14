"""
github_client.py
Cliente minimalista para la API REST de GitHub.
Operaciones que usa el bot WMS: listar, descargar, subir, eliminar y mover archivos.
Credenciales desde .env (GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH).
"""

import base64
import json
import os

import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_TOKEN  = os.getenv("GITHUB_TOKEN", "")
_REPO   = os.getenv("GITHUB_REPO",   "InnovaJeruth/rollos-wms")
_BRANCH = os.getenv("GITHUB_BRANCH", "main")
_BASE   = "https://api.github.com"


class GitHubError(Exception):
    pass


def _headers():
    if not _TOKEN:
        raise GitHubError("GITHUB_TOKEN no configurado en .env")
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# =========================================================================
# Lectura
# =========================================================================

def listar_archivos(carpeta):
    """
    Lista archivos en una carpeta del repo.
    Devuelve lista de dicts: {name, path, sha, download_url}.
    Devuelve [] si la carpeta no existe o está vacía.
    """
    url = f"{_BASE}/repos/{_REPO}/contents/{carpeta}"
    r = requests.get(url, headers=_headers(), params={"ref": _BRANCH})
    if r.status_code == 404:
        return []
    if not r.ok:
        raise GitHubError(f"listar_archivos({carpeta}): HTTP {r.status_code}\n{r.text[:300]}")
    return [
        {"name": f["name"], "path": f["path"], "sha": f["sha"],
         "download_url": f.get("download_url")}
        for f in r.json()
        if f["type"] == "file"
    ]


def descargar_json(path):
    """Descarga y parsea un JSON del repo. Devuelve el dict Python."""
    contenido_bytes, _ = descargar_bytes(path)
    return json.loads(contenido_bytes.decode("utf-8"))


def descargar_bytes(path):
    """
    Descarga el contenido raw de un archivo.
    Devuelve (bytes, sha).  Útil para .gz y para mover_archivo.
    """
    url = f"{_BASE}/repos/{_REPO}/contents/{path}"
    r = requests.get(url, headers=_headers(), params={"ref": _BRANCH})
    if not r.ok:
        raise GitHubError(f"descargar_bytes({path}): HTTP {r.status_code}\n{r.text[:300]}")
    data = r.json()
    return base64.b64decode(data["content"]), data["sha"]


def _obtener_sha(path):
    """SHA del archivo (requerido por GitHub para update y delete)."""
    url = f"{_BASE}/repos/{_REPO}/contents/{path}"
    r = requests.get(url, headers=_headers(), params={"ref": _BRANCH})
    if not r.ok:
        raise GitHubError(f"_obtener_sha({path}): HTTP {r.status_code}")
    return r.json()["sha"]


# =========================================================================
# Escritura
# =========================================================================

def subir_archivo(path, contenido, mensaje_commit, sha=None):
    """
    Crea o actualiza un archivo en el repo.
    contenido: str (se convierte a UTF-8) o bytes.
    sha: SHA del archivo si ya existe. Si se omite, se consulta automáticamente.
    """
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")

    if sha is None:
        try:
            sha = _obtener_sha(path)
        except GitHubError:
            sha = None  # archivo nuevo

    body = {
        "message": mensaje_commit,
        "content": base64.b64encode(contenido).decode("ascii"),
        "branch":  _BRANCH,
    }
    if sha:
        body["sha"] = sha

    r = requests.put(f"{_BASE}/repos/{_REPO}/contents/{path}",
                     headers=_headers(), json=body)
    if not r.ok:
        raise GitHubError(f"subir_archivo({path}): HTTP {r.status_code}\n{r.text[:300]}")
    return r.json()


def eliminar_archivo(path, sha=None, mensaje_commit=None):
    """Elimina un archivo del repo."""
    if sha is None:
        sha = _obtener_sha(path)
    body = {
        "message": mensaje_commit or f"bot: eliminar {path}",
        "sha":     sha,
        "branch":  _BRANCH,
    }
    r = requests.delete(f"{_BASE}/repos/{_REPO}/contents/{path}",
                        headers=_headers(), json=body)
    if not r.ok:
        raise GitHubError(f"eliminar_archivo({path}): HTTP {r.status_code}\n{r.text[:300]}")


def mover_archivo(path_origen, path_destino, mensaje_commit):
    """
    'Mueve' un archivo: crea en destino con el mismo contenido y elimina el origen.
    GitHub API no tiene rename nativo — se hace en 2 pasos.
    Si la creación en destino falla, el origen NO se borra (consistencia).
    """
    # Descargar contenido + sha del origen en un solo request
    url = f"{_BASE}/repos/{_REPO}/contents/{path_origen}"
    r = requests.get(url, headers=_headers(), params={"ref": _BRANCH})
    if not r.ok:
        raise GitHubError(f"mover_archivo(get {path_origen}): HTTP {r.status_code}")
    data       = r.json()
    contenido_b64 = data["content"].replace("\n", "")  # GitHub incluye saltos de línea
    sha_origen = data["sha"]

    # Crear en destino (primero, para no perder datos si falla)
    body_crear = {
        "message": mensaje_commit,
        "content": contenido_b64,
        "branch":  _BRANCH,
    }
    r2 = requests.put(f"{_BASE}/repos/{_REPO}/contents/{path_destino}",
                      headers=_headers(), json=body_crear)
    if not r2.ok:
        raise GitHubError(f"mover_archivo(put {path_destino}): HTTP {r2.status_code}\n{r2.text[:300]}")

    # Eliminar origen solo si la creación fue exitosa
    eliminar_archivo(path_origen, sha=sha_origen,
                     mensaje_commit=f"{mensaje_commit} — eliminar origen")


# =========================================================================
# Helpers de alto nivel para el bot WMS
# =========================================================================

def listar_pendientes():
    """Lista los JSONs ejecutables en pendientes/. Devuelve [{name, path, sha}]."""
    return [f for f in listar_archivos("pendientes") if f["name"].endswith(".json")]


def archivar_pendiente(path_pendiente, sha, carpeta_destino, motivo="procesado"):
    """
    Mueve un JSON de pendientes/ a procesados/ o discrepancias/.
    path_pendiente: ej. 'pendientes/movimientos_abc.json'
    sha: el sha que ya tenemos al descargar (evita un request extra)
    carpeta_destino: 'procesados' o 'discrepancias'
    """
    nombre = os.path.basename(path_pendiente)
    path_destino = f"{carpeta_destino}/{nombre}"
    mover_archivo(
        path_pendiente,
        path_destino,
        mensaje_commit=f"bot: {motivo} — {nombre}",
    )
    return path_destino
