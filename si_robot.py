# -*- coding: utf-8 -*-
# ───────────────────────────────────────────────────────────────
#  SLOVENIJA — ROBOT (SBITOP)
#  sastav+cijene: ljse.si JSON  |  dividende: SEONET (HTML/PDF/OCR)
#
#  Treba:  pip install pypdf        (OCR je neobavezan, samo za skenove)
#  Pokreces:  python si_robot.py SVE          (cijeli indeks)
#             python si_robot.py KRKG         (jedna firma)
# ───────────────────────────────────────────────────────────────
import urllib.request, re, io, sys, json, time, datetime, html as _html

try:
    from pypdf import PdfReader
except ImportError:
    print("Nedostaje 'pypdf'.  Pokreni:  pip install pypdf"); sys.exit()

# --- OCR (3. stupanj, neobavezno) ---
OCR_MOGUC, LANG_OCR, POPPLER = False, None, None
try:
    import os, glob, pytesseract
    from pdf2image import convert_from_bytes
    _tw = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_tw):
        pytesseract.pytesseract.tesseract_cmd = _tw
    for k in glob.glob(r"C:\poppler\**\bin", recursive=True):
        if os.path.exists(os.path.join(k, "pdftoppm.exe")):
            POPPLER = k; break
    _j = set(pytesseract.get_languages(config=""))
    LANG_OCR = "slv" if "slv" in _j else ("eng" if "eng" in _j else None)
    OCR_MOGUC = LANG_OCR is not None
except Exception:
    pass

SBITOP_ISIN = "SI0026109882"
TTM_DANA    = 450     # zadrzi dividende novije od ~15 mjeseci
MAX_OBJAVA  = 6       # koliko objava po firmi najvise procitati
MAX_STRANICA_OCR = 6

# ---------- mreza ----------
def dohvati(url, bajtovi=False):
    z = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                             "Accept": "*/*"})
    with urllib.request.urlopen(z, timeout=60) as o:
        b = o.read()
    return b if bajtovi else b.decode("utf-8", errors="ignore")

def _cisto(s):
    return (s or "").replace("&nbsp;", "").strip()

# ---------- 1) sastav indeksa + cijene ----------
def dohvati_sastav():
    u = ("https://ljse.si/json/IndexComposition?search=&sort=symbol&order=asc"
         f"&isin={SBITOP_ISIN}&lng=si")
    p = json.loads(dohvati(u))
    redovi = p.get("rows") if isinstance(p, dict) else p
    firme, sastav = [], []
    for r in redovi or []:
        sym, isin = r.get("symbol"), r.get("isin")
        if not sym or not isin:
            continue
        naziv = (r.get("name") or sym).strip().title()
        firme.append((sym, isin, naziv))
        sastav.append({"ticker": sym, "company": naziv,
                       "weight": _cisto(r.get("weight_percentage")),
                       "price":  _cisto(r.get("last_price")),
                       "change": _cisto(r.get("change_prev_close_percentage"))})
    if not firme:
        raise ValueError("sastav je prazan")
    return firme, sastav

# ---------- 2) objave sa SEONET-a ----------
def objave(isin):
    """Objave koje spominju dividendu — (doc_id, datum), najnovije prvo.
    NAPOMENA: na SEONET-u datum dolazi IZA poveznice na objavu."""
    u = ("https://seonet.ljse.si/default_sl.aspx?doc=SEARCH&language=sl"
         f"&field.words=dividend&field.isin={isin}")
    h = dohvati(u)
    out, vidjeni = [], set()
    for m in re.finditer(r"doc_id=(\d+)", h):
        did = m.group(1)
        if did in vidjeni:
            continue
        vidjeni.add(did)
        poslije = h[m.end(): m.end() + 1200]
        d = re.search(r"(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})", poslije)
        out.append((did, d.group(1) if d else None))
    return out

