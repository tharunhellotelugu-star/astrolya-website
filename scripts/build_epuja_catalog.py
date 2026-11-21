"""Rebuilds epuja/catalog.json from Vedamandir's public sitemap and puja pages.

Runs daily from .github/workflows/epuja-catalog.yml. Standard library only.
The Astrolya app reads https://astrolya.in/epuja/catalog.json (see EPujaCatalog.kt) and adds the
partner tracking parameters itself, so this file only needs puja ids, titles, dates and tags.

Safety: if fewer than MIN_PUJAS upcoming pujas are found (site change, outage), the existing
catalogue is left untouched and the script exits non-zero so the failed run shows up in Actions.
"""
import datetime as dt
import html as htmllib
import json
import re
import sys
import time
import urllib.request

SITEMAP = "https://vedamandir.com/sitemap.xml"
UA = "AstrolyaCatalogBot/1.0 (+https://astrolya.in)"
OUT = sys.argv[1] if len(sys.argv) > 1 else "epuja/catalog.json"
MIN_PUJAS = 5

# Vedamandir URL prefix -> app language code. Telugu lives at the site root.
PREFIX_LANG = {"en": "en", "hi": "hi", "": "te", "tam": "ta", "ka": "kn", "ml": "ml"}

MONTHS = {
    "en": ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"],
    "hi": ["जनवरी", "फ़रवरी|फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर|सितम्बर", "अक्टूबर", "नवंबर|नवम्बर", "दिसंबर|दिसम्बर"],
    "te": ["జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్", "జులై|జూలై", "ఆగస్టు|ఆగష్టు", "సెప్టెంబర్|సెప్టెంబరు", "అక్టోబర్|అక్టోబరు", "నవంబర్|నవంబరు", "డిసెంబర్|డిసెంబరు"],
    "ta": ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"],
    "kn": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
    "ml": ["ജനുവരി", "ഫെബ്രുവരി", "മാർച്ച്", "ഏപ്രിൽ", "മേയ്|മെയ്", "ജൂൺ", "ജൂലൈ", "ഓഗസ്റ്റ്|ആഗസ്റ്റ്", "സെപ്റ്റംബർ", "ഒക്ടോബർ", "നവംബർ", "ഡിസംബർ"],
}

