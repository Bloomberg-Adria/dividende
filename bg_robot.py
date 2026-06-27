# -*- coding: utf-8 -*-
# ───────────────────────────────────────────────────────────────
#  BEOGRAD — ROBOT (Faza 1):  crawler + OCR citac.
#  Za svaku BELEX15 firmu: prodji dokumente -> preskoci velike ->
#  skini sitne -> OCR (cirilica) -> nadji dividendu -> izvuci iznos
#  i datum -> zapisi u dividende_bg.json.
#
#  Pokreces:   python bg_robot.py          (samo DNOS — za test)
#              python bg_robot.py SVE       (svih 9 firmi)
#              python bg_robot.py MTLC      (jedna druga firma)
# ───────────────────────────────────────────────────────────────
import urllib.request, re, sys, json, time, datetime, html as _html

try:
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError as e:
    print("Nedostaje paket:", e, "\nPokreni:  pip install pytesseract pdf2image"); sys.exit()

# ---------- postavke ----------
import os, glob
# Tesseract: na Windowsu fiksna putanja; na Linuxu/GitHubu je na PATH-u.
_tess_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(_tess_win):
    pytesseract.pytesseract.tesseract_cmd = _tess_win

# Poppler: na Windowsu trazi C:\poppler; na Linuxu ostaje None (sistemski).
POPPLER = None
for k in glob.glob(r"C:\poppler\**\bin", recursive=True):
    if os.path.exists(os.path.join(k, "pdftoppm.exe")):
        POPPLER = k
        break

PRAG_MB = 2.0       # PDF veci od ovoga = izvjestaj -> preskoci (ne skidaj)
MAX_STRANICA = 6    # OCR-aj samo prvih N stranica
TTM_DANA = 450      # zadrzi dividende novije od ovoliko dana (~15 mj).
                    # Za striktni TTM stavi 365 (ali tada godisnje dividende
                    # mogu nakratko "nestati" izmedju isplate i nove najave).

# Srbi koriste oba pisma: citamo cirilicu (srp) I latinicu (srp_latn) zajedno.
try:
    _dostupni = set(pytesseract.get_languages(config=""))
except Exception:
    _dostupni = {"srp"}
_dijelovi = [l for l in ("srp", "srp_latn") if l in _dostupni] or ["srp"]
LANG = "+".join(_dijelovi)
if "srp_latn" not in _dostupni:
    print("UPOZORENJE: nema jezika 'srp_latn' (srpska latinica).")
    print("  Latinicni dokumenti se mozda nece dobro procitati.")
    print("  Dodaj ga: skini 'srp_latn.traineddata' i stavi u")
    print("  C:\\Program Files\\Tesseract-OCR\\tessdata\\  (pa ponovi).")
print("OCR jezici:", LANG)

# BELEX15 sastav (zadnja revizija 31.03.2026.) — naziv, tezina u indeksu
BELEX15 = [
    ("AERO", "Aerodrom Nikola Tesla", "20,00%"),
    ("DNOS", "Dunav osiguranje",      "20,00%"),
    ("NIIS", "NIS",                   "20,00%"),
    ("TGAS", "Messer Tehnogas",       "17,22%"),
    ("MTLC", "Metalac",               "10,93%"),
    ("IMPL", "Impol Seval",           "3,57%"),
    ("JESV", "Jedinstvo",             "3,26%"),
    ("FINT", "Fintel energija",       "2,99%"),
    ("ENHL", "Energoprojekt holding", "2,03%"),
]

# ---------- mreza ----------
def dohvati(url):
    z = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(z, timeout=60) as o:
        return o.read()

def dohvati_tekst(url):
    return dohvati(url).decode("utf-8", errors="ignore")

# ---------- lista dokumenata jedne firme ----------
def velicina_u_mb(opis):
    m = re.search(r'([\d.,]+)\s*(kb|mb|gb)', opis, re.I)
    if not m: return None
    broj = float(m.group(1).replace(",", "."))
    j = m.group(2).lower()
    return broj/1024 if j == "kb" else (broj if j == "mb" else broj*1024)

def ocisti(s):
    return _html.unescape(re.sub(r"<[^>]+>", " ", s)).strip(" .\t\n")

