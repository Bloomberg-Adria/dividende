# -*- coding: utf-8 -*-
# ───────────────────────────────────────────────────────────────
#  DIVIDENDE — pravi robot (verzija sa strukturiranim blokom)
#
#  Za svaku firmu: prolista arhivu objava (godinu unatrag), u\u0111e u
#  objave koje izgledaju kao dividenda/skup\u0161tina, i u svakoj potra\u017ei
#  blok "Informacije o dividendi". Ako ga na\u0111e -> izvu\u010de iznos i datume.
#  Sve zapi\u0161e u  dividends.json.
#
#  Pokre\u0107e\u0161:   python dividende.py
# ───────────────────────────────────────────────────────────────

import urllib.request, re, html, json, datetime, time

BAZA = "https://eho.zse.hr"

FIRME = {
    "HRADPLRA0006": ("ADPL",  "AD Plastik"),
    "HRADRSPA0009": ("ADRS2", "Adris grupa (pref.)"),
    "HRATGRRA0003": ("ATGR",  "Atlantic Grupa"),
    "HRHPB0RA0002": ("HPB",   "Hrvatska po\u0161tanska banka"),
    "HRHT00RA0005": ("HT",    "Hrvatski Telekom"),
    "HRKODTRA0007": ("KODT",  "Kon\u010dar \u2013 Distributivni i specijalni transformatori"),
    "HRKOEIRA0009": ("KOEI",  "Kon\u010dar"),
    "HRPODRRA0004": ("PODR",  "Podravka"),
    "HRRIVPRA0000": ("RIVP",  "Valamar Riviera"),
    "HRZTOSRB0002": ("ZITO",  "\u017dito"),
}

# None = svih 10 firmi. (Mo\u017ee\u0161 staviti npr. ["HRKOEIRA0009"] za test jedne.)
SAMO = None

DANA_UNATRAG = 365
MAX_STRANICA = 12
GODINU_DANA = datetime.date.today() - datetime.timedelta(days=DANA_UNATRAG)
DAT = r'\d{2}\.\d{2}\.\d{4}'
# objave koje vrijedi otvoriti (ostale ne diramo)
KLJUCNE = ("dividend", "skup\u0161tin", "ex-datum", "ex datum")


def dohvati(url, pokusaja=3):
    for n in range(pokusaja):
        try:
            z = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(z, timeout=30) as o:
                return o.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if n == pokusaja - 1:
                raise
            time.sleep(2)   # kratka pauza pa poku\u0161aj ponovno


def ocisti(h):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h)))


def procitaj_listu(h):
    """Iz stranice popisa vrati objave: datum, tekst, link na detalj (/view/ID)."""
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


def status_iz(tip, ex, pay):
    t = (tip or "").lower()
    danas = datetime.date.today()
    if pay and datetime.date.fromisoformat(pay) < danas:
        return "paid"
    if ex and datetime.date.fromisoformat(ex) <= danas:
        return "ex"
    if "predlo" in t or "najav" in t or "predujam" in t:
        return "proposed"
    return "approved"


def parsiraj_detalj(h, naziv, oznaka, view_url):
    """Ako stranica detalja ima blok o dividendi, vrati zapis; ina\u010de None."""
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
    """Ista firma + isti iznos + isti ex-datum = jedna dividenda.
    Zadr\u017eava onu iz najnovije objave (ispravak gazi staro)."""
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
    # 1) skupi kandidate (datum + link na detalj) iz arhive
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

    # 2) u\u0111i u svaku kandidat-objavu i potra\u017ei blok
    nadjene = []
    print(f"({len(kandidati)} objava za provjeru)", end=" ", flush=True)
    for datum, view in kandidati:
        try:
            h = dohvati(BAZA + view)
        except Exception:
            continue
        zapis = parsiraj_detalj(h, naziv, oznaka, view)
        if zapis:
            zapis["_objava"] = datum.isoformat()   # za biranje najnovije
            nadjene.append(zapis)
        time.sleep(0.5)
    return dedup(nadjene)


def main():
    firme = {k: v for k, v in FIRME.items() if (SAMO is None or k in SAMO)}
    print(f"Tra\u017eim dividende od {GODINU_DANA.isoformat()} do danas, za {len(firme)} firmu(e).\n")
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
        json.dump({"updated_at": datetime.datetime.now().isoformat(timespec="minutes"),
                   "dividends": sve}, f, ensure_ascii=False, indent=2)
    print("\n" + "─" * 60)
    print(f"Gotovo. Zapisano {len(sve)} dividend(i) u dividends.json")


if __name__ == "__main__":
    main()
