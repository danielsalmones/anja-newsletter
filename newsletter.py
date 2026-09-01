#!/usr/bin/env python3
"""
Newsletter automático de conciertos de Anja Bihlmaier.
Scraping semanal del calendario y envío por email en alemán.
Ejecución: GitHub Actions cada domingo a las ~10:00 hora española.
"""

import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from html import unescape
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")
URL_CALENDARIO = "https://anjabihlmaier.de/de/kalender/"
STATE_FILE = "state.json"
MAX_EVENTOS_LISTA = 10
DIAS_UMBRAL_PROXIMOS = 7

DIAS_ALEMAN = [
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
]
MESES_ALEMAN = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
_MESES_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
ETIQUETAS_CAMPOS = {
    "date": "Datum", "venue": "Saal", "city": "Stadt",
    "program": "Programm", "soloists": "Solisten", "orchestra": "Orchester",
}
CAMPOS_COMPARABLES = list(ETIQUETAS_CAMPOS.keys())


def _n(s: str) -> str:
    t = s.lower().strip()
    for a, b in (
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
        ("â", "a"), ("ê", "e"), ("î", "i"), ("ô", "o"), ("û", "u"),
        ("ñ", "n"), ("ç", "c"), ("ï", "i"), ("ë", "e"),
        ("š", "s"), ("ž", "z"), ("č", "c"), ("ř", "r"),
        ("ť", "t"), ("ď", "d"), ("ň", "n"), ("ů", "u"),
    ):
        t = t.replace(a, b)
    return t


