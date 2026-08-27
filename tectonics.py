import numpy as np
import pandas as pd
from geopy.distance import geodesic

# Coordenadas maestras aproximadas del eje de la Fosa de Perú-Chile (Trinchera oceánica)
FOSA_PERU_CHILE = [
    (-3.50, -81.80),
    (-6.00, -81.50),
    (-9.00, -80.50),
    (-12.00, -78.80),
    (-14.50, -77.20),
    (-16.50, -74.50),
    (-18.50, -72.00),
    (-20.50, -71.50)
]

def calcular_distancia_fosa_km(lat, lon):
    """Calcula la distancia mínima en km desde el epicentro al eje de subducción."""
    min_dist = float("inf")
    for punto_fosa in FOSA_PERU_CHILE:
        d = geodesic((lat, lon), punto_fosa).kilometers
        if d < min_dist:
            min_dist = d
    return round(min_dist, 1)

def identificar_secuencias_sismicas(df, ventana_dias=7, radio_km=100.0):
    """
    Agrupa eventos sísmicos en enjambres/secuencias (Mainshock vs Réplicas).
    """
    if df.empty:
        return df
        
    df_temp = df.copy()
    df_temp["fecha_dt"] = pd.to_datetime(df_temp["fecha_hora"], errors="coerce")
    df_temp = df_temp.sort_values(by="fecha_dt", ascending=False).reset_index(drop=True)
    
    df_temp["rol_evento"] = "Evento Aislado"
    df_temp["id_secuencia"] = "None"
    
    # Identificar sismos principales (M >= 5.5)
    principales = df_temp[df_temp["magnitud"] >= 5.5]
    
    secuencia_id = 1
    for idx_p, s_prin in principales.iterrows():
        t_prin = s_prin["fecha_dt"]
        coords_prin = (s_prin["latitud"], s_prin["longitud"])
        
        # Buscar réplicas posteriores en el tiempo y cercanas en radio
        condicion = (
            (df_temp["fecha_dt"] >= t_prin) &
            (df_temp["fecha_dt"] <= t_prin + pd.Timedelta(days=ventana_dias)) &
            (df_temp.index != idx_p)
        )
        
        candidatos = df_temp[condicion]
        replicas_idx = []
        for idx_c, cand in candidatos.iterrows():
            d = geodesic(coords_prin, (cand["latitud"], cand["longitud"])).kilometers
            if d <= radio_km:
                replicas_idx.append(idx_c)
                
        if replicas_idx:
            df_temp.loc[idx_p, "rol_evento"] = "Sismo Principal (Mainshock)"
            df_temp.loc[idx_p, "id_secuencia"] = f"SEC-{secuencia_id}"
            df_temp.loc[replicas_idx, "rol_evento"] = "Réplica (Aftershock)"
            df_temp.loc[replicas_idx, "id_secuencia"] = f"SEC-{secuencia_id}"
            secuencia_id += 1
            
    return df_temp