def tekst_objave(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    i = h.find("visit_publisher")
    if i != -1: h = h[i:]
    t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
    return re.sub(r"^visit_publisher\S*\s*", "", t)

def prilozi(h):
    out = []
    for m in re.finditer(r"""(?:href|src)=['"]([^'"]*file\.aspx\?AttachmentID=\d+)['"]""", h, re.I):
        u = m.group(1)
        if not u.startswith("http"):
            u = "https://seonet.ljse.si/" + u.lstrip("/")
        if u not in out: out.append(u)
    return out

def tekst_pdf(b):
    try:
        r = PdfReader(io.BytesIO(b))
        return "\n".join((s.extract_text() or "") for s in r.pages)
    except Exception:
        return ""

def tekst_ocr(b):
    if not OCR_MOGUC: return ""
    try:
        slike = convert_from_bytes(b, dpi=300, first_page=1,
                                   last_page=MAX_STRANICA_OCR, poppler_path=POPPLER)
        return "\n".join(pytesseract.image_to_string(s, lang=LANG_OCR) for s in slike)
    except Exception:
        return ""

# ---------- 3) vadjenje podataka ----------
def _broj(s):
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return None

def iznos_iz(t):
    """Bruto dividenda PO DELNICI.
    Pravila: mora biti uz 'na delnico', mora biti razumne velicine
    (dividenda po dionici nije milijunska), i prednost ima onaj iznos
    koji je najblizi rijeci 'dividend' (da ne pokupimo npr. cijenu dionice)."""
    kandidati = []
    for m in re.finditer(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*(?:EUR|evr|€)"
                         r"(?=[^)\n]{0,35}?na\s+delnic)", t, re.I):
        v = _broj(m.group(1))
        if v is None or v > 1000:        # milijunski iznosi = ukupno, ne po dionici
            continue
        okolina = t[max(0, m.start()-220): m.end()+120].lower()
        # iskljuci: knjigovodska vrijednost, zarada po dionici, cijena dionice
        # (usko okno — samo ista fraza, ne prethodna recenica)
        blizu = t[max(0, m.start()-45): m.start()].lower()
        if ("knjigovodsk" in blizu or "dobiček na delnic" in blizu
                or "dobicek na delnic" in blizu or "tečaj" in blizu):
            continue

        # iskljuci NIJEKANJE i PROSLE godine:
        # "ni izplačala dividend", "dividenda za leto 2024", "v letu 2025 je bila"
        recenica = t[max(0, m.start()-260): m.end()+60].lower()
        # zadnja tocka prije iznosa = pocetak recenice (grubo, ali dovoljno)
        poc = max(recenica.rfind(". "), recenica.rfind("\n"))
        recenica = recenica[poc+1:] if poc != -1 else recenica
        if re.search(r"\bni\b\s+(?:izplač\w*|bil\w*)|\bne\s+izplač\w*|"
                     r"ni\s+bilo\s+izplač|brez\s+izplačil", recenica):
            continue                      # rijec je o NEisplati
        # dividenda za NEKU STARIJU poslovnu godinu (npr. 2026. spominje "za leto 2024")
        _stare = [str(datetime.date.today().year - k) for k in (2, 3, 4, 5)]
        if re.search(r"za\s+leto\s+(" + "|".join(_stare) + r")\b", recenica):
            continue
        blizina = 999
        for d in re.finditer(r"dividend", okolina):
            blizina = min(blizina, abs(d.start() - 220))
        kandidati.append((blizina, m.start(), m.group(1)))
    if kandidati:
        kandidati.sort()                 # najblizi rijeci 'dividenda' pobjedjuje
        return kandidati[0][2]

    # rezerva: iznos odmah uz rijec 'dividenda', ali samo ako je malen
    for m in re.finditer(r"dividend\w*.{0,90}?(\d{1,3}(?:\.\d{3})*,\d+)\s*(?:EUR|evr|€)",
                         t, re.I | re.S):
        v = _broj(m.group(1))
        if v is not None and v <= 1000:
            return m.group(1)
    return None

def _iso(s):
    d, mj, g = [x.strip() for x in s.split(".")[:3]]
    return f"{int(g):04d}-{int(mj):02d}-{int(d):02d}"

DAT = r"(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})"

def datumi_iz(t):
    """(presjecni dan, datum isplate). Tekst je pun tocaka ('d. d.', datumi),
    pa ne smijemo zabraniti tocku izmedju."""
    rec = pay = None
    # najpouzdanije: obje informacije u istoj recenici
    m = re.search(r"izplač\w*\s+" + DAT + r".{0,250}?na dan\s+" + DAT, t, re.I | re.S)
    if m:
        return _iso(m.group(2)), _iso(m.group(1))

    for uzorak in (r"izplačevati\s+" + DAT,
                   r"izplač\w*\s+(?:dne\s+)?" + DAT,
                   r"dividend\w*.{0,80}?izplač\w*.{0,40}?" + DAT):
        m = re.search(uzorak, t, re.I | re.S)
        if m:
            pay = _iso(m.group(m.lastindex)); break

    for uzorak in (r"presečn\w*\s+(?:dan|datum|presek).{0,60}?" + DAT,
                   r"(?:stanju vpisov|delniško knjigo|delniški knjigi).{0,120}?na dan\s+" + DAT,
                   r"zadnji trgovalni dan.{0,60}?" + DAT,
                   r"vpisani.{0,80}?na dan\s+" + DAT):
        m = re.search(uzorak, t, re.I | re.S)
        if m:
            rec = _iso(m.group(m.lastindex)); break
    return rec, pay

# ---------- 4) obrada jedne firme ----------
def obradi(sym, isin, naziv):
    print(f"\n=== {sym} ({naziv}) ===")
    try:
        lista = objave(isin)
    except Exception as e:
        print("   greska kod popisa objava:", e); return None
    if not lista:
        print("   nema objava o dividendi"); return None

    nalazi = []          # (datum_objave, iznos, rec, pay, doc_id, izvor)
    for doc_id, dat in lista[:MAX_OBJAVA]:
        try:
            hh = dohvati(f"https://seonet.ljse.si/default_sl.aspx?doc=SEARCH&doc_id={doc_id}")
        except Exception:
            continue
        t = tekst_objave(hh)
        izn, izvor = iznos_iz(t), "HTML"

        if not izn:
            for p in prilozi(hh):
                try:
                    b = dohvati(p, bajtovi=True)
                except Exception:
                    continue
                if not b.startswith(b"%PDF"):
                    continue                      # ZIP/Word/slika -> preskoci
                tp, izvor = tekst_pdf(b), "PDF"
                if len(tp.strip()) < 40:          # nema teksta -> sken
                    tp, izvor = tekst_ocr(b), "OCR"
                i2 = iznos_iz(tp)
                if i2:
                    izn, t = i2, tp
                    break

        if izn:
            rec, pay = datumi_iz(t)
            nalazi.append((dat, izn, rec, pay, doc_id, izvor))
            print(f"   • {dat or '?':12} {izn:>9} EUR  ({izvor})")
        time.sleep(0.3)

    if not nalazi:
        print("   — iznos nije pronadjen"); return None

    # NAJNOVIJI POTVRDJENI: uzmi najnoviji iznos koji se pojavljuje u
    # bar DVIJE objave (potvrdjen); ako nijedan nema dvije, uzmi najnoviji.
    # -> kod povecanja dividende novi iznos pobjedjuje cim stigne druga
    #    objava (obicno za par dana), a jedna kriva objava ne moze prevariti.
    def _norm(x):
        v = _broj(x)
        return round(v, 4) if v is not None else x
    glasovi = {}
    for d2, i2, *_ in nalazi:
        glasovi[_norm(i2)] = glasovi.get(_norm(i2), 0) + 1

    izbor = None
    for n in nalazi:                        # nalazi su vec od najnovijeg
        if glasovi[_norm(n[1])] >= 2:
            izbor = n
            break
    if izbor is None:
        izbor = nalazi[0]                   # nista potvrdjeno -> najnoviji

    dat, izn, rec, pay, doc_id, izvor = izbor
    for d2, i2, r2, p2, *_ in nalazi:
        if _norm(i2) == _norm(izn):
            rec = rec or r2
            pay = pay or p2
    potvrda = glasovi[_norm(izn)]
    print(f"   -> {izn} EUR/delnici  ({potvrda}x)   presjek: {rec or '—'}  isplata: {pay or '—'}")
    return {"ticker": sym, "company": naziv, "gross": izn,
            "record_date": rec, "payment_date": pay,
            "pub_date": dat, "doc_id": doc_id, "source": izvor,
            "url": f"https://seonet.ljse.si/default_sl.aspx?doc=SEARCH&doc_id={doc_id}"}

# ══════ glavni dio ══════
arg = sys.argv[1] if len(sys.argv) > 1 else "SVE"
print("SLOVENIJA robot — dohvacam sastav SBITOP...")
firme, sastav = dohvati_sastav()
print(f"Sastavnica: {len(firme)}" + (f"   (OCR: {LANG_OCR})" if OCR_MOGUC else "   (bez OCR-a)"))

if arg != "SVE":
    firme = [f for f in firme if f[0] == arg]

rezultat = []
for sym, isin, naziv in firme:
    r = obradi(sym, isin, naziv)
    if r: rezultat.append(r)

# TTM filtar po datumu objave
def _pub_iso(n):
    try: return _iso(n["pub_date"])
    except Exception: return "0000-00-00"
granica = (datetime.date.today() - datetime.timedelta(days=TTM_DANA)).isoformat()
prije = len(rezultat)
rezultat = [n for n in rezultat if _pub_iso(n) >= granica]
izbaceno = prije - len(rezultat)

redoslijed = {s["ticker"]: i for i, s in enumerate(sastav)}
rezultat.sort(key=lambda n: redoslijed.get(n["ticker"], 99))

with open("dividende_si.json", "w", encoding="utf-8") as f:
    json.dump({"updated_at": datetime.datetime.now().isoformat(timespec="minutes"),
               "composition": sastav, "dividends": rezultat},
              f, ensure_ascii=False, indent=2)

print("\n" + "═"*62)
print(f"Gotovo. Dividendi u TTM: {len(rezultat)}"
      + (f"  (izbaceno starijih: {izbaceno})" if izbaceno else ""))
for n in rezultat:
    print(f"  {n['ticker']:6} {n['gross']:>9} EUR   presjek {n['record_date'] or '—'}")
print("Zapisano u dividende_si.json")