CITY_FLAGS: dict[str, str] = {
    "berlin": "DE", "münchen": "DE", "munich": "DE", "hamburg": "DE",
    "frankfurt": "DE", "köln": "DE", "koln": "DE", "cologne": "DE",
    "dortmund": "DE", "bonn": "DE", "mannheim": "DE", "düsseldorf": "DE",
    "dusseldorf": "DE", "stuttgart": "DE", "leipzig": "DE", "dresden": "DE",
    "nürnberg": "DE", "nurnberg": "DE", "hannover": "DE", "wiesbaden": "DE",
    "mainz": "DE", "essen": "DE", "bremen": "DE", "duisburg": "DE",
    "bochum": "DE", "wuppertal": "DE", "bielefeld": "DE", "karlsruhe": "DE",
    "freiburg": "DE", "lubeck": "DE", "lübeck": "DE", "erfurt": "DE",
    "saarbrucken": "DE", "saarbrücken": "DE", "mönchengladbach": "DE",
    "monchengladbach": "DE", "braunschweig": "DE", "chemnitz": "DE",
    "krefeld": "DE", "augsburg": "DE", "gelsenkirchen": "DE",
    "madrid": "ES", "barcelona": "ES", "valencia": "ES", "sevilla": "ES",
    "bilbao": "ES", "zaragoza": "ES", "malaga": "ES", "málaga": "ES",
    "alcoi": "ES", "alcoy": "ES", "la vall d'uixo": "ES", "la vall duixo": "ES",
    "castellon": "ES", "castellón": "ES", "alicante": "ES", "granada": "ES",
    "santander": "ES", "oviedo": "ES", "palma": "ES", "palma de mallorca": "ES",
    "vigo": "ES", "gijon": "ES", "gijón": "ES", "a coruna": "ES",
    "a coruña": "ES", "vitoria": "ES", "terrassa": "ES", "sabadell": "ES",
    "jerez": "ES", "pamplona": "ES", "leon": "ES", "león": "ES",
    "almeria": "ES", "almería": "ES", "burgos": "ES", "salamanca": "ES",
    "tarragona": "ES", "lleida": "ES", "girona": "ES", "sant cugat": "ES",
    "san sebastian": "ES", "donostia": "ES", "logrono": "ES", "logroño": "ES",
    "badajoz": "ES", "cartagena": "ES", "tenerife": "ES", "las palmas": "ES",
    "wien": "AT", "linz": "AT", "graz": "AT", "salzburg": "AT",
    "innsbruck": "AT", "bregenz": "AT", "wels": "AT", "klagenfurt": "AT",
    "zürich": "CH", "zurich": "CH", "basel": "CH", "bern": "CH",
    "luzern": "CH", "lucerne": "CH", "genf": "CH", "geneve": "CH",
    "genève": "CH", "lausanne": "CH", "winterthur": "CH", "st. gallen": "CH",
    "st gallen": "CH", "lugano": "CH", "biel": "CH",
    "amsterdam": "NL", "rotterdam": "NL", "den haag": "NL", "the hague": "NL",
    "utrecht": "NL", "heerlen": "NL", "herleen": "NL",
    "eindhoven": "NL", "tilburg": "NL", "groningen": "NL", "breda": "NL",
    "nijmegen": "NL", "arnhem": "NL", "haarlem": "NL", "maastricht": "NL",
    "leiden": "NL", "delft": "NL", "alkmaar": "NL", "zwolle": "NL",
    "enschede": "NL", "amersfoort": "NL",
    "brussel": "BE", "bruxelles": "BE", "brussels": "BE", "antwerpen": "BE",
    "antwerp": "BE", "gent": "BE", "ghent": "BE", "brugge": "BE",
    "bruges": "BE", "liege": "BE", "liège": "BE", "namur": "BE",
    "mons": "BE", "charleroi": "BE", "leuven": "BE", "mechelen": "BE",
    "london": "GB", "manchester": "GB", "birmingham": "GB", "glasgow": "GB",
    "edinburgh": "GB", "liverpool": "GB", "bristol": "GB", "leeds": "GB",
    "sheffield": "GB", "cardiff": "GB", "belfast": "GB", "nottingham": "GB",
    "newcastle": "GB", "southampton": "GB", "brighton": "GB", "oxford": "GB",
    "cambridge": "GB", "coventry": "GB",
    "dublin": "IE", "cork": "IE", "limerick": "IE", "galway": "IE",
    "paris": "FR", "lyon": "FR", "strasbourg": "FR", "marseille": "FR",
    "toulouse": "FR", "nice": "FR", "nantes": "FR", "bordeaux": "FR",
    "lille": "FR", "rennes": "FR", "reims": "FR", "montpellier": "FR",
    "toulon": "FR", "grenoble": "FR", "dijon": "FR", "angers": "FR",
    "le havre": "FR", "clermont-ferrand": "FR", "tours": "FR",
    "limoges": "FR", "amiens": "FR", "metz": "FR", "perpignan": "FR",
    "besancon": "FR", "besançon": "FR", "rouen": "FR", "caen": "FR",
    "mulhouse": "FR", "orleans": "FR", "orléans": "FR",
    "rom": "IT", "roma": "IT", "rome": "IT", "milan": "IT", "milano": "IT",
    "torino": "IT", "turin": "IT", "venezia": "IT", "venice": "IT",
    "firenze": "IT", "florence": "IT", "bologna": "IT", "genova": "IT",
    "genoa": "IT", "palermo": "IT", "napoli": "IT", "naples": "IT",
    "catania": "IT", "verona": "IT", "padova": "IT", "padua": "IT",
    "brescia": "IT", "trieste": "IT", "parma": "IT", "cagliari": "IT",
    "messina": "IT", "pescara": "IT", "livorno": "IT", "bergamo": "IT",
    "rimini": "IT", "ferrara": "IT", "salerno": "IT", "modena": "IT",
    "monza": "IT", "siracusa": "IT", "udine": "IT", "trento": "IT",
    "bolzano": "IT", "vicenza": "IT", "ancona": "IT",
    "lisboa": "PT", "lisbon": "PT", "porto": "PT", "oporto": "PT",
    "braga": "PT", "coimbra": "PT", "funchal": "PT", "faro": "PT",
    "evora": "PT", "évora": "PT", "aveiro": "PT", "guimaraes": "PT",
    "guimarães": "PT", "setubal": "PT", "setúbal": "PT",
    "helsinki": "FI", "espoo": "FI", "tampere": "FI", "vantaa": "FI",
    "oulu": "FI", "turku": "FI", "jyvaskyla": "FI", "jyväskylä": "FI",
    "stockholm": "SE", "göteborg": "SE", "goteborg": "SE", "malmo": "SE",
    "malmö": "SE", "uppsala": "SE", "linkoping": "SE", "linköping": "SE",
    "orebro": "SE", "örebro": "SE", "vasteras": "SE", "västerås": "SE",
    "norrkoping": "SE", "norrköping": "SE", "helsingborg": "SE",
    "jonkoping": "SE", "jönköping": "SE", "lund": "SE", "umea": "SE",
    "umeå": "SE",
    "oslo": "NO", "bergen": "NO", "stavanger": "NO", "trondheim": "NO",
    "tromso": "NO", "tromsø": "NO", "drammen": "NO", "fredrikstad": "NO",
    "kristiansand": "NO", "sandnes": "NO",
    "kopenhagen": "DK", "københavn": "DK", "copenhagen": "DK",
    "aarhus": "DK", "århus": "DK", "odense": "DK", "aalborg": "DK",
    "esbjerg": "DK", "randers": "DK", "kolding": "DK", "roskilde": "DK",
    "warschau": "PL", "warsaw": "PL", "warszawa": "PL", "krakow": "PL",
    "kraków": "PL", "lodz": "PL", "łódź": "PL", "wroclaw": "PL",
    "wrocław": "PL", "poznan": "PL", "poznań": "PL", "gdansk": "PL",
    "gdańsk": "PL", "szczecin": "PL", "lublin": "PL", "bydgoszcz": "PL",
    "katowice": "PL", "bialystok": "PL", "białystok": "PL",
    "prag": "CZ", "praha": "CZ", "prague": "CZ", "brno": "CZ",
    "ostrava": "CZ", "plzen": "CZ", "plzeň": "CZ", "liberec": "CZ",
    "olomouc": "CZ",
    "new york": "US", "los angeles": "US", "hollywood": "US", "chicago": "US",
    "boston": "US", "san francisco": "US", "washington": "US",
    "philadelphia": "US", "miami": "US", "atlanta": "US", "dallas": "US",
    "houston": "US", "detroit": "US", "seattle": "US", "denver": "US",
    "san diego": "US", "minneapolis": "US", "portland": "US",
    "tokio": "JP", "tokyo": "JP", "osaka": "JP", "kyoto": "JP",
    "yokohama": "JP", "nagoya": "JP",
    "pekin": "CN", "beijing": "CN", "shanghai": "CN", "guangzhou": "CN",
    "shenzhen": "CN",
    "seul": "KR", "seoul": "KR", "busan": "KR",
    "moskau": "RU", "moscow": "RU", "sankt petersburg": "RU", "st. petersburg": "RU",
    "budapest": "HU", "debrecen": "HU", "szeged": "HU",
    "bukarest": "RO", "bucharest": "RO", "cluj-napoca": "RO",
    "timisoara": "RO", "iasi": "RO",
    "athen": "GR", "athens": "GR", "thessaloniki": "GR",
    "zagreb": "HR", "split": "HR", "rijeka": "HR", "dubrovnik": "HR",
    "ljubljana": "SI", "maribor": "SI",
    "bratislava": "SK", "kosice": "SK", "košice": "SK",
    "vilnius": "LT", "kaunas": "LT", "riga": "LV", "tallinn": "EE",
    "luxemburg": "LU", "luxembourg": "LU", "reykjavik": "IS", "reykjavík": "IS",
    "belgrad": "RS", "belgrade": "RS", "sofia": "BG", "plovdiv": "BG",
    "kiew": "UA", "kyiv": "UA", "kiev": "UA", "lviv": "UA", "odessa": "UA",
    "odesa": "UA",
    "istanbul": "TR", "ankara": "TR", "izmir": "TR",
    "tel aviv": "IL", "jerusalem": "IL", "dubai": "AE", "singapur": "SG",
    "singapore": "SG",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "auckland": "NZ", "wellington": "NZ",
    "sao paulo": "BR", "são paulo": "BR", "rio de janeiro": "BR",
    "brasilia": "BR", "brasília": "BR",
    "buenos aires": "AR", "cordoba": "AR", "córdoba": "AR",
    "santiago": "CL", "valparaiso": "CL", "valparaíso": "CL",
    "bogota": "CO", "bogotá": "CO", "medellin": "CO", "medellín": "CO",
    "mexico city": "MX", "ciudad de mexico": "MX", "guadalajara": "MX",
    "monterrey": "MX", "lima": "PE",
    "rabat": "MA", "casablanca": "MA", "marrakesch": "MA", "marrakech": "MA",
    "kapstadt": "ZA", "cape town": "ZA", "johannesburg": "ZA",
    "kairo": "EG", "cairo": "EG",
}

