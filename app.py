from flask import Flask, render_template, request, jsonify
import requests
import json
from geopy.geocoders import Nominatim
import datetime
import math
import pdfkit
import xml.etree.ElementTree as ET
from flask import Response

app = Flask(__name__)

OPENAI_KEY = 'xxxxxxxxxxxxxxxx'
ORS_API_KEY = 'xxxxxxxxxxxxxxxxxxxxx'

# Emoji-Zuordnungen
EMOJI_MAP = {
    "jacke": "🧥", "regenjacke": "☔", "sonnenbrille": "🕶️", "wanderschuhe": "🥾",
    "mütze": "🧢", "rucksack": "🎒", "trinkflasche": "🚰", "handschuhe": "🧤",
    "schal": "🧣", "socken": "🧦", "t-shirt": "👕", "shirt": "👕", "hose": "👖",
    "kurze hose": "🩳", "lange hose": "👖", "hut": "👒", "cap": "🧢",
    "windbreaker": "🌬️", "sonnenschutz": "🧴", "schuhe": "👟"
}

def enrich_with_emojis(text):
    for wort, emoji in EMOJI_MAP.items():
        text = text.replace(wort, f"{wort} {emoji}")
    return text

def extract_packlist(text):
    schlüsselwörter = list(EMOJI_MAP.keys()) + ["stirnlampe", "wasser"]
    gefunden = set()
    for zeile in text.lower().splitlines():
        for wort in schlüsselwörter:
            if wort in zeile:
                gefunden.add(wort)
    return list(gefunden)

def get_coords(city):
    geolocator = Nominatim(user_agent="tourwaer", timeout=5)  # oder 10

    location = geolocator.geocode(city)
    if not location:
        return None
    return location.latitude, location.longitude

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(d_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_weather(city):
    coords = get_coords(city)
    if not coords:
        return "unbekannt"
    lat, lon = coords
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&timezone=auto&start_date={date}&end_date={date}"
    )
    res = requests.get(url)
    data = res.json()
    try:
        t_min = data["daily"]["temperature_2m_min"][0]
        t_max = data["daily"]["temperature_2m_max"][0]
        return f"zwischen {t_min} °C und {t_max} °C"
    except:
        return "nicht verfügbar"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/export")
def export():
    start = request.args.get("start")
    ziel = request.args.get("ziel")
    modus = request.args.get("modus", "wandern")
    zusatz = request.args.get("frage", "")

    if not start or not ziel:
        return "Fehlende Parameter", 400

    wetter_start = get_weather(start)
    wetter_ziel = get_weather(ziel)
    coords1 = get_coords(start)
    coords2 = get_coords(ziel)
    if not coords1 or not coords2:
        return "Koordinatenfehler", 400

    distanz = haversine_distance(*coords1, *coords2)
    geschw = 4 if modus == "wandern" else 15
    dauer = round(distanz / geschw, 2)

    prompt = (
        f"Ein Nutzer plant eine Tour von {start} nach {ziel} mit dem {modus}. "
        f"Die Tour dauert etwa {dauer} Stunden. "
        f"Das Wetter ist am Startort {wetter_start}, am Zielort {wetter_ziel}. "
        f"{'Zusatzfrage: ' + zusatz if zusatz else ''} "
        f"Gib wetter- und aktivitätsbezogene Kleidungsempfehlungen."
    )

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        },
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]}
    )

    antwort = res.json()["choices"][0]["message"]["content"]
    antwort = enrich_with_emojis(antwort)
    packliste = extract_packlist(antwort)

    html = render_template("export.html",
        start=start, ziel=ziel,
        wetter_start=wetter_start, wetter_ziel=wetter_ziel,
        dauer=dauer, modus=modus,
        antwort=antwort, packliste=packliste
    )

    config = pdfkit.configuration(wkhtmltopdf=r"E:\Programme\wkhtmltopdf\bin\wkhtmltopdf.exe")  # Nur nötig wenn nicht im Systempfad
    pdf = pdfkit.from_string(html, False, configuration=config)

    return (pdf, 200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": f"attachment; filename=TourWaer_{start}_nach_{ziel}.pdf"
    })


@app.route("/frage", methods=["POST"])
def frage():
    daten = request.json
    start = daten.get("start")
    ziel = daten.get("ziel")
    modus = daten.get("modus", "wandern")
    zusatz = daten.get("frage", "")

    wetter_start = get_weather(start)
    wetter_ziel = get_weather(ziel)

    coords1 = get_coords(start)
    coords2 = get_coords(ziel)
    if not coords1 or not coords2:
        return jsonify({"antwort": "Start/Ziel nicht gefunden", "packliste": [], "dauer": "?"})

    distanz = haversine_distance(*coords1, *coords2)
    geschw = 4 if modus == "wandern" else 15
    dauer = round(distanz / geschw, 2)

    prompt = (
        f"Ein Nutzer plant eine Tour von {start} nach {ziel}, mit dem {modus}. "
        f"Die Tour dauert etwa {dauer} Stunden. "
        f"Das Wetter ist am Startort {wetter_start}, am Zielort {wetter_ziel}. "
        f"{'Zusatzfrage: ' + zusatz if zusatz else ''} "
        f"Gib wetter- und aktivitätsbezogene Kleidungsempfehlungen."
    )

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}]
        }
    )

    antwort_json = res.json()
    if "choices" in antwort_json:
        content = antwort_json["choices"][0]["message"]["content"]
        content = enrich_with_emojis(content.lower())
        packliste = extract_packlist(content)
    else:
        content = "Fehler bei der GPT-Antwort"
        packliste = []

    return jsonify({
        "antwort": content,
        "packliste": sorted(packliste),
        "wetter_start": wetter_start,
        "wetter_ziel": wetter_ziel,
        "dauer": dauer
    })

