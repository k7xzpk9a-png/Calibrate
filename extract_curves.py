#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extraction des courbes de performance du FM NH90 (Section IX) en SVGZ.

1. Parse la "LIST OF FIGURES" (pages PDF 108-133) -> catalogue
   (numero figure 9-N, titre, page logique 9-X).
2. Mapping page logique 9-X -> page PDF via le FOOTER reel (ligne 'ISS001M0301').
   /!\\ l'offset page PDF = page logique + cste N'EST PAS constant (pages inserees).
3. Genere un SVGZ vectoriel par figure (pdftocairo -svg, optimisation svgo,
   gzip), nomme proprement.
4. Ecrit catalog.json + catalog.js (consommes par l'outil de validation HTML).

Optimisation : par defaut on passe chaque SVG dans svgo (chemins relatifs,
fusion des groupes, arrondi des coordonnees) -> fichiers ~3x plus petits.
svgo est cherche dans $SVGO, puis le PATH, puis via `npx svgo`. Si introuvable,
on retombe sur l'arrondi maison (--precision) avec un avertissement.

Usage :
    python3 extract_curves.py [PDF]               # tout (parse + SVGZ, svgo)
    python3 extract_curves.py [PDF] --list-only   # juste le catalogue
    python3 extract_curves.py [PDF] --precision 3 # coords a 3 decimales
    python3 extract_curves.py [PDF] --no-svgo     # desactive svgo (arrondi maison)
    python3 extract_curves.py [PDF] --svg         # SVG non compresse (debug)

PDF par defaut : FM_-_TFRA-MR1_V3 ...pdf dans le dossier parent.
Mettre a jour le manuel = relancer avec le nouveau PDF en argument.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_PDF = ROOT / "FM_SWR2_V3.pdf"   # manuel courant (passer un autre en argument)

# Les plages de pages sont DETECTEES automatiquement (elles bougent d'un
# manuel/edition a l'autre) : on repere 'LIST OF FIGURES' et l'etendue de la liste.
LIST_HEADING = "LIST OF FIGURES"
FOOTER_TAG = "ISS001M0301"         # prefixe stable du pied de page (toutes editions NH90)
SCAN_LIMIT = 400                   # on cherche la liste dans les SCAN_LIMIT 1eres pages

SVG_DIR = HERE / "svg"
CATALOG = HERE / "catalog.json"

# Lignes d'en-tete / pied de page a ignorer dans la liste
SKIP_TOKENS = (
    "TTH-TFRA", "ISS001", "NATO UNCLASSIFIED", "Edition", "Rev 000",
    "FLIGHT MANUAL", "VOLUME 3", "Figure Title", "LIST OF FIGURES",
    "SECTION IX",
)
ROMAN_FOOTER = re.compile(r"^\s*9-[ivxlcdm]+\s*$", re.I)
ENTRY_RE = re.compile(r"^(9-\d+)\s+(.*)$")
PAGE_TAIL_RE = re.compile(r"(9-\d+)\s*$")
LEADER_RE = re.compile(r"(?:\s*[.…]\s*){2,}")   # dot leaders ".....", ". . . ."
# tout nombre decimal ou en notation scientifique (les entiers sont laisses tels quels)
NUM_RE = re.compile(r"-?\d+\.\d+(?:[eE][+-]?\d+)?|-?\d+[eE][+-]?\d+")


# ---------------------------------------------------------------- helpers texte
def clean(text: str) -> str:
    text = LEADER_RE.sub(" ", text).replace("…", " ")
    text = re.sub(r"\s*\.\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_skip(line: str) -> bool:
    return bool(ROMAN_FOOTER.match(line)) or any(t in line for t in SKIP_TOKENS)


def normalize_name(title: str) -> str:
    """Titre -> nom canonique : ASCII, MAJUSCULES, ponctuation -> espace.
    Ex: 'Hover in ground effect (ECS OFF, Engine AI OFF)'
        -> 'HOVER IN GROUND EFFECT ECS OFF ENGINE AI OFF'."""
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


# Regles de famille (ordre = priorite, 1er match gagne). Editable ensuite dans l'outil.
FAMILY_RULES = [
    ("weight_index", r"\bweight index\b"),                       # avant height_loss
    ("flyaway",      r"\bfly away\b|\bmaximum weight (at which|to)\b"),
    ("weight",       r"\bmaximum weight\b"),                     # HOGE/HIGE OEI -> weight
    ("hover",        r"\bhover (in|out)\b|\bh[io]ge\b"),
    ("height_loss",  r"\bheight loss\b"),
    ("roc",          r"\bclimb speed\b|\brate of climb\b|\bmaximum roc\b|\broc\b"),
    ("level_flight", r"\blevel flight\b"),
    ("hv",           r"height ?/ ?velocity"),
    ("cruise",       r"\b(tas|cruise|range|endurance)\b"),
    ("conversion",   r"airspeed system|density altitude|kilometers per|meters per "
                     r"second|liters|degrees celsius|fahrenheit"),
]


def classify_family(title: str) -> str:
    low = title.lower()
    for fam, pat in FAMILY_RULES:
        if re.search(pat, low):
            return fam
    return "other"


# --------------------------------------------------------- extraction de texte
def _pdftotext(pdf: Path, first: int, last: int, cache: Path) -> str:
    """Texte -layout des pages [first,last], cache invalide si le PDF change."""
    sig = _pdf_sig(pdf)
    sig_file = cache.with_suffix(cache.suffix + ".sig")
    if cache.exists() and sig_file.exists() and sig_file.read_text() == sig:
        return cache.read_text(encoding="utf-8", errors="replace")
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    cache.write_text(out, encoding="utf-8")
    sig_file.write_text(sig)
    return out


def _pdf_sig(pdf: Path) -> str:
    st = pdf.stat()
    return hashlib.md5(f"{pdf.resolve()}|{st.st_size}|{int(st.st_mtime)}"
                       .encode()).hexdigest()


def total_pages(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else SCAN_LIMIT


ENTRY_LINE = re.compile(r"^9-\d+\s+\S")   # ligne d'entree de la liste


def detect_ranges(pdf: Path):
    """Detecte automatiquement les pages PDF de la liste et du corps.
    Renvoie (ranges, list_pages_text) ; list_pages_text est reutilise par parse."""
    npages = total_pages(pdf)
    scan = _pdftotext(pdf, 1, min(SCAN_LIMIT, npages), HERE / "_scan_raw.txt").split("\f")
    # La 'LIST OF FIGURES' de la section IX = la page qui porte le titre ET
    # contient des entrees '9-N' (le doc a plusieurs LIST OF FIGURES par section).
    list_first = None
    for i, p in enumerate(scan):
        if LIST_HEADING in p and sum(1 for l in p.splitlines() if ENTRY_LINE.match(l)) >= 4:
            list_first = i + 1            # pdftotext demarre a la page 1
            break
    if list_first is None:
        sys.exit(f"'{LIST_HEADING}' (section IX, entrees 9-N) introuvable dans "
                 f"les {len(scan)} 1eres pages.")
    # etendue : tant que la page ressemble a la liste (>=4 lignes d'entree)
    list_last = list_first
    for i in range(list_first - 1, len(scan)):
        n = sum(1 for l in scan[i].splitlines() if ENTRY_LINE.match(l))
        if n >= 4:
            list_last = i + 1
        elif i + 1 > list_first:
            break
    ranges = {"list_first": list_first, "list_last": list_last,
              "body_first": list_last + 1, "body_last": npages}
    return ranges, scan[list_first - 1: list_last]


def build_footer_map(pdf: Path, ranges: dict) -> dict:
    """page logique '9-X' -> numero de page PDF, via le footer reel.

    Scan PAGE PAR PAGE en -layout : un pdftotext groupe sur tout le corps
    fusionne les pages PAYSAGE (les figures) et fausse l'alignement des \\f.
    Resultat mis en cache (cle = signature du PDF)."""
    cache = HERE / "_footermap.json"
    sig_file = HERE / "_footermap.sig"
    sig = _pdf_sig(pdf)
    if cache.exists() and sig_file.exists() and sig_file.read_text() == sig:
        return json.loads(cache.read_text(encoding="utf-8"))

    bf, bl = ranges["body_first"], ranges["body_last"]
    foot = re.compile(r"9-(\d+)")
    log2pdf = {}
    print(f"  footer-map : scan pages {bf}-{bl}...", flush=True)
    for pg in range(bf, bl + 1):
        txt = subprocess.run(
            ["pdftotext", "-layout", "-f", str(pg), "-l", str(pg), str(pdf), "-"],
            capture_output=True, text=True,
        ).stdout
        fl = [l for l in txt.splitlines() if FOOTER_TAG in l]
        if not fl:
            continue
        nums = foot.findall(fl[-1])
        if nums:
            log2pdf.setdefault("9-" + nums[-1], pg)
    cache.write_text(json.dumps(log2pdf), encoding="utf-8")
    sig_file.write_text(sig)
    return log2pdf


def parse_catalog(pdf: Path, ranges: dict, list_pages: list) -> list:
    entries, cur = [], None
    for line in "\f".join(list_pages).splitlines():
        line = line.replace("\f", "")
        if not line.strip():
            continue
        m = ENTRY_RE.match(line)
        if m:
            if cur:
                entries.append(cur)
            num, rest = m.group(1), m.group(2)
            pm = PAGE_TAIL_RE.search(rest)
            logical = pm.group(1) if pm else None
            if pm:
                rest = rest[: pm.start()]
            cur = {"num": num, "title": clean(rest), "logical_page": logical}
        else:
            if cur is None or is_skip(line) or not line.startswith((" ", "\t")):
                continue
            extra = clean(line)
            if extra:
                cur["title"] = (cur["title"] + " " + extra).strip()
    if cur:
        entries.append(cur)

    ext = ".svg" if KEEP_SVG else ".svgz"
    log2pdf = build_footer_map(pdf, ranges)
    for e in entries:
        e["pdf_page"] = log2pdf.get(e["logical_page"])
        e["file"] = e["num"] + ext          # fichiers nommes par n° de figure seul
        e["name"] = normalize_name(e["title"])
        e["family"] = classify_family(e["title"])
        e["validated"] = False
    return entries


def build_lookup(entries: list) -> dict:
    """Table de correspondance : index (nom normalise -> n°) + figs (n° -> infos)."""
    lookup = {
        "version": 1,
        "normalise": "strip-prefix + spaces→_ + uppercase + drop-ext",
        "index": {},
        "figs": {},
    }
    for e in entries:
        lookup["figs"][e["num"]] = {"family": e["family"], "name": e["name"]}
        key = e["name"].replace(" ", "_")
        k, i = key, 2
        while k in lookup["index"]:      # titres identiques -> suffixe _2, _3...
            k, i = f"{key}_{i}", i + 1
        lookup["index"][k] = e["num"]
    return lookup


# ------------------------------------------------------------ extraction SVG(Z)
def find_svgo() -> list | None:
    """Localise un executable svgo. Renvoie la commande (liste) ou None.
    Ordre : $SVGO, svgo dans le PATH, puis `npx svgo` (si npx est dispo)."""
    env = os.environ.get("SVGO")
    if env:
        return [env]
    local = HERE / "node_modules" / ".bin" / "svgo"   # svgo installe dans ce dossier
    if local.exists():
        return [str(local)]
    exe = shutil.which("svgo")
    if exe:
        return [exe]
    npx = shutil.which("npx")
    if npx:
        # --no-install : on n'autorise pas npx a telecharger silencieusement
        cmd = [npx, "--no-install", "svgo"]
        probe = subprocess.run(cmd + ["--version"], capture_output=True, text=True)
        if probe.returncode == 0:
            return cmd
    return None


SVGO_CONFIG = HERE / "svgo.config.mjs"   # garde 1 courbe = 1 <path> (mergePaths off)


def run_svgo(svgo_cmd: list, svg_path: Path, precision: int) -> str:
    """Optimise svg_path via svgo, renvoie le SVG optimise (stdout).
    Utilise svgo.config.mjs s'il existe (chemins non fusionnes pour tag-curves)."""
    cmd = svgo_cmd + ["-i", str(svg_path), "-o", "-",
                      "--multipass", "--precision", str(precision)]
    if SVGO_CONFIG.exists():
        cmd += ["--config", str(SVGO_CONFIG)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not res.stdout.strip():
        raise RuntimeError(res.stderr.strip() or "svgo a renvoye un SVG vide")
    return res.stdout


def optimize(svg: str, precision: int) -> str:
    """Reduit la precision des coordonnees a `precision` chiffres significatifs.
    Le prologue <?xml ... ?> est preserve (sinon version='1.0' -> '1' casse le XML)."""
    fmt = "%." + str(precision) + "g"
    sub = lambda m: fmt % float(m.group())
    head = re.match(r"^\s*<\?xml.*?\?>", svg, re.S)
    if head:
        return svg[: head.end()] + NUM_RE.sub(sub, svg[head.end():])
    return NUM_RE.sub(sub, svg)


def extract_svgs(entries: list, pdf: Path, precision: int, use_svgo: bool):
    SVG_DIR.mkdir(exist_ok=True)
    # nettoie les anciens fichiers derives pour repartir propre
    for old in SVG_DIR.glob("*.svg*"):
        old.unlink()

    svgo_cmd = find_svgo() if use_svgo else None
    if use_svgo and svgo_cmd is None:
        print("  !! svgo introuvable ($SVGO / PATH / npx) -> arrondi maison "
              "(installez svgo pour des fichiers ~3x plus petits)")
    elif svgo_cmd:
        print(f"  optimisation svgo : {' '.join(svgo_cmd)}")
    svgo_failed = False   # on ne spamme pas l'avertissement par figure

    total = len(entries)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "p.svg"
        for i, e in enumerate(entries, 1):
            if not e["pdf_page"]:
                print(f"  !! {e['num']} sans page logique -> ignore")
                continue
            subprocess.run(
                ["pdftocairo", "-svg", "-f", str(e["pdf_page"]),
                 "-l", str(e["pdf_page"]), str(pdf), str(tmp)],
                check=True, capture_output=True,
            )
            svg = None
            if svgo_cmd:
                try:
                    svg = run_svgo(svgo_cmd, tmp, precision)
                except Exception as exc:        # svgo cale sur cette figure
                    if not svgo_failed:
                        print(f"  !! svgo a echoue sur {e['num']} ({exc}) "
                              f"-> arrondi maison pour les figures concernees")
                        svgo_failed = True
            if svg is None:
                svg = optimize(tmp.read_text(encoding="utf-8"), precision)
            data = svg.encode("utf-8")
            out = SVG_DIR / e["file"]
            if KEEP_SVG:
                out.write_bytes(data)
            else:
                out.write_bytes(gzip.compress(data, 9))
            if i % 50 == 0 or i == total:
                print(f"  {i}/{total}  ({e['num']})  {len(out.read_bytes())//1024} Ko")


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Extraction des courbes de perf NH90")
    ap.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF),
                    help="PDF du manuel a extraire (defaut : V3)")
    ap.add_argument("--list-only", action="store_true",
                    help="genere seulement le catalogue (pas les SVG)")
    ap.add_argument("--precision", type=int, default=2,
                    help="decimales des coordonnees (svgo) / chiffres signif. "
                         "(arrondi maison) ; defaut 2")
    ap.add_argument("--no-svgo", dest="svgo", action="store_false",
                    help="desactive svgo (arrondi maison seulement)")
    ap.add_argument("--svg", action="store_true",
                    help="sortir du SVG non compresse au lieu de SVGZ")
    args = ap.parse_args()

    global KEEP_SVG
    KEEP_SVG = args.svg
    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        sys.exit(f"PDF introuvable : {pdf}")
    print("PDF source :", pdf.name)

    ranges, list_pages = detect_ranges(pdf)
    print(f"Detection : LIST OF FIGURES = pages PDF {ranges['list_first']}-"
          f"{ranges['list_last']} | corps = {ranges['body_first']}-{ranges['body_last']}")

    entries = parse_catalog(pdf, ranges, list_pages)
    print(f"Figures parsees : {len(entries)}")
    if not entries:
        sys.exit("Aucune figure trouvee dans la liste detectee. "
                 "Verifiez que la section commence bien par 'LIST OF FIGURES'.")
    print("  1ere :", entries[0]["num"], "-", entries[0]["title"],
          "-> PDF", entries[0]["pdf_page"])
    print("  der. :", entries[-1]["num"], "-> PDF", entries[-1]["pdf_page"])
    missing = [e["num"] for e in entries if not e["pdf_page"]]
    if missing:
        print("  sans page :", missing)

    CATALOG.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    (HERE / "catalog.js").write_text(
        "window.CATALOG = " + json.dumps(entries, ensure_ascii=False) + ";",
        encoding="utf-8")
    lookup = build_lookup(entries)
    (HERE / "lookup.json").write_text(
        json.dumps(lookup, ensure_ascii=False, indent=2), encoding="utf-8")
    fams = {}
    for f in lookup["figs"].values():
        fams[f["family"]] = fams.get(f["family"], 0) + 1
    print("Catalogue -> catalog.json (+ catalog.js) | lookup.json")
    print("Familles :", ", ".join(f"{k}={v}" for k, v in sorted(fams.items())))

    if not args.list_only:
        fmt = "SVG" if KEEP_SVG else "SVGZ"
        print(f"Extraction {fmt} (precision {args.precision}, "
              f"svgo {'on' if args.svgo else 'off'})...")
        extract_svgs(entries, pdf, args.precision, args.svgo)
        tot = sum(f.stat().st_size for f in SVG_DIR.glob("*.svg*"))
        print(f"Termine. {len(list(SVG_DIR.glob('*.svg*')))} fichiers, "
              f"{tot/1e6:.0f} Mo total.")


KEEP_SVG = False

if __name__ == "__main__":
    main()