COUNTRY_NAMES: dict[str, str] = {
    "deutschland": "DE", "germany": "DE", "allemagne": "DE",
    "spanien": "ES", "españa": "ES", "spain": "ES", "espagne": "ES",
    "österreich": "AT", "austria": "AT", "autriche": "AT",
    "schweiz": "CH", "switzerland": "CH", "suisse": "CH",
    "niederlande": "NL", "netherlands": "NL", "holland": "NL", "pays-bas": "NL",
    "belgien": "BE", "belgium": "BE", "belgique": "BE",
    "grossbritannien": "GB", "vereinigtes königreich": "GB",
    "united kingdom": "GB", "england": "GB",
    "irland": "IE", "ireland": "IE", "irlande": "IE",
    "frankreich": "FR", "france": "FR",
    "italien": "IT", "italy": "IT", "italie": "IT",
    "portugal": "PT",
    "finnland": "FI", "finland": "FI",
    "schweden": "SE", "sweden": "SE",
    "norwegen": "NO", "norway": "NO",
    "danemark": "DK", "dänemark": "DK", "denmark": "DK",
    "polen": "PL", "poland": "PL",
    "tschechien": "CZ", "czech republic": "CZ",
    "usa": "US", "united states": "US", "vereinigte staaten": "US",
    "japan": "JP", "china": "CN", "korea": "KR", "südkorea": "KR",
    "russland": "RU", "russia": "RU", "ungarn": "HU", "hungary": "HU",
    "rumänien": "RO", "romania": "RO", "griechenland": "GR", "greece": "GR",
    "kroatien": "HR", "croatia": "HR", "slowenien": "SI", "slovenia": "SI",
    "slowakei": "SK", "slovakia": "SK", "litauen": "LT", "lettland": "LV",
    "estland": "EE", "luxemburg": "LU", "island": "IS", "iceland": "IS",
    "serbien": "RS", "serbia": "RS", "bulgarien": "BG", "bulgaria": "BG",
    "ukraine": "UA", "türkei": "TR", "turkey": "TR", "israel": "IL",
    "australien": "AU", "australia": "AU", "neuseeland": "NZ", "new zealand": "NZ",
    "brasilien": "BR", "brazil": "BR", "argentinien": "AR", "argentina": "AR",
    "chile": "CL", "kolumbien": "CO", "colombia": "CO", "mexiko": "MX",
    "peru": "PE", "perú": "PE", "marokko": "MA", "morocco": "MA",
    "südafrika": "ZA", "south africa": "ZA", "ägypten": "EG", "egypt": "EG",
}