@app.route("/route", methods=["POST"])
def route():
    daten = request.json
    start = daten.get("start")
    ziel = daten.get("ziel")

    coords1 = get_coords(start)
    coords2 = get_coords(ziel)
    if not coords1 or not coords2:
        return jsonify({"fehler": "Koordinaten nicht gefunden"}), 400

    route_res = requests.post(
        "https://api.openrouteservice.org/v2/directions/foot-hiking/geojson",
        headers={"Authorization": ORS_API_KEY},
        json={
            "coordinates": [[coords1[1], coords1[0]], [coords2[1], coords2[0]]],
            "elevation": True
        }
    )
    route_data = route_res.json()
    try:
        linie = route_data["features"][0]["geometry"]["coordinates"]
        latlngs = [{"lat": p[1], "lon": p[0], "ele": p[2]} for p in linie if len(p) >= 3]
    except:
        latlngs = []

    return jsonify({"punkte": latlngs})

@app.route("/gpx", methods=["POST"])
def gpx():
    daten = request.json
    start = daten.get("start")
    ziel  = daten.get("ziel")

    coords1 = get_coords(start)
    coords2 = get_coords(ziel)
    if not coords1 or not coords2:
        return "Fehler: Orte nicht gefunden", 400

    # OpenRouteService-Routenabfrage
    route_res = requests.post(
        "https://api.openrouteservice.org/v2/directions/foot-hiking/geojson",
        headers={"Authorization": ORS_API_KEY},
        json={
            "coordinates": [[coords1[1], coords1[0]], [coords2[1], coords2[0]]],
            "elevation": True
        }
    )
    data = route_res.json()
    punkte = data["features"][0]["geometry"]["coordinates"]

    # GPX aufbauen
    gpx = ET.Element("gpx", version="1.1", creator="TourWaer", xmlns="http://www.topografix.com/GPX/1/1")
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = f"{start} nach {ziel}"
    trkseg = ET.SubElement(trk, "trkseg")

    for p in punkte:
        trkpt = ET.SubElement(trkseg, "trkpt", lat=str(p[1]), lon=str(p[0]))
        if len(p) == 3:
            ET.SubElement(trkpt, "ele").text = str(p[2])

    xml = ET.tostring(gpx, encoding="utf-8", method="xml")
    return Response(xml, mimetype="application/gpx+xml",
                    headers={"Content-Disposition": f"attachment; filename={start}_{ziel}.gpx"})

@app.route("/pois", methods=["POST"])
def pois():
    daten = request.json
    start = daten.get("start")
    ziel = daten.get("ziel")
    radius = daten.get("distanz", 100)  # Umkreis in Metern

    coords1 = get_coords(start)
    coords2 = get_coords(ziel)
    if not coords1 or not coords2:
        return jsonify({"fehler": "Koordinatenfehler"}), 400

    # Route abfragen
    route_res = requests.post(
        "https://api.openrouteservice.org/v2/directions/foot-hiking/geojson",
        headers={"Authorization": ORS_API_KEY},
        json={
            "coordinates": [[coords1[1], coords1[0]], [coords2[1], coords2[0]]],
            "elevation": False
        }
    )
    route_data = route_res.json()
    punkte = route_data["features"][0]["geometry"]["coordinates"]

    # Overpass-Query um jeden Punkt
    around_snippets = []
    for p in punkte[::max(1, len(punkte)//30)]:  # max. 30 Punkte zur Begrenzung
        lat, lon = p[1], p[0]
        around_snippets.append(f"""
          node(around:{radius},{lat},{lon})["amenity"="drinking_water"];
          node(around:{radius},{lat},{lon})["tourism"="picnic_site"];
          node(around:{radius},{lat},{lon})["building"="hut"];
          node(around:{radius},{lat},{lon})["amenity"="toilets"];
        """)

    overpass_query = f"""
    [out:json][timeout:25];
    (
        {''.join(around_snippets)}
    );
    out body;
    """

    res = requests.post("https://overpass-api.de/api/interpreter", data=overpass_query)
    data = res.json()

    pois = []
    for el in data.get("elements", []):
        pois.append({
            "lat": el["lat"],
            "lon": el["lon"],
            "type": el.get("tags", {}).get("amenity") or el.get("tags", {}).get("tourism") or el.get("tags", {}).get("building") or "POI",
            "name": el.get("tags", {}).get("name", "")
        })

    return jsonify(pois)

