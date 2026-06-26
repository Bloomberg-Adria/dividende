# -*- coding: utf-8 -*-
# ───────────────────────────────────────────────────────────────
#  DIVIDENDE — pravi robot
#
#  1. SAM ucita aktualni sastav CROBEX10 sa ZSE (vise ne diramo popis rukom)
#  2. za svaku firmu prolista arhivu objava godinu unatrag
#  3. u objavama nadje blok "Informacije o dividendi" i izvuce iznos + datume
#  4. ocisti duplikate i zapise u  dividends.json
#
#  Pokrece se:   python dividende.py
# ───────────────────────────────────────────────────────────────

import urllib.request, re, html, json, datetime, time

BAZA = "https://eho.zse.hr"

# Sluzbeni izvor sastava indeksa (CROBEX10 ima ISIN HRZB00ICBE11)
INDEX_ISIN = "HRZB00ICBE11"
SASTAV_URL = f"https://zse.hr/json/IndexComposition?isin={INDEX_ISIN}&lng=hr&order=asc&sort=symbol"

# Lijepa imena za prikaz (za firme koje poznajemo). Ako u indeks udje
# nova firma koju ovdje nemamo, robot ce uzeti ime sa ZSE-a automatski.
LIJEPA_IMENA = {
    "HRADPLRA0006": "AD Plastik",
    "HRADRSPA0009": "Adris grupa (pref.)",
    "HRATGRRA0003": "Atlantic Grupa",
    "HRHPB0RA0002": "Hrvatska po\u0161tanska banka",
    "HRHT00RA0005": "Hrvatski Telekom",
    "HRKODTRA0007": "Kon\u010dar \u2013 Distributivni i specijalni transformatori",
    "HRKOEIRA0009": "Kon\u010dar",
    "HRPODRRA0004": "Podravka",
    "HRRIVPRA0000": "Valamar Riviera",
    "HRZTOSRB0002": "\u017dito",
}

# Rezervni popis ako ZSE sastav-servis bas taj dan ne radi.
REZERVNI_POPIS = {isin: (None, naziv) for isin, naziv in LIJEPA_IMENA.items()}

# None = sve firme iz sastava. (Mozes staviti npr. ["HRKOEIRA0009"] za test jedne.)
SAMO = None

DANA_UNATRAG = 365
MAX_STRANICA = 12
GODINU_DANA = datetime.date.today() - datetime.timedelta(days=DANA_UNATRAG)
DAT = r'\d{2}\.\d{2}\.\d{4}'
KLJUCNE = ("dividend", "skup\u0161tin", "ex-datum", "ex datum")


def dohvati(url, pokusaja=3):
    for n in range(pokusaja):
        try:
            z = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(z, timeout=30) as o:
                return o.read().decode("utf-8", errors="ignore")
        except Exception:
            if n == pokusaja - 1:
                raise
            time.sleep(2)


def ocisti_naziv(s):
    """'AD PLASTIK D.D.' -> 'Ad Plastik d.d.' (da ne vristi velikim slovima)."""
    s = (s or "").strip().title()
    return s.replace(" D.D.", " d.d.").replace(" D.D", " d.d")


def dohvati_sastav():
    """Procita aktualni sastav CROBEX10 sa ZSE. Vraca {isin: (simbol, naziv)}."""
    podaci = json.loads(dohvati(SASTAV_URL))
    firme = {}
    for r in podaci.get("rows", []):
        isin, simbol = r.get("isin"), r.get("symbol")
        if not isin or not simbol:
            continue
        naziv = LIJEPA_IMENA.get(isin) or ocisti_naziv(r.get("name", simbol))
        firme[isin] = (simbol, naziv)
    if not firme:
        raise ValueError("sastav je prazan")
    return firme


def ocisti(h):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h)))


def procitaj_listu(h):
    objave = []
    datumi = list(re.finditer(r'(\d{2})\.(\d{2})\.(\d{4})\.\s*\d{2}:\d{2}', h))
    for i, m in enumerate(datumi):
        blok = h[m.start(): datumi[i + 1].start() if i + 1 < len(datumi) else len(h)]
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        view = re.search(r'(/obavijesti-izdavatelja/view/\d+)', blok)
        objave.append({
            "datum": datetime.date(y, mo, d),
            "tekst": ocisti(blok),
            "view": view.group(1) if view else None,
        })
    return objave


def sljedeca(h, trenutna):
    for m in re.finditer(r'href="([^"]*currentPage%5D=(\d+)[^"]*)"', h):
        if int(m.group(2)) == trenutna + 1:
            return html.unescape(m.group(1))
    return None


def raspon(t, oznaka, sljedece):
    i = t.find(oznaka)
    if i < 0:
        return ""
    poc = i + len(oznaka)
    krajevi = [t.find(s, poc) for s in sljedece if t.find(s, poc) > -1]
    return t[poc: (min(krajevi) if krajevi else poc + 120)]


def u_broj(s):
    m = re.search(r'\d[\d.,]*', s)
    if not m:
        return None
    x = m.group(0)
    if "," in x and "." in x:
        x = x.replace(".", "").replace(",", ".")
    elif "," in x:
        x = x.replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None


def datum_iso(s):
    m = re.search(DAT, s)
    if not m:
        return None
    d, mo, y = m.group(0).split(".")[:3]
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def hrvatsko_vrijeme():
    """Trenutno vrijeme po hrvatskom satu (ljeti +2, zimi +1 od UTC-a),
    da oznaka 'Zadnje osvjezeno' na stranici bude po nasem vremenu."""
    utc = datetime.datetime.utcnow()

    def zadnja_nedjelja(godina, mjesec):
        if mjesec == 12:
            d = datetime.date(godina, 12, 31)
        else:
            d = datetime.date(godina, mjesec + 1, 1) - datetime.timedelta(days=1)
        return d - datetime.timedelta(days=(d.weekday() + 1) % 7)

    pocetak = datetime.datetime.combine(zadnja_nedjelja(utc.year, 3), datetime.time(1, 0))
    kraj = datetime.datetime.combine(zadnja_nedjelja(utc.year, 10), datetime.time(1, 0))
    ljetno = pocetak <= utc < kraj
    return utc + datetime.timedelta(hours=2 if ljetno else 1)


