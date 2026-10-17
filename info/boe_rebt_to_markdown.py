#!/usr/bin/env python3
"""
Descarga el Reglamento electrotécnico para baja tensión e ITC (BOE-A-2002-18099)
desde la API de datos abiertos del BOE (legislación consolidada) y lo convierte a:

  <salida>/
    md/00_reglamento.md        texto del Reglamento y disposiciones (antes de las ITC)
    md/ITC-BT-19.md            un archivo por ITC (agrupación heurística)
    md/zz_*.md                 bloques editoriales posteriores a las ITC (p. ej. "[Información relacionada]")
    tablas/ITC-BT-19_t01.csv   cada tabla en CSV (y también incrustada en el .md)
    indice.json                bloques, títulos, fechas de vigencia, archivos generados
    cache/                     XML original descargado (para no repetir peticiones)

Detalles de conversión:
  - Se exporta la versión vigente a hoy (nunca una reforma futura anunciada).
  - Apartados numerados cortos ("1. Objeto", "1.1 Generalidades") se emiten como
    encabezados (heurística: <= 90 caracteres y sin puntuación final).
  - Las imágenes (fórmulas) se conservan como enlaces absolutos ![imagen](...).
  - La caché solo guarda y reutiliza respuestas XML válidas.

Uso:
    python boe_rebt_to_markdown.py                 # descarga y convierte
    python boe_rebt_to_markdown.py --out rebt      # carpeta de salida
    python boe_rebt_to_markdown.py --no-group      # un .md por bloque, sin agrupar por ITC
    python boe_rebt_to_markdown.py --debug         # imprime respuestas crudas si algo falla

Solo usa la librería estándar (Python 3.9+).
API: https://www.boe.es/datosabiertos/api/api.php
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id"
BOE_WEB = "https://www.boe.es"
NORMA_ID = "BOE-A-2002-18099"  # Real Decreto 842/2002 (REBT) consolidado
UA = "rebt-to-markdown/1.0 (uso personal; contacto: ver correo del usuario)"

ITC_RE = re.compile(
    r"^(?:INSTRUCCI[ÓO]N\s+T[ÉE]CNICA\s+COMPLEMENTARIA\s+)?ITC[-\s]*BT[-\s]*0?(\d{1,2})\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- red
def is_valid_xml(data: bytes) -> bool:
    try:
        ET.fromstring(data)
        return True
    except ET.ParseError:
        return False


def fetch(url: str, cache_file: Path, debug: bool = False, retries: int = 3) -> bytes:
    """GET con caché en disco. Pide XML (la API devuelve 400/406 sin cabecera Accept).

    La caché solo se lee y se escribe si el contenido es XML parseable: una
    respuesta corrupta (corte, página de error con 200) no debe envenenarla."""
    if cache_file.exists() and cache_file.stat().st_size > 0:
        data = cache_file.read_bytes()
        if is_valid_xml(data):
            return data
        cache_file.unlink()
        if debug:
            print(f"[debug] caché corrupta, se re-descarga: {cache_file}", file=sys.stderr)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/xml", "User-Agent": UA}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if not is_valid_xml(data):
                raise ValueError(f"respuesta no XML ({len(data)} bytes)")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)
            time.sleep(0.4)  # cortesía con el servidor
            return data
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_err = e
            if debug:
                print(f"[debug] intento {attempt} fallido para {url}: {e}", file=sys.stderr)
            time.sleep(1.5 * attempt)
    raise SystemExit(f"No se pudo descargar {url}\n  último error: {last_err}")


# ----------------------------------------------------------------- utilidades XML
def strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def inline_text(el: ET.Element) -> str:
    """Texto de un elemento conservando sup/sub de forma legible."""
    parts: list[str] = []

    def walk(node: ET.Element):
        if node.text:
            parts.append(node.text)
        for ch in node:
            tag = ch.tag.lower() if isinstance(ch.tag, str) else ""
            if tag == "sup":
                parts.append("^" + "".join(ch.itertext()))
            elif tag == "sub":
                parts.append("_" + "".join(ch.itertext()))
            elif tag == "br":
                parts.append(" ")
            elif tag == "img":
                src = ch.get("src", "")
                if src:
                    alt = ch.get("alt") or "imagen"
                    parts.append(f"![{alt}]({urllib.parse.urljoin(BOE_WEB, src)})")
            else:
                walk(ch)
            if ch.tail:
                parts.append(ch.tail)

    walk(el)
    return re.sub(r"[ \t\u00a0]+", " ", "".join(parts)).strip()


def slugify(s: str, maxlen: int = 60) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen].rstrip("-")) or "bloque"


# ------------------------------------------------------------------------ tablas
def table_to_grid(table: ET.Element) -> list[list[str]]:
    """Expande colspan/rowspan a una rejilla rectangular de strings."""
    rows = [tr for tr in table.iter() if isinstance(tr.tag, str) and tr.tag.lower() == "tr"]
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}  # (fila, col) -> texto por rowspan
    for r, tr in enumerate(rows):
        row: list[str] = []
        c = 0
        cells = [td for td in tr if isinstance(td.tag, str) and td.tag.lower() in ("td", "th")]
        for td in cells:
            while (r, c) in pending:
                row.append(pending.pop((r, c)))
                c += 1
            text = inline_text(td)
            try:
                cs = max(1, int(td.get("colspan", "1")))
                rs = max(1, int(td.get("rowspan", "1")))
            except ValueError:
                cs = rs = 1
            for k in range(cs):
                row.append(text if k == 0 else "")
                for extra in range(1, rs):
                    pending[(r + extra, c + k)] = text if k == 0 else ""
            c += cs
        while (r, c) in pending:
            row.append(pending.pop((r, c)))
            c += 1
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]


def grid_to_markdown(grid: list[list[str]]) -> str:
    if not grid or not grid[0]:
        return ""
    esc = lambda s: s.replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(esc(c) for c in grid[0]) + " |",
             "|" + "|".join("---" for _ in grid[0]) + "|"]
    for row in grid[1:]:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------------- un bloque
def pick_latest_version(bloque: ET.Element, hoy: str | None = None) -> ET.Element:
    """Versión vigente a `hoy` (AAAAMMDD; por defecto la fecha actual).

    Nunca devuelve una reforma futura anunciada; si todas las versiones son
    futuras (bloque aún no en vigor), devuelve la más temprana."""
    versions = [v for v in bloque if isinstance(v.tag, str) and v.tag == "version"]
    if not versions:
        return bloque
    clave = lambda v: v.get("fecha_vigencia") or v.get("fecha_publicacion") or ""
    hoy = hoy or time.strftime("%Y%m%d")
    vigentes = [v for v in versions if clave(v) <= hoy]
    if vigentes:
        return max(vigentes, key=clave)
    return min(versions, key=clave)


def heading_level(cls: str) -> int:
    c = (cls or "").lower()
    if c.startswith("libro"):
        return 2
    if c.startswith("titulo") or c == "anexo" or c.startswith("anexo"):
        return 2
    if c.startswith("capitulo"):
        return 3
    if c.startswith("seccion") or c.startswith("subseccion"):
        return 4
    if c.startswith("articulo"):
        return 4
    return 0


APARTADO_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


def numbered_heading_level(txt: str) -> int:
    """'1. Objeto' -> 3, '1.1 Generalidades' -> 4; 0 si no parece encabezado.

    Heurística conservadora para las ITC (sus <p> llegan con clase
    'parrafo'/'parrafo_2', sin nivel): párrafo corto y sin puntuación final,
    porque los encabezados del BOE no terminan en punto; así las
    enumeraciones del cuerpo no se promocionan por error."""
    if len(txt) > 90 or txt.rstrip().endswith((".", ";", ",", ":")):
        return 0
    m = APARTADO_RE.match(txt)
    if not m:
        return 0
    partes = m.group(1).split(".")
    if any(int(p) > 99 or (len(p) > 1 and p.startswith("0")) for p in partes):
        return 0  # miles ("16.000") o numeración rara: no es encabezado
    return min(6, 2 + len(partes))


def group_for_block(titulo: str, current: str, itc_started: bool) -> tuple[str, bool]:
    """Grupo de salida para el bloque y si ya arrancaron las ITC.

    Todo lo anterior a la primera ITC se acumula en 00_reglamento; un bloque
    posterior a las ITC que no es ITC (p. ej. '[Información relacionada]')
    va a un archivo propio zz_* en lugar de colarse en la última ITC."""
    m = ITC_RE.match(titulo)
    if m:
        return f"ITC-BT-{int(m.group(1)):02d}", True
    if itc_started:
        return f"zz_{slugify(titulo)}", True
    return current, itc_started


def block_to_items(bloque: ET.Element):
    """Devuelve [('p', clase, texto) | ('table', grid)] de la versión vigente."""
    ver = pick_latest_version(bloque)
    items = []
    for el in ver:
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag == "p":
            txt = inline_text(el)
            if txt:
                items.append(("p", el.get("class", ""), txt))
        elif tag == "table":
            grid = table_to_grid(el)
            if grid:
                items.append(("table", grid))
        elif tag in ("blockquote", "div"):
            for sub in el.iter():
                if isinstance(sub.tag, str) and sub.tag.lower() == "p":
                    txt = inline_text(sub)
                    if txt:
                        items.append(("p", sub.get("class", ""), txt))
                elif isinstance(sub.tag, str) and sub.tag.lower() == "table":
                    items.append(("table", table_to_grid(sub)))
    return ver, items


# ---------------------------------------------------------------------- principal
def parse_indice(xml_bytes: bytes, debug: bool):
    root = strip_ns(ET.fromstring(xml_bytes))
    code = root.findtext(".//status/code")
    if code and code != "200":
        raise SystemExit(f"La API devolvió estado {code}: {root.findtext('.//status/text')}")
    blocks = []
    for b in root.iter("bloque"):
        bid = (b.findtext("id") or b.get("id") or "").strip()
        if not bid:
            continue
        blocks.append({
            "id": bid,
            "titulo": (b.findtext("titulo") or b.get("titulo") or "").strip(),
            "fecha_actualizacion": (b.findtext("fecha_actualizacion") or "").strip(),
        })
    if debug or not blocks:
        print(f"[debug] {len(blocks)} bloques en el índice", file=sys.stderr)
    if not blocks:
        raise SystemExit("El índice no contiene bloques. Ejecuta con --debug y revisa cache/indice.xml")
    return blocks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="rebt_salida", help="carpeta de salida")
    ap.add_argument("--id", default=NORMA_ID, help="identificador BOE de la norma consolidada")
    ap.add_argument("--no-group", action="store_true", help="un .md por bloque (sin agrupar por ITC)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    cache = out / "cache"
    md_dir, tab_dir = out / "md", out / "tablas"
    for d in (cache, md_dir, tab_dir):
        d.mkdir(parents=True, exist_ok=True)

    base = f"{BASE}/{args.id}/texto"
    indice = parse_indice(fetch(f"{base}/indice", cache / "indice.xml", args.debug), args.debug)

    # grupos: nombre -> lista de líneas markdown
    groups: dict[str, list[str]] = {"00_reglamento": []}
    current = "00_reglamento"
    itc_started = False
    meta_blocks = []
    table_count: dict[str, int] = {}

    for n, blk in enumerate(indice, 1):
        raw = fetch(f"{base}/bloque/{blk['id']}", cache / f"bloque_{blk['id']}.xml", args.debug)
        root = strip_ns(ET.fromstring(raw))
        bloque = next(root.iter("bloque"), None)
        if bloque is None:
            print(f"[aviso] bloque {blk['id']} sin contenido, se omite", file=sys.stderr)
            continue
        ver, items = block_to_items(bloque)
        vigencia = ver.get("fecha_vigencia", "") if ver is not bloque else ""
        titulo = blk["titulo"] or bloque.get("titulo", "")

        if args.no_group:
            current = f"{n:03d}_{slugify(titulo or blk['id'])}"
            groups.setdefault(current, [])
        else:
            current, itc_started = group_for_block(titulo or blk["id"], current, itc_started)
            groups.setdefault(current, [])

        lines = groups[current]
        first_p = next((it[2] for it in items if it[0] == "p"), "")
        norm = lambda s: re.sub(r"\W+", "", s).lower()
        repeated = bool(first_p) and norm(first_p)[:25] == norm(titulo)[:25]
        if titulo and not repeated:
            lines.append(f"\n## {titulo}\n")

        for it in items:
            if it[0] == "p":
                _, cls, txt = it
                # ¿una ITC empieza dentro de un bloque? (párrafo corto tipo título)
                m = ITC_RE.match(txt)
                if not args.no_group and m and len(txt) <= 160 and not txt.rstrip().endswith("."):
                    current = f"ITC-BT-{int(m.group(1)):02d}"
                    itc_started = True
                    groups.setdefault(current, [])
                    lines = groups[current]
                    lines.append(f"\n## {txt}\n")
                    continue
                lvl = heading_level(cls) or numbered_heading_level(txt)
                lines.append(("#" * lvl + " " + txt + "\n") if lvl else (txt + "\n"))
            else:
                grid = it[1]
                table_count[current] = table_count.get(current, 0) + 1
                tname = f"{current}_t{table_count[current]:02d}"
                with open(tab_dir / f"{tname}.csv", "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(grid)
                lines.append(f"\n<!-- tabla: tablas/{tname}.csv -->\n{grid_to_markdown(grid)}\n")

        meta_blocks.append({"n": n, "id": blk["id"], "titulo": titulo,
                            "vigencia": vigencia, "grupo": current})

    files = {}
    for name, lines in groups.items():
        body = "\n".join(lines).strip()
        if not body:
            continue
        header = (f"---\nnorma: {args.id}\ngrupo: {name}\n"
                  f"fuente: https://www.boe.es/buscar/act.php?id={args.id}\n---\n\n")
        p = md_dir / f"{name}.md"
        p.write_text(header + body + "\n", encoding="utf-8")
        files[name] = str(p.relative_to(out))

    (out / "indice.json").write_text(
        json.dumps({"norma": args.id, "bloques": meta_blocks, "archivos": files,
                    "tablas": sum(table_count.values())}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"Hecho: {len(files)} archivos .md en {md_dir}, {sum(table_count.values())} tablas CSV en {tab_dir}")
    print("Revisa indice.json y comprueba a mano las tablas críticas contra el original.")


if __name__ == "__main__":
    main()