def dokumenti(symbol, godina=None):
    url = f"https://bgdx.rs/trgovanje/vesti/hartija/{symbol}"
    if godina: url += f"/{godina}"
    h = dohvati_tekst(url)
    out = []
    for a in re.finditer(r"""<a\b[^>]*?href=['"]([^'"]*?/data/\d{4}/\d{2}/\d+\.pdf)['"][^>]*>""", h, re.I):
        link = a.group(1)
        if link.startswith("/"): link = "https://bgdx.rs" + link
        tm = re.search(r"""title=['"]([^'"]*)['"]""", a.group(0))
        mb = velicina_u_mb(tm.group(1) if tm else "")
        prije = h[:a.start()]
        dts = re.findall(r'(\d{2}\.\d{2}\.\d{4})', prije)
        datum = dts[-1] if dts else None
        naslov = ""
        if datum:
            naslov = ocisti(h[prije.rfind(datum)+len(datum):a.start()])[:90]
        out.append({"datum": datum, "naslov": naslov, "url": link, "mb": mb})
    return out

# ---------- OCR + vadjenje (citac) ----------
def ocr_bytes(pdf_bytes):
    slike = convert_from_bytes(pdf_bytes, dpi=300, first_page=1,
                               last_page=MAX_STRANICA, poppler_path=POPPLER)
    return "\n".join(pytesseract.image_to_string(s, lang=LANG) for s in slike)

MJESECI = {  # cirilica
    "јануар":1,"фебруар":2,"март":3,"април":4,"мај":5,"јун":6,
    "јул":7,"август":8,"септембар":9,"октобар":10,"новембар":11,"децембар":12,
    # latinica
    "januar":1,"februar":2,"mart":3,"april":4,"maj":5,"jun":6,
    "jul":7,"avgust":8,"septembar":9,"oktobar":10,"novembar":11,"decembar":12}

def srpski_datum(s):
    m = re.search(r'(\d{1,2})\.\s*([A-Za-zА-Яа-яЁёЂђЈјЉљЊњЋћЏџČčĆćŠšŽžĐđ]+)\s+(\d{4})', s)
    if not m: return None
    dan, mjr, god = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    for kor, broj in MJESECI.items():
        if mjr.startswith(kor[:4]):
            return f"{god:04d}-{broj:02d}-{dan:02d}"
    return None

def num_iso(s):  # "10.06.2025" -> "2025-06-10"
    d, m, g = s.split(".")[:3]
    return f"{int(g):04d}-{int(m):02d}-{int(d):02d}"

def izvuci_iznos(tekst):
    """BRUTO iznos po akciji/deonici. Ignorira neto iznose iz rasclambi;
    podnosi 'dinara'/'RSD', umetnute rijeci ('bruto', 'jednoj') i oba pisma."""
    pat = re.compile(
        r'(\d{1,3}(?:\.\d{3})*,\d+)\s*(?:dinara|динара|rsd|рсд)\b[^\n)]{0,15}?'
        r'(?:po|по)\s+(?:\w+\s+)?(?:akcij|акциј|deonic|деониц)', re.IGNORECASE)
    najbolji = None
    for m in pat.finditer(tekst):
        prije = tekst[max(0, m.start()-35):m.start()].lower()
        oko   = tekst[max(0, m.start()-45):m.end()+10].lower()
        if "нето" in prije or "neto" in prije:
            continue                         # neto -> preskoci
        ima_bruto = ("бруто" in oko or "bruto" in oko)
        if najbolji is None or (ima_bruto and not najbolji[1]):
            najbolji = (m.group(1), ima_bruto)
    return najbolji[0] if najbolji else None

def izvuci_datum_prava(tekst):
    """Dan dividende / dan akcionara (numericki ili s imenom mjeseca)."""
    for pat in (r'(?:дан дивиденде|dan dividende|дан акционара|dan akcionara)[^0-9]{0,45}(\d{1,2}\.\d{1,2}\.\d{4})',
                r'(\d{1,2}\.\d{1,2}\.\d{4})[^0-9]{0,30}(?:дан дивиденде|dan dividende|дан акционара|dan akcionara)'):
        m = re.search(pat, tekst, re.I)
        if m: return num_iso(m.group(1))
    m = re.search(r'(?:на дан|na dan)\s+(\d{1,2}\.\s*[^\s,]+\s+\d{4})', tekst, re.I)
    return srpski_datum(m.group(1)) if m else None