FLAG_EMOJI: dict[str, str] = {
    "DE": "🇩🇪", "ES": "🇪🇸", "AT": "🇦🇹", "CH": "🇨🇭", "NL": "🇳🇱",
    "BE": "🇧🇪", "GB": "🇬🇧", "IE": "🇮🇪", "FR": "🇫🇷", "IT": "🇮🇹",
    "PT": "🇵🇹", "FI": "🇫🇮", "SE": "🇸🇪", "NO": "🇳🇴", "DK": "🇩🇰",
    "PL": "🇵🇱", "CZ": "🇨🇿", "US": "🇺🇸", "JP": "🇯🇵", "CN": "🇨🇳",
    "KR": "🇰🇷", "RU": "🇷🇺", "HU": "🇭🇺", "RO": "🇷🇴", "GR": "🇬🇷",
    "HR": "🇭🇷", "SI": "🇸🇮", "SK": "🇸🇰", "LT": "🇱🇹", "LV": "🇱🇻",
    "EE": "🇪🇪", "LU": "🇱🇺", "IS": "🇮🇸", "RS": "🇷🇸", "BG": "🇧🇬",
    "UA": "🇺🇦", "TR": "🇹🇷", "IL": "🇮🇱", "AE": "🇦🇪", "SG": "🇸🇬",
    "AU": "🇦🇺", "NZ": "🇳🇿", "BR": "🇧🇷", "AR": "🇦🇷", "CL": "🇨🇱",
    "CO": "🇨🇴", "MX": "🇲🇽", "PE": "🇵🇪", "MA": "🇲🇦", "ZA": "🇿🇦",
    "EG": "🇪🇬",
}
@dataclass
class Evento:
    id: str
    fecha_iso: str
    orquesta: str
    programa: str
    solistas: str
    sala: str
    ciudad: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fecha_date(self) -> date:
        return date.fromisoformat(self.fecha_iso)

    @property
    def texto_completo(self) -> str:
        return " ".join(
            filter(None, [self.orquesta, self.programa, self.solistas,
                          self.sala, self.ciudad])
        )


def obtener_bandera(ciudad: str, texto_completo: str = "") -> str:
    norm = _n(ciudad)
    if norm in CITY_FLAGS:
        codigo = CITY_FLAGS[norm]
        return FLAG_EMOJI.get(codigo, "🌍")
    texto_lower = texto_completo.lower()
    for nombre, codigo in COUNTRY_NAMES.items():
        if nombre in texto_lower:
            return FLAG_EMOJI.get(codigo, "🌍")
    return "🌍"


def es_espana(ciudad: str, texto_completo: str = "") -> bool:
    norm = _n(ciudad)
    if norm in CITY_FLAGS and CITY_FLAGS[norm] == "ES":
        return True
    texto_lower = texto_completo.lower()
    for nombre, codigo in COUNTRY_NAMES.items():
        if nombre in texto_lower and codigo == "ES":
            return True
    return False


def parsear_fecha(texto: str) -> Optional[date]:
    texto = texto.strip()
    m = re.match(r"(\w{3})\s+(\d{1,2})\s+(\d{4})", texto)
    if not m:
        return None
    mes = _MESES_EN.get(m.group(1).lower())
    if mes is None:
        return None
    try:
        return date(int(m.group(3)), mes, int(m.group(2)))
    except ValueError:
        return None


def fecha_alemana(d: date) -> str:
    dia_semana = DIAS_ALEMAN[d.weekday()]
    mes = MESES_ALEMAN[d.month - 1]
    return f"{dia_semana}, {d.day}. {mes} {d.year}"


def fecha_alemana_iso(iso: str) -> str:
    return fecha_alemana(date.fromisoformat(iso))


def generar_id(fecha_iso: str, ciudad: str, programa: str, url: str) -> str:
    if url:
        return url
    cadena = f"{fecha_iso}|{ciudad}|{programa}"
    return "hash:" + hashlib.sha1(cadena.encode("utf-8")).hexdigest()


def texto_proximidad(dias: int) -> Optional[str]:
    if dias < 0:
        return None
    if dias == 0:
        return "heute"
    if dias == 1:
        return "morgen"
    if dias <= DIAS_UMBRAL_PROXIMOS:
        return f"in {dias} Tagen"
    return None


def _limpiar(texto: str) -> str:
    if not texto:
        return ""
    return unescape(texto).strip()