# Problem-area tags (must match EPujaCatalog.TAGS in the app), matched against the title.
TAG_WORDS = {
    "shani": ["shani", "saturn", "sade sati", "शनि", "శని", "சனி", "ಶನಿ", "ശനി"],
    "rahu_ketu": ["rahu", "ketu", "kaal sarp", "kalsarp", "राहु", "केतु", "कालसर्प", "రాహు", "కేతు", "ராகு", "கேது", "ರಾಹು", "ಕೇತು", "രാഹു", "കേതു"],
    "navagraha": ["navagraha", "navgrah", "नवग्रह", "నవగ్రహ", "நவகிரக", "ನವಗ್ರಹ", "നവഗ്രഹ"],
    "money": ["lakshmi", "laxmi", "kuber", "karza", "debt", "wealth", "dhan ", "aishwarya", "kanakdhara", "samriddhi", "लक्ष्मी", "कुबेर", "कर्ज", "धन", "ऐश्वर्य", "समृद्धि", "కనకధార", "లక్ష్మీ", "కుబేర", "ధన", "ఋణ", "లட்சுமி", "லட்சுமி", "குபேர", "செல்வ", "ಲಕ್ಷ್ಮೀ", "ಕುಬೇರ", "ಧನ", "ലക്ഷ്മി", "കുബേര", "ധന"],
    "marriage": ["vivah", "marriage", "saubhagya", "swayamvar", "kalyan", "विवाह", "सौभाग्य", "स्वयंवर", "వివాహ", "కళ్యాణ", "திருமண", "கல்யாண", "ವಿವಾಹ", "ಕಲ್ಯಾಣ", "വിവാഹ", "സ്വയംവര"],
    "protection": ["raksha", "kavach", "shatru", "bhairav", "baglamukhi", "suraksha", "kasht", "pratyangira", "रक्षा", "कवच", "शत्रु", "भैरव", "बगलामुखी", "రక్ష", "భైరవ", "ரக்ஷ", "பைரவ", "ರಕ್ಷ", "ಭೈರವ", "രക്ഷ", "ഭൈരവ"],
    "health": ["health", "arogya", "mrityunjay", "dhanvantari", "dhanwantari", "rog ", "आरोग्य", "रोग", "मृत्युंजय", "ధన్వంతరి", "మృత్యుంజయ", "ఆరోగ్య", "ஆரோக்கிய", "மிருத்யுஞ்ஜய", "தன்வந்திரி", "ಆರೋಗ್ಯ", "ಮೃತ್ಯುಂಜಯ", "ಧನ್ವಂತರಿ", "ആരോഗ്യ", "മൃത്യുഞ്ജയ", "ധന്വന്തരി"],
    "property": ["bhu varaha", "bhoomi", "land", "property", "vastu", "house construction", "भूमि", "वास्तु", "భూవరాహ", "భూమి", "వాస్తు", "பூவராக", "வாஸ்து", "நில", "ಭೂವರಾಹ", "ಭೂಮಿ", "ವಾಸ್ತು", "ഭൂവരാഹ", "ഭൂമി", "വാസ്തു"],
    "karma": ["janam dosh", "janma dosh", "paap", "pitru", "pitra", "pitr ", "karma", "पाप", "पितृ", "जन्म दोष", "పితృ", "పాప", "பித்ரு", "பித்ரு", "ಪಿತೃ", "പിതൃ"],
    "shiva": ["shiv", "rudra", "mahadev", "शिव", "रुद्र", "శివ", "రుద్ర", "சிவ", "ருத்ர", "ಶಿವ", "ರುದ್ರ", "ശിവ", "രുദ്ര"],
    "obstacles": ["ganesh", "ganapati", "vighna", "obstacle", "sankat", "hanuman", "गणेश", "विघ्न", "संकट", "हनुमान", "గణపతి", "గణేశ", "ఆంజనేయ", "హనుమ", "விநாயக", "கணபதி", "அனுமன்", "ಗಣಪತಿ", "ಗಣೇಶ", "ಹನುಮ", "ഗണപതി", "ഹനുമ"],
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_date(html: str, lang: str, today: dt.date):
    """Reads the '📅 <date> 📍' line every puja page carries, in the page's own language."""
    for seg in re.findall(r"📅(.{1,80}?)📍", html, flags=re.S):
        seg_l = seg.lower()
        month = None
        best = 0
        for i, names in enumerate(MONTHS[lang]):
            for name in names.split("|"):
                if name in seg_l and len(name) > best:
                    month, best = i + 1, len(name)
        if month is None:
            continue
        year_m = re.search(r"\b(20\d\d)\b", seg)
        day_m = [int(d) for d in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", seg) if 1 <= int(d) <= 31]
        if not day_m:
            continue
        year = int(year_m.group(1)) if year_m else today.year
        try:
            date = dt.date(year, month, day_m[0])
        except ValueError:
            continue
        if not year_m and date < today - dt.timedelta(days=60):
            date = date.replace(year=year + 1)
        return date
    return None


def parse_title(html: str):
    m = re.search(r"<title>([^<]+)</title>", html)
    if not m:
        return None
    t = re.sub(r"\s+", " ", htmllib.unescape(m.group(1))).strip()
    return t or None


def tags_for(title: str):
    t = " " + title.lower() + " "
    return [tag for tag, words in TAG_WORDS.items() if any(w in t for w in words)]


def main():
    today = dt.date.today()
    sitemap = fetch(SITEMAP)
    urls = re.findall(r"<loc>https://vedamandir\.com/(?:([a-z]+)/)?pooja-details/(\d+)</loc>", sitemap)
    pujas = []
    for prefix, pid in sorted(set(urls), key=lambda x: (x[0], int(x[1]))):
        lang = PREFIX_LANG.get(prefix or "")
        if lang is None:
            continue
        path = f"{prefix}/pooja-details/{pid}" if prefix else f"pooja-details/{pid}"
        try:
            html = fetch(f"https://vedamandir.com/{path}")
        except Exception as e:  # one bad page shouldn't sink the run
            print(f"skip {path}: {e}", file=sys.stderr)
            continue
        finally:
            time.sleep(0.5)
        title, date = parse_title(html), parse_date(html, lang, today)
        if not title or not date:
            print(f"skip {path}: title={bool(title)} date={date}", file=sys.stderr)
            continue
        if date < today:
            continue
        pujas.append({"key": f"{lang}_{pid}", "tags": tags_for(title), "date": date.isoformat(),
                      "v": {lang: {"id": int(pid), "t": title}}})
        print(f"ok {lang} {pid} {date} {pujas[-1]['tags']}")

    if len(pujas) < MIN_PUJAS:
        print(f"Only {len(pujas)} upcoming pujas found; keeping the existing catalogue.", file=sys.stderr)
        sys.exit(1)

    pujas.sort(key=lambda p: (p["date"], p["key"]))
    catalog = {"version": 1, "updated": today.isoformat(), "validUntil": today.isoformat(), "pujas": pujas}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Wrote {len(pujas)} pujas to {OUT}")


if __name__ == "__main__":
    main()