def analiziraj(tekst):
    t = tekst.lower()
    if "дивиденд" not in t and "dividend" not in t:
        return None
    iznos = izvuci_iznos(tekst)
    datum_prava = izvuci_datum_prava(tekst)
    if iznos:
        status = "odluka"
    elif any(k in t for k in ("сазив","saziv","предлог","predlog","тачка","tačka","дневни ред","dnevni red")):
        status = "najava (provjeri)"
    else:
        status = "spominje (provjeri)"
    return {"iznos": iznos, "datum_prava": datum_prava, "status": status}

# ---------- obrada jedne firme ----------
def obradi_firmu(ticker, naziv):
    print(f"\n=== {ticker} ({naziv}) ===")
    try:
        docs = dokumenti(ticker)
    except Exception as e:
        print("  greska kod liste dokumenata:", e); return []
    nalazi = []
    for d in docs:
        if d["mb"] is not None and d["mb"] > PRAG_MB:
            continue  # velik izvjestaj -> preskoci
        try:
            pdf = dohvati(d["url"])
            tekst = ocr_bytes(pdf)
        except Exception as e:
            print("  greska:", d["url"], e); continue
        n = analiziraj(tekst)
        if not n:
            continue
        print(f"  • {d['datum']}  {n['status']:18}  iznos={n['iznos'] or '-'}  {d['naslov'][:45]}")
        nalazi.append({
            "ticker": ticker, "company": naziv,
            "gross": n["iznos"], "record_date": n["datum_prava"],
            "pub_date": d["datum"], "status": n["status"],
            "title": d["naslov"], "url": d["url"],
        })
        time.sleep(0.4)  # pristojnost prema serveru
    return nalazi

# ---------- dedup ----------
def datum_key(s):
    # "30.04.2025" -> sortabilno
    try:
        d, m, g = s.split("."); return f"{g}{m}{d}"
    except Exception:
        return "00000000"

def procisti(sve):
    """Jedna stavka po firmi: najnovija dividenda (s iznosom ako postoji)."""
    po_firmi = {}
    for n in sve:
        po_firmi.setdefault(n["ticker"], []).append(n)
    konacno = []
    for ticker, lista in po_firmi.items():
        s_iznosom = [n for n in lista if n["gross"]]
        izbor = s_iznosom or lista
        konacno.append(max(izbor, key=lambda n: datum_key(n["pub_date"])))
    return konacno

# ---------- glavni dio ----------
arg = sys.argv[1] if len(sys.argv) > 1 else "DNOS"
if arg == "SVE":
    firme = BELEX15
else:
    firme = [f for f in BELEX15 if f[0] == arg] or [(arg, arg, "")]

sastav = [{"ticker": t, "company": n, "weight": w} for t, n, w in BELEX15]

print("BEOGRAD robot (Faza 1) — krecem...")
sve = []
for t, n, w in firme:
    sve += obradi_firmu(t, n)

redoslijed = {t: i for i, (t, n, w) in enumerate(BELEX15)}
konacno = procisti(sve)

# TTM filter: zadrzi samo dividende novije od TTM_DANA (po datumu objave)
def _iso_pub(n):
    try:
        d, m, g = n["pub_date"].split(".")[:3]
        return f"{int(g):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return "0000-00-00"
granica = (datetime.date.today() - datetime.timedelta(days=TTM_DANA)).isoformat()
prije_ttm = len(konacno)
konacno = [n for n in konacno if _iso_pub(n) >= granica]
izbaceno = prije_ttm - len(konacno)

konacno.sort(key=lambda n: redoslijed.get(n["ticker"], 99))

with open("dividende_bg.json", "w", encoding="utf-8") as f:
    json.dump({"updated_at": datetime.datetime.now().isoformat(timespec="minutes"),
               "composition": sastav, "dividends": konacno},
              f, ensure_ascii=False, indent=2)

print("\n" + "═"*60)
print(f"Gotovo. Dividendi u TTM ({TTM_DANA} dana): {len(konacno)}"
      + (f"  (izbaceno starijih: {izbaceno})" if izbaceno else ""))
for n in konacno:
    print(f"  {n['ticker']:5} {n['gross'] or '(bez iznosa)':>12}  {n['status']}")
print("Zapisano u dividende_bg.json")