def scrape_eventos() -> list[Evento]:
    resp = requests.get(
        URL_CALENDARIO,
        headers={"User-Agent": "AnjaBihlmaierCalendarBot/1.0"},
        timeout=30,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    actualidad = soup.select_one("div#aktuell")
    if not actualidad:
        raise RuntimeError(
            "No se encontró div#aktuell en la página. "
            "¿Cambió la estructura de la web?"
        )
    eventos_raw: list[Evento] = []
    for bloque in actualidad.select("div.newsblok"):
        ev = _parsear_bloque(bloque)
        if ev:
            eventos_raw.append(ev)
    hoy = datetime.now(MADRID_TZ).date()
    eventos_futuros = [e for e in eventos_raw if e.fecha_date >= hoy]
    eventos_futuros.sort(key=lambda e: e.fecha_iso)
    vistos: set[str] = set()
    unicos: list[Evento] = []
    for ev in eventos_futuros:
        if ev.id not in vistos:
            vistos.add(ev.id)
            unicos.append(ev)
    return unicos


def _parsear_bloque(bloque: BeautifulSoup) -> Optional[Evento]:
    h3 = bloque.find("h3")
    if not h3:
        return None
    fecha = parsear_fecha(h3.get_text())
    if not fecha:
        return None
    h4 = bloque.find("h4")
    orquesta = _limpiar(h4.get_text()) if h4 else ""
    h5 = bloque.find("h5")
    programa = _limpiar(h5.get_text()) if h5 else ""
    h6 = bloque.find("h6")
    solistas = _limpiar(h6.get_text()) if h6 else ""
    sala, ciudad = "", ""
    for p in bloque.find_all("p", recursive=False):
        if not p.find("a"):
            texto_loc = _limpiar(p.get_text())
            partes = texto_loc.rsplit(",", 1)
            if len(partes) == 2:
                sala = partes[0].strip()
                ciudad = partes[1].strip()
            else:
                ciudad = partes[0].strip()
            break
    url = ""
    link = bloque.find("a", class_="buttonlink")
    if link and link.get("href"):
        url = link["href"].strip()
        if url.startswith("/"):
            url = "https://anjabihlmaier.de" + url
    fecha_iso = fecha.isoformat()
    ev_id = generar_id(fecha_iso, ciudad, programa, url)
    return Evento(
        id=ev_id, fecha_iso=fecha_iso, orquesta=orquesta,
        programa=programa, solistas=solistas, sala=sala,
        ciudad=ciudad, url=url,
    )


def cargar_estado() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_sent": None, "events": []}


def guardar_estado(estado: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


@dataclass
class DiffResultado:
    nuevos_ids: set[str] = field(default_factory=set)
    cambiados: dict[str, list[str]] = field(default_factory=dict)
    cancelados: list[dict] = field(default_factory=list)


def calcular_diff(
    eventos_actuales: list[Evento],
    estado_anterior: dict,
) -> DiffResultado:
    resultado = DiffResultado()
    eventos_previos = estado_anterior.get("events", [])
    es_primera = estado_anterior.get("last_sent") is None
    previos_por_id: dict[str, dict] = {}
    for ev in eventos_previos:
        previos_por_id[ev["id"]] = ev
    ids_actuales = {ev.id for ev in eventos_actuales}
    hoy = datetime.now(MADRID_TZ).date()
    if es_primera:
        return resultado
    for ev in eventos_actuales:
        if ev.id not in previos_por_id:
            resultado.nuevos_ids.add(ev.id)
        else:
            anterior = previos_por_id[ev.id]
            cambios = []
            for campo in CAMPOS_COMPARABLES:
                val_ant = anterior.get(campo, "")
                val_nuevo = getattr(ev, campo, "")
                if isinstance(val_nuevo, date):
                    val_nuevo = val_nuevo.isoformat()
                if val_ant != val_nuevo:
                    if campo == "date":
                        txt_ant = fecha_alemana_iso(val_ant) if val_ant else "(leer)"
                        txt_nuevo = fecha_alemana_iso(val_nuevo) if val_nuevo else "(leer)"
                    else:
                        txt_ant = val_ant or "(leer)"
                        txt_nuevo = val_nuevo or "(leer)"
                    cambios.append(
                        f"{ETIQUETAS_CAMPOS[campo]}: {txt_ant} → {txt_nuevo}"
                    )
            if cambios:
                resultado.cambiados[ev.id] = cambios
    for ev in eventos_previos:
        ev_id = ev["id"]
        if ev_id not in ids_actuales:
            try:
                fecha_ev = date.fromisoformat(ev["date"])
                if fecha_ev >= hoy:
                    resultado.cancelados.append(ev)
            except (ValueError, KeyError):
                resultado.cancelados.append(ev)
    return resultado
def _esc_html(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_evento_html(ev, diff, hoy, es_primera, compacto=False):
    bandera = obtener_bandera(ev.ciudad, ev.texto_completo)
    fecha_str = fecha_alemana(ev.fecha_date)
    dias = (ev.fecha_date - hoy).days
    prox_texto = texto_proximidad(dias)
    padding = "10px 14px" if compacto else "16px"
    margin = "0 0 6px 0" if compacto else "0 0 12px 0"
    font_titulo = "15px" if compacto else "17px"
    font_orq = "14px" if compacto else "15px"
    p = []
    p.append(f'<div style="margin:{margin};padding:{padding};background:#fafafa;border-radius:8px;border:1px solid #eee;">')
    p.append(f'<p style="margin:0 0 4px 0;font-size:{font_titulo};font-weight:bold;">{bandera} {fecha_str}</p>')
    if ev.orquesta:
        p.append(f'<p style="margin:0 0 2px 0;font-size:{font_orq};font-weight:bold;color:#222;">{_esc_html(ev.orquesta)}</p>')
    if ev.programa:
        p.append(f'<p style="margin:0 0 2px 0;font-size:14px;color:#555;">{_esc_html(ev.programa)}</p>')
    if ev.solistas:
        p.append(f'<p style="margin:0 0 2px 0;font-size:14px;color:#555;">{_esc_html(ev.solistas)}</p>')
    ubicacion = ", ".join(filter(None, [ev.sala, ev.ciudad]))
    if ubicacion:
        p.append(f'<p style="margin:0 0 8px 0;font-size:14px;">📍 {_esc_html(ubicacion)}</p>')
    badges = []
    if not es_primera and ev.id in diff.nuevos_ids:
        badges.append('<span style="display:inline-block;background:#fff3cd;color:#856404;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;margin-right:4px;">🆕 NEU</span>')
    if not es_primera and ev.id in diff.cambiados:
        badges.append('<span style="display:inline-block;background:#f8d7da;color:#721c24;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;margin-right:4px;">⚠️ GEÄNDERT</span>')
    if prox_texto:
        badges.append(f'<span style="display:inline-block;background:#d1ecf1;color:#0c5460;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;margin-right:4px;">⏰ {_esc_html(prox_texto)}</span>')
    if badges:
        p.append(f'<p style="margin:0;">{"".join(badges)}</p>')
    if not es_primera and ev.id in diff.cambiados:
        cambios_html = "<br>".join(_esc_html(c) for c in diff.cambiados[ev.id])
        p.append(f'<p style="margin:4px 0 0 0;font-size:12px;color:#721c24;font-style:italic;">Änderung: {cambios_html}</p>')
    p.append("</div>")
    return "\n".join(p)


def _render_evento_texto(ev, diff, hoy, es_primera):
    bandera = obtener_bandera(ev.ciudad, ev.texto_completo)
    fecha_str = fecha_alemana(ev.fecha_date)
    dias = (ev.fecha_date - hoy).days
    prox_texto = texto_proximidad(dias)
    lineas = [f"  {bandera} {fecha_str}"]
    if ev.orquesta:
        lineas.append(f"  {ev.orquesta}")
    if ev.programa:
        lineas.append(f"  {ev.programa}")
    if ev.solistas:
        lineas.append(f"  {ev.solistas}")
    ubicacion = ", ".join(filter(None, [ev.sala, ev.ciudad]))
    if ubicacion:
        lineas.append(f"  📍 {ubicacion}")
    etiquetas = []
    if not es_primera and ev.id in diff.nuevos_ids:
        etiquetas.append("🆕 NEU")
    if not es_primera and ev.id in diff.cambiados:
        etiquetas.append("⚠️ GEÄNDERT")
    if prox_texto:
        etiquetas.append(f"⏰ {prox_texto}")
    if etiquetas:
        lineas.append(f"  [{' · '.join(etiquetas)}]")
    if not es_primera and ev.id in diff.cambiados:
        for cambio in diff.cambiados[ev.id]:
            lineas.append(f"    → {cambio}")
    return "\n".join(lineas)


def renderizar_email(eventos, diff, es_primera):
    hoy = datetime.now(MADRID_TZ).date()
    n_nuevos = len(diff.nuevos_ids) if not es_primera else 0
    n_proximos = sum(1 for ev in eventos if 0 <= (ev.fecha_date - hoy).days <= DIAS_UMBRAL_PROXIMOS)
    n_cambiados = len(diff.cambiados)
    n_cancelados = len(diff.cancelados)
    partes = []
    if n_nuevos > 0:
        partes.append(f"{n_nuevos} neue Termine 🆕")
    if n_proximos > 0:
        partes.append(f"{n_proximos} stehen bald bevor ⏰")
    if n_cambiados > 0:
        partes.append(f"{n_cambiados} Änderungen ⚠️")
    if n_cancelados > 0:
        partes.append(f"{n_cancelados} evtl. abgesagt ❌")
    linea_resumen = "Diese Woche: " + " · ".join(partes) if partes else "Diese Woche: Keine Änderungen."
    if n_nuevos > 0:
        asunto = f"🎼 Anja Bihlmaier · {n_nuevos} neue Termine diese Woche"
    else:
        asunto = "🎼 Anja Bihlmaier · Diese Woche keine neuen Termine"
    eventos_espana = [ev for ev in eventos if es_espana(ev.ciudad, ev.texto_completo)]
    # HTML
    h = []
    h.append('<div style="max-width:600px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#333;line-height:1.6;">')
    h.append('<p style="font-size:16px;margin:0 0 8px 0;">Liebe Elisabeth,</p>')
    h.append('<p style="font-size:16px;margin:0 0 16px 0;">hier ist dein wöchentlicher Überblick über die Konzerte deiner Nichte Anja 🎻</p>')
    h.append(f'<p style="font-size:15px;margin:0 0 20px 0;padding:12px 16px;background:#f0f4ff;border-radius:8px;border-left:4px solid #4a6fa5;">{linea_resumen}</p>')
    eventos_lista = eventos[:MAX_EVENTOS_LISTA]
    for ev in eventos_lista:
        h.append(_render_evento_html(ev, diff, hoy, es_primera))
    if len(eventos) > MAX_EVENTOS_LISTA:
        restantes = len(eventos) - MAX_EVENTOS_LISTA
        h.append(f'<p style="font-size:14px;color:#666;margin:8px 0 20px 0;">… und {restantes} weitere Termine <a href="{URL_CALENDARIO}" style="color:#4a6fa5;">Vollständiger Kalender</a></p>')
    elif not eventos:
        h.append('<p style="font-size:15px;color:#666;margin:0 0 20px 0;">Zurzeit keine kommenden Konzerte.</p>')
    if diff.cancelados:
        h.append('<p style="font-size:16px;font-weight:bold;margin:20px 0 8px 0;color:#721c24;">❌ Möglicherweise abgesagt</p>')
        for ev_c in diff.cancelados:
            fs = ev_c.get("date", "")
            if fs:
                try: fs = fecha_alemana_iso(fs)
                except ValueError: pass
            orq = ev_c.get("orchestra", "")
            ciu = ev_c.get("city", "")
            sal = ev_c.get("venue", "")
            ubi = f"{sal}, {ciu}".strip(", ")
            h.append(f'<div style="margin:0 0 8px 0;padding:10px 14px;background:#f8d7da;border-radius:6px;font-size:14px;"><span style="font-weight:bold;">{fs}</span>{f" · {orq}" if orq else ""}{f"<br>{ubi}" if ubi else ""}</div>')
    h.append('<p style="font-size:16px;font-weight:bold;margin:24px 0 8px 0;color:#333;">Konzerte in Spanien 🇪🇸</p>')
    if eventos_espana:
        for ev in eventos_espana:
            h.append(_render_evento_html(ev, diff, hoy, es_primera, compacto=True))
    else:
        h.append('<p style="font-size:14px;color:#888;margin:0 0 20px 0;">Zurzeit keine Konzerte in Spanien.</p>')
    h.append('<hr style="border:none;border-top:1px solid #ddd;margin:24px 0 12px 0;">')
    h.append(f'<p style="font-size:13px;color:#888;margin:0 0 4px 0;"><a href="{URL_CALENDARIO}" style="color:#4a6fa5;">Vollständiger Kalender</a></p>')
    h.append('<p style="font-size:13px;color:#888;margin:0 0 16px 0;">Diese Übersicht kommt jeden Sonntag um 10:00 Uhr automatisch.</p>')
    h.append('<p style="font-size:15px;margin:0;">Viele Grüße, dein Kalender-Roboter 🤖</p>')
    h.append('</div>')
    html_completo = "\n".join(h)
    # TEXTO
    t = []
    t.append("Liebe Elisabeth,")
    t.append("")
    t.append("hier ist dein wöchentlicher Überblick über die Konzerte deiner Nichte Anja 🎻")
    t.append("")
    t.append(linea_resumen)
    t.append("")
    t.append("━" * 50)
    for ev in eventos_lista:
        t.append(_render_evento_texto(ev, diff, hoy, es_primera))
        t.append("━" * 50)
    if len(eventos) > MAX_EVENTOS_LISTA:
        restantes = len(eventos) - MAX_EVENTOS_LISTA
        t.append(f"… und {restantes} weitere Termine: {URL_CALENDARIO}")
        t.append("━" * 50)
    elif not eventos:
        t.append("Zurzeit keine kommenden Konzerte.")
        t.append("━" * 50)
    if diff.cancelados:
        t.append("")
        t.append("❌ Möglicherweise abgesagt")
        t.append("━" * 50)
        for ev_c in diff.cancelados:
            fs = ev_c.get("date", "")
            if fs:
                try: fs = fecha_alemana_iso(fs)
                except ValueError: pass
            orq = ev_c.get("orchestra", "")
            ciu = ev_c.get("city", "")
            sal = ev_c.get("venue", "")
            ubi = f"{sal}, {ciu}".strip(", ")
            t.append(f"  {fs}{f' · {orq}' if orq else ''}")
            if ubi: t.append(f"  {ubi}")
            t.append("━" * 50)
    t.append("")
    t.append("Konzerte in Spanien 🇪🇸")
    t.append("━" * 50)
    if eventos_espana:
        for ev in eventos_espana:
            t.append(_render_evento_texto(ev, diff, hoy, es_primera))
            t.append("━" * 50)
    else:
        t.append("Zurzeit keine Konzerte in Spanien.")
        t.append("━" * 50)
    t.append("")
    t.append(f"Vollständiger Kalender: {URL_CALENDARIO}")
    t.append("Diese Übersicht kommt jeden Sonntag um 10:00 Uhr automatisch.")
    t.append("")
    t.append("Viele Grüße, dein Kalender-Roboter 🤖")
    texto_completo = "\n".join(t)
    return html_completo, texto_completo, asunto


def enviar_email(asunto, html, texto, smtp_user, smtp_pass, email_to, email_cc=""):
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr(("Kalender-Roboter 🤖", smtp_user))
    dests_to = [e.strip() for e in email_to.split(",") if e.strip()]
    msg["To"] = ", ".join(dests_to)
    dests_cc = [e.strip() for e in email_cc.split(",") if e.strip()]
    if dests_cc:
        msg["Cc"] = ", ".join(dests_cc)
    msg.set_content(texto, charset="utf-8")
    msg.add_alternative(html, subtype="html", charset="utf-8")
    contexto = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=contexto) as servidor:
        servidor.login(smtp_user, smtp_pass)
        servidor.sendmail(smtp_user, dests_to + dests_cc, msg.as_string())
    print(f"Email enviado a {', '.join(dests_to)}" + (f" (CC: {', '.join(dests_cc)})" if dests_cc else ""))

def enviar_email_error(error, smtp_user, smtp_pass, email_cc):
    dests_cc = [e.strip() for e in email_cc.split(",") if e.strip()]
    if not dests_cc:
        return
    asunto = "⚠️ Fehler beim Abrufen des Anja-Bihlmaier-Kalenders"
    texto = f"Es ist ein Fehler aufgetreten beim Scraping des Kalenders:\n\n{error}\n\nBitte prüfe die GitHub Actions Logs."
    html = f'<div style="font-family:Arial,sans-serif;color:#333;max-width:600px;"><h2 style="color:#721c24;">⚠️ Fehler beim Kalender-Scraping</h2><pre style="background:#f8d7da;padding:12px;border-radius:6px;font-size:13px;">{_esc_html(error)}</pre></div>'
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr(("Kalender-Roboter 🤖", smtp_user))
    msg["To"] = dests_cc[0]
    if len(dests_cc) > 1:
        msg["Cc"] = ", ".join(dests_cc[1:])
    msg.set_content(texto, charset="utf-8")
    msg.add_alternative(html, subtype="html", charset="utf-8")
    contexto = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=contexto) as servidor:
        servidor.login(smtp_user, smtp_pass)
        servidor.sendmail(smtp_user, dests_cc, msg.as_string())

def main():
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    email_to = os.environ.get("EMAIL_TO", "")
    email_cc = os.environ.get("EMAIL_CC", "").strip()
    if not smtp_user or not smtp_pass or not email_to:
        raise ValueError("Faltan variables de entorno: SMTP_USER, SMTP_PASS, EMAIL_TO")
    estado = cargar_estado()
    es_primera = estado.get("last_sent") is None
    print(f"Estado: {len(estado.get('events', []))} eventos previos" + (" (PRIMERA)" if es_primera else ""))
    print("Scrapeando calendario...")
    eventos = scrape_eventos()
    print(f"Encontrados {len(eventos)} eventos futuros.")
    diff = calcular_diff(eventos, estado)
    print(f"Diff: {len(diff.nuevos_ids)} nuevos, {len(diff.cambiados)} cambiados, {len(diff.cancelados)} cancelados.")
    html, texto, asunto = renderizar_email(eventos, diff, es_primera)
    print("Enviando email...")
    enviar_email(asunto, html, texto, smtp_user, smtp_pass, email_to, email_cc)
    estado["last_sent"] = datetime.now(MADRID_TZ).isoformat()
    estado["events"] = [ev.to_dict() for ev in eventos]
    guardar_estado(estado)
    print("Estado actualizado y guardado.")


def test_parser():
    html_fixture = """
    <div id="aktuell">
      <div class="newsblok">
        <span class="baton2"></span>
        <h3>Sep 01 2026</h3>
        <h4>Los Angeles Philharmonic Orchestra</h4>
        <h5>Gibson, Bruch, Dvorak</h5>
        <h6>Bomsori, violin</h6>
        <p style="font-size:16px;">Hollywood Bowl, Los Angeles</p>
        <p><a href="https://anjabihlmaier.de/kalenderitem/los-angeles-philharmonic-hollywood-bowl/" class="buttonlink">Weitere Informationen</a></p>
      </div>
      <div class="newsblok">
        <span class="baton2"></span>
        <h3>Oct 15 2025</h3>
        <h4>Orquesta Sin&#39;nica de Valencia</h4>
        <p style="font-size:16px;">Palau de la Música, Valencia</p>
        <p><a href="https://anjabihlmaier.de/kalenderitem/valencia/" class="buttonlink">Weitere Informationen</a></p>
      </div>
      <div class="newsblok">
        <span class="baton2"></span>
        <h3>Dec 03 2025</h3>
        <h4>Berliner Philharmoniker</h4>
        <h5>Beethoven, Strauss</h5>
        <p style="font-size:16px;">Philharmonie Berlin</p>
      </div>
    </div>
    """
    soup = BeautifulSoup(html_fixture, "html.parser")
    actualidad = soup.select_one("div#aktuell")
    assert actualidad is not None
    bloques = actualidad.select("div.newsblok")
    assert len(bloques) == 3
    ev1 = _parsear_bloque(bloques[0])
    assert ev1 is not None
    assert ev1.fecha_iso == "2026-09-01"
    assert ev1.orquesta == "Los Angeles Philharmonic Orchestra"
    assert ev1.programa == "Gibson, Bruch, Dvorak"
    assert ev1.solistas == "Bomsori, violin"
    assert ev1.sala == "Hollywood Bowl"
    assert ev1.ciudad == "Los Angeles"
    assert ev1.url == "https://anjabihlmaier.de/kalenderitem/los-angeles-philharmonic-hollywood-bowl/"
    assert ev1.id == ev1.url
    ev2 = _parsear_bloque(bloques[1])
    assert ev2 is not None
    assert ev2.fecha_iso == "2025-10-15"
    assert ev2.orquesta == "Orquesta Sin'nica de Valencia"
    assert ev2.programa == ""
    assert ev2.solistas == ""
    assert ev2.ciudad == "Valencia"
    ev3 = _parsear_bloque(bloques[2])
    assert ev3 is not None
    assert ev3.fecha_iso == "2025-12-03"
    assert ev3.url == ""
    assert ev3.id.startswith("hash:")
    assert ev3.sala == ""
    assert ev3.ciudad == "Philharmonie Berlin"
    assert obtener_bandera("Los Angeles") == "🇺🇸"
    assert obtener_bandera("Valencia") == "🇪🇸"
    assert obtener_bandera("Philharmonie Berlin") == "🌍"
    assert obtener_bandera("Heerlen") == "🇳🇱"
    assert obtener_bandera("Herleen") == "🇳🇱"
    assert obtener_bandera("Ciudad Desconocida") == "🌍"
    assert obtener_bandera("Ciudad X", "concierto en Deutschland") == "🇩🇪"
    assert es_espana("Valencia") is True
    assert es_espana("Madrid") is True
    assert es_espana("alcoi") is True
    assert es_espana("Alcoy") is True
    assert es_espana("Berlin") is False
    assert es_espana("Ciudad X", "concierto en Spanien") is True
    assert es_espana("Ciudad X", "concierto en Deutschland") is False
    assert fecha_alemana(date(2026, 9, 1)) == "Dienstag, 1. September 2026"
    assert fecha_alemana(date(2025, 10, 15)) == "Mittwoch, 15. Oktober 2025"
    assert fecha_alemana(date(2025, 12, 3)) == "Mittwoch, 3. Dezember 2025"
    assert texto_proximidad(0) == "heute"
    assert texto_proximidad(1) == "morgen"
    assert texto_proximidad(5) == "in 5 Tagen"
    assert texto_proximidad(7) == "in 7 Tagen"
    assert texto_proximidad(8) is None
    assert texto_proximidad(-1) is None
    print("✅ Todos los tests del parser PASARON.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_parser()
        sys.exit(0)
    try:
        main()
    except Exception as e:
        error_detail = traceback.format_exc()
        print(f"ERROR: {error_detail}", file=sys.stderr)
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")
        email_cc = os.environ.get("EMAIL_CC", "").strip()
        if smtp_user and smtp_pass and email_cc:
            try:
                enviar_email_error(error_detail, smtp_user, smtp_pass, email_cc)
            except Exception:
                pass
        sys.exit(1)
