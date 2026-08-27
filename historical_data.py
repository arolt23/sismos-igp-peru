import requests
import pandas as pd
from datetime import datetime

# Catálogo de terremotos históricos con alto impacto en poblaciones
SISMOS_DESTRUCTIVOS_HISTORICOS = [
    {"fecha_hora": "1970-05-31 15:23", "anio": 1970, "latitud": -9.18, "longitud": -78.83, "profundidad_km": 45.0, "magnitud": 7.9, "referencia": "Ancash / Yungay", "departamento": "Ancash", "impacto": "Catastrófico (Aluvión en Yungay, ~70k fallecidos)", "fuente": "Registro Histórico"},
    {"fecha_hora": "1974-10-03 09:21", "anio": 1974, "latitud": -12.30, "longitud": -77.60, "profundidad_km": 30.0, "magnitud": 8.1, "referencia": "Costa Central / Lima", "departamento": "Lima", "impacto": "Muy Severo (Daños en Callao, Lima y Cañete)", "fuente": "Registro Histórico"},
    {"fecha_hora": "1996-11-12 11:59", "anio": 1996, "latitud": -15.00, "longitud": -75.63, "profundidad_km": 33.0, "magnitud": 7.7, "referencia": "Nazca / Ica", "departamento": "Ica", "impacto": "Severo (Destrucción en Nazca y Palpa)", "fuente": "Registro Histórico"},
    {"fecha_hora": "2001-06-23 15:33", "anio": 2001, "latitud": -16.26, "longitud": -73.64, "profundidad_km": 33.0, "magnitud": 8.4, "referencia": "Arequipa / Camaná", "departamento": "Arequipa", "impacto": "Catastrófico (Tsunami en Camaná, daños Moquegua/Tacna)", "fuente": "Registro Histórico"},
    {"fecha_hora": "2007-08-15 18:40", "anio": 2007, "latitud": -13.35, "longitud": -76.51, "profundidad_km": 39.0, "magnitud": 8.0, "referencia": "Pisco / Ica", "departamento": "Ica", "impacto": "Catastrófico (Devastación en Pisco, Chincha e Ica)", "fuente": "Registro Histórico"},
    {"fecha_hora": "2019-05-26 02:41", "anio": 2019, "latitud": -5.81, "longitud": -75.27, "profundidad_km": 122.0, "magnitud": 8.0, "referencia": "Alto Amazonas / Loreto", "departamento": "Loreto", "impacto": "Moderado a Severo (Sismo intraplaca profundo)", "fuente": "Registro Histórico"}
]

def obtener_historico_peru(start_year=2000, min_mag=4.5):
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "format": "geojson",
        "starttime": f"{start_year}-01-01",
        "minmagnitude": min_mag,
        "minlatitude": -18.5,
        "maxlatitude": 0.0,
        "minlongitude": -82.0,
        "maxlongitude": -68.0,
        "limit": 2500
    }
    
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code != 200:
            return pd.DataFrame(SISMOS_DESTRUCTIVOS_HISTORICOS)
            
        geojson = res.json()
        registros = []
        
        for feature in geojson.get("features", []):
            prop = feature["properties"]
            geom = feature["geometry"]["coordinates"]
            fecha = datetime.utcfromtimestamp(prop["time"] / 1000.0)
            
            place_text = prop.get("place", "Perú")
            registros.append({
                "fecha_hora": fecha.strftime("%Y-%m-%d %H:%M"),
                "anio": fecha.year,
                "latitud": geom[1],
                "longitud": geom[0],
                "profundidad_km": geom[2],
                "magnitud": prop["mag"],
                "referencia": place_text,
                "impacto": "Registro Instrumental",
                "fuente": "USGS Histórico"
            })
            
        df_api = pd.DataFrame(registros)
        df_hist = pd.DataFrame(SISMOS_DESTRUCTIVOS_HISTORICOS)
        return pd.concat([df_hist, df_api], ignore_index=True)
        
    except Exception:
        return pd.DataFrame(SISMOS_DESTRUCTIVOS_HISTORICOS)