def status_iz(tip, ex, pay):
    t = (tip or "").lower()
    danas = datetime.date.today()
    # Tip dividende ima prednost: ako ZSE kaze "Prijedlog", jos nije
    # izglasano -> "predlozeno", bez obzira na datume.
    if "prijedlog" in t or "predlo" in t or "najav" in t:
        return "proposed"
    # Inace je izglasano/odluceno -> status odredjuju datumi.
    if pay and datetime.date.fromisoformat(pay) < danas:
        return "paid"
    if ex and datetime.date.fromisoformat(ex) <= danas:
        return "ex"
    return "approved"


def parsiraj_detalj(h, naziv, oznaka, view_url):
    if "Vrijednost dividende" not in h and "Informacije o dividendi" not in h:
        return None
    t = ocisti(h)
    iznos = u_broj(raspon(t, "Vrijednost dividende", ["Po\u010detak trgovanja", "Datum stjecanja"]))
    ex = datum_iso(raspon(t, "bez dividende", ["Datum stjecanja"]))
    rec = datum_iso(raspon(t, "prava na dividendu", ["Datum isplate"]))
    pay = datum_iso(raspon(t, "isplate dividende", ["Aktualna", "Informacije"]))
    tip = raspon(t, "Tip dividende", ["Vrsta dividende", "Vrijednost"]).strip()
    return {
        "company": naziv,
        "ticker": oznaka,
        "gross": iznos,
        "currency": "EUR",
        "status": status_iz(tip, ex, pay),
        "ex_date": ex,
        "record_date": rec,
        "payment_date": pay,
        "source_url": BAZA + view_url,
    }


def dedup(zapisi):
    najbolji = {}
    for z in zapisi:
        kljuc = (z["ticker"], z["gross"], z["ex_date"])
        if kljuc not in najbolji or (z.get("_objava") or "") > (najbolji[kljuc].get("_objava") or ""):
            najbolji[kljuc] = z
    rez = list(najbolji.values())
    for z in rez:
        z.pop("_objava", None)
    return rez


def obradi_firmu(isin, oznaka, naziv):
    url = f"{BAZA}/obavijesti-izdavatelja/filter/{isin}"
    stranica, kandidati = 1, []
    while url and stranica <= MAX_STRANICA:
        h = dohvati(url)
        objave = procitaj_listu(h)
        if not objave:
            break
        for o in objave:
            if o["datum"] < GODINU_DANA or not o["view"]:
                continue
            if any(k in o["tekst"].lower() for k in KLJUCNE):
                kandidati.append((o["datum"], o["view"]))
        if min(o["datum"] for o in objave) < GODINU_DANA:
            break
        slj = sljedeca(h, stranica)
        if not slj:
            break
        url = BAZA + slj
        stranica += 1
        time.sleep(1)

    nadjene = []
    print(f"({len(kandidati)} objava za provjeru)", end=" ", flush=True)
    for datum, view in kandidati:
        try:
            h = dohvati(BAZA + view)
        except Exception:
            continue
        zapis = parsiraj_detalj(h, naziv, oznaka, view)
        if zapis:
            zapis["_objava"] = datum.isoformat()
            nadjene.append(zapis)
        time.sleep(0.5)
    return dedup(nadjene)


def main():
    # 1) ucitaj aktualni sastav (s rezervom)
    try:
        firme = dohvati_sastav()
        print(f"Sastav CROBEX10 ucitan sa ZSE: {len(firme)} firmi.")
        novi = [i for i in firme if i not in LIJEPA_IMENA]
        otisli = [i for i in LIJEPA_IMENA if i not in firme]
        if novi:
            print("  ! NOVO u indeksu:", ", ".join(firme[i][0] for i in novi))
        if otisli:
            print("  ! IZASLO iz indeksa:", ", ".join(LIJEPA_IMENA[i] for i in otisli))
    except Exception as e:
        print(f"Ne mogu ucitati sastav ({e}); koristim rezervni popis.")
        firme = REZERVNI_POPIS

    if SAMO:
        firme = {k: v for k, v in firme.items() if k in SAMO}

    print(f"Trazim dividende od {GODINU_DANA.isoformat()} do danas, za {len(firme)} firmu(e).\n")
    sve = []
    for isin, (oznaka, naziv) in firme.items():
        print(f"  {naziv} ({oznaka})...", end=" ", flush=True)
        nadjene = obradi_firmu(isin, oznaka, naziv)
        sve.extend(nadjene)
        if nadjene:
            print()
            for d in nadjene:
                iznos = f"{d['gross']:.2f} EUR" if d["gross"] is not None else "(bez iznosa)"
                print(f"      \u2192 {iznos:>12}  ex {d['ex_date']}  isplata {d['payment_date']}  [{d['status']}]")
        else:
            print("nema dividendi.")
        time.sleep(1)

    with open("dividends.json", "w", encoding="utf-8") as f:
        json.dump({"updated_at": hrvatsko_vrijeme().isoformat(timespec="minutes"),
                   "dividends": sve}, f, ensure_ascii=False, indent=2)
    print("\n" + "-" * 60)
    print(f"Gotovo. Zapisano {len(sve)} dividend(i) u dividends.json")


if __name__ == "__main__":
    main()
