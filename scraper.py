import requests
import xml.etree.ElementTree as ET
import pandas as pd
import re

IGP_RSS_URL = "https://ultimosismo.igp.gob.pe/rss/sismos"

def parsear_contenido_igp(texto_item):
    """Extrae magnitud, profundidad, latitud y longitud del formato de texto del IGP."""
    profundidad = None
    magnitud = None
    referencia = "Perú"
    
    # Búsqueda por expresiones regulares
    match_prof = re.search(r'Profundidad:\s*([\d\.]+)\s*km', texto_item, re.IGNORECASE)
    match_mag = re.search(r'Magnitud:\s*([\d\.]+)', texto_item, re.IGNORECASE)
    match_ref = re.search(r'Referencia:\s*([^<]+)', texto_item, re.IGNORECASE)
    
    if match_prof:
        profundidad = float(match_prof.group(1))
    if match_mag:
        magnitud = float(match_mag.group(1))
    if match_ref:
        referencia = match_ref.group(1).strip()
        
    return magnitud, profundidad, referencia

def obtener_sismos_en_vivo():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(IGP_RSS_URL, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return pd.DataFrame()

        root = ET.fromstring(response.content)
        sismos = []

        # El feed RSS de IGP usa etiquetas GeoRSS para coordenadas
        namespaces = {
            'geo': 'http://www.w3.org/2003/01/geo/wgs84_pos#',
            'georss': 'http://www.georss.org/georss'
        }

        for item in root.findall('.//item'):
            titulo = item.find('title').text if item.find('title') is not None else ""
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            desc = item.find('description').text if item.find('description') is not None else ""
            
            # Coordenadas
            lat_elem = item.find('geo:lat', namespaces)
            lon_elem = item.find('geo:long', namespaces)
            
            lat = float(lat_elem.text) if lat_elem is not None else None
            lon = float(lon_elem.text) if lon_elem is not None else None
            
            mag, prof, ref = parsear_contenido_igp(desc + " " + titulo)
            
            if lat is not None and lon is not None:
                sismos.append({
                    "fecha_hora": pub_date,
                    "latitud": lat,
                    "longitud": lon,
                    "magnitud": mag if mag else 4.0,
                    "profundidad_km": prof if prof else 30.0,
                    "referencia": ref
                })

        df = pd.DataFrame(sismos)
        return df

    except Exception:
        return pd.DataFrame()