"""Location normalisation: free-text location strings -> canonical cities + ISO country codes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# canonical city -> (country, aliases)
CITIES: dict[str, tuple[str, list[str]]] = {
    "Bengaluru": ("IN", ["bangalore", "bengaluru", "blr", "bengalore"]),
    "Mumbai": ("IN", ["mumbai", "bombay", "navi mumbai", "thane", "powai"]),
    "Delhi": ("IN", ["new delhi", "delhi"]),
    "Gurugram": ("IN", ["gurgaon", "gurugram"]),
    "Noida": ("IN", ["noida", "greater noida"]),
    "Hyderabad": ("IN", ["hyderabad", "secunderabad"]),
    "Pune": ("IN", ["pune", "poona"]),
    "Chennai": ("IN", ["chennai", "madras"]),
    "Kolkata": ("IN", ["kolkata", "calcutta"]),
    "Ahmedabad": ("IN", ["ahmedabad", "gandhinagar", "gift city"]),
    "Jaipur": ("IN", ["jaipur"]),
    "Kochi": ("IN", ["kochi", "cochin"]),
    "Thiruvananthapuram": ("IN", ["trivandrum", "thiruvananthapuram"]),
    "Chandigarh": ("IN", ["chandigarh", "mohali"]),
    "Indore": ("IN", ["indore"]),
    "Coimbatore": ("IN", ["coimbatore"]),
    "San Francisco": ("US", ["san francisco", "sf bay area", "bay area", "palo alto", "mountain view", "menlo park", "sunnyvale", "san jose", "south san francisco", "redwood city", "san mateo", "oakland", "cupertino", "santa clara"]),
    "New York": ("US", ["new york", "nyc", "brooklyn", "manhattan"]),
    "Seattle": ("US", ["seattle", "bellevue", "redmond", "kirkland"]),
    "Los Angeles": ("US", ["los angeles", "santa monica"]),
    "Boston": ("US", ["boston", "cambridge, ma"]),
    "Austin": ("US", ["austin"]),
    "Chicago": ("US", ["chicago"]),
    "Denver": ("US", ["denver", "boulder"]),
    "Washington DC": ("US", ["washington, dc", "washington dc", "arlington, va"]),
    "Atlanta": ("US", ["atlanta"]),
    "Miami": ("US", ["miami"]),
    "London": ("GB", ["london"]),
    "Cambridge UK": ("GB", ["cambridge, uk", "cambridge, united kingdom"]),
    "Dublin": ("IE", ["dublin"]),
    "Berlin": ("DE", ["berlin"]),
    "Munich": ("DE", ["munich", "münchen"]),
    "Amsterdam": ("NL", ["amsterdam"]),
    "Paris": ("FR", ["paris"]),
    "Zurich": ("CH", ["zurich", "zürich"]),
    "Stockholm": ("SE", ["stockholm"]),
    "Barcelona": ("ES", ["barcelona"]),
    "Madrid": ("ES", ["madrid"]),
    "Lisbon": ("PT", ["lisbon", "lisboa"]),
    "Warsaw": ("PL", ["warsaw", "warszawa"]),
    "Tel Aviv": ("IL", ["tel aviv"]),
    "Dubai": ("AE", ["dubai"]),
    "Singapore": ("SG", ["singapore"]),
    "Tokyo": ("JP", ["tokyo"]),
    "Sydney": ("AU", ["sydney"]),
    "Melbourne": ("AU", ["melbourne"]),
    "Toronto": ("CA", ["toronto"]),
    "Vancouver": ("CA", ["vancouver"]),
    "Montreal": ("CA", ["montreal"]),
    "São Paulo": ("BR", ["sao paulo", "são paulo"]),
    "Jakarta": ("ID", ["jakarta"]),
}

COUNTRIES: dict[str, list[str]] = {
    "IN": ["india", "bharat"],
    "US": ["united states", "usa", "u.s.", "us-based", "america"],
    "GB": ["united kingdom", "uk", "england", "scotland", "great britain"],
    "IE": ["ireland"],
    "DE": ["germany", "deutschland"],
    "NL": ["netherlands"],
    "FR": ["france"],
    "CH": ["switzerland"],
    "ES": ["spain"],
    "PT": ["portugal"],
    "PL": ["poland"],
    "SE": ["sweden"],
    "IL": ["israel"],
    "AE": ["united arab emirates", "uae"],
    "SG": ["singapore"],
    "JP": ["japan"],
    "AU": ["australia"],
    "CA": ["canada"],
    "BR": ["brazil"],
    "MX": ["mexico"],
    "ID": ["indonesia"],
    "PH": ["philippines"],
    "VN": ["vietnam"],
}

# Regions that remote postings commonly restrict to.
REGIONS: dict[str, list[str]] = {
    "EU": ["europe", "emea", "eu only", "european union", "cet", "cest"],
    "AMER": ["north america", "americas", "latam", "latin america"],
    "APAC": ["apac", "asia", "asia pacific"],
}

WORLDWIDE = re.compile(r"\b(worldwide|anywhere|global(?:ly)?|work from anywhere|any location|international)\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|wfh|distributed|telecommute)\b", re.I)
HYBRID = re.compile(r"\bhybrid\b", re.I)

_CITY_RE = [(city, cc, re.compile(r"\b(" + "|".join(re.escape(a) for a in aliases) + r")\b", re.I)) for city, (cc, aliases) in CITIES.items()]
_COUNTRY_RE = [(cc, re.compile(r"(?<![\w.])(" + "|".join(re.escape(a) for a in names) + r")(?![\w])", re.I)) for cc, names in COUNTRIES.items()]
_REGION_RE = [(r, re.compile(r"\b(" + "|".join(re.escape(a) for a in names) + r")\b", re.I)) for r, names in REGIONS.items()]
# Bare ISO codes / US state codes at the end of "City, XX"
_TRAILING_CODE = re.compile(r",\s*([A-Z]{2})\b")
_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


@dataclass
class ParsedLocation:
    cities: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    remote: bool = False
    hybrid: bool = False
    worldwide: bool = False


def parse_location(raw: str | None, country_hints: list[str] | None = None) -> ParsedLocation:
    out = ParsedLocation()
    text = raw or ""
    for city, cc, pat in _CITY_RE:
        if pat.search(text):
            out.cities.append(city)
            if cc not in out.countries:
                out.countries.append(cc)
    for cc, pat in _COUNTRY_RE:
        if pat.search(text) and cc not in out.countries:
            out.countries.append(cc)
    for m in _TRAILING_CODE.finditer(text):
        code = m.group(1)
        cc = "US" if code in _US_STATES and code != "IN" else code
        if code == "IN" and not re.search(r"\bIndia\b", text) and re.search(r"Indiana", text):
            cc = "US"
        if cc in COUNTRIES and cc not in out.countries:
            out.countries.append(cc)
    for region, pat in _REGION_RE:
        if pat.search(text):
            out.regions.append(region)
    for hint in country_hints or []:
        cc = normalize_country(hint)
        if cc and cc not in out.countries:
            out.countries.append(cc)
    out.remote = bool(REMOTE.search(text))
    out.hybrid = bool(HYBRID.search(text))
    out.worldwide = bool(WORLDWIDE.search(text)) or (out.remote and not out.countries and not out.regions and text.strip().lower() in {"remote", "remote job", "100% remote", "fully remote"})
    return out


def normalize_country(value: str) -> str | None:
    v = value.strip()
    if len(v) == 2 and v.upper() in COUNTRIES:
        return v.upper()
    if v.upper() in {"USA", "UK"}:
        return "US" if v.upper() == "USA" else "GB"
    for cc, pat in _COUNTRY_RE:
        if pat.fullmatch(v) or pat.search(v):
            return cc
    return None
