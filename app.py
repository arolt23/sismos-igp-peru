import streamlit as st
import pandas as pd
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.express as px
import json
from geopy.distance import geodesic
from scraper import obtener_sismos_en_vivo
from historical_data import obtener_historico_peru
from analysis import calcular_energia_joules, estimar_radio_percepcion_km, clasificar_alerta_riesgo
from tectonics import FOSA_PERU_CHILE, calcular_distancia_fosa_km, identificar_secuencias_sismicas

st.set_page_config(page_title="Monitor Geofísico & Tectónico Perú - IGP", layout="wide")

UBICACIONES_PERU = {
    "Lima": {"provincia": "Lima", "coords": (-12.0464, -77.0428)},
    "Arequipa": {"provincia": "Arequipa", "coords": (-16.4090, -71.5375)},
    "Ica": {"provincia": "Ica", "coords": (-14.0678, -75.7286)},
    "Ancash": {"provincia": "Huaraz", "coords": (-9.5278, -77.5278)},
    "Cusco": {"provincia": "Cusco", "coords": (-13.5319, -71.9675)},
    "La Libertad": {"provincia": "Trujillo", "coords": (-8.1116, -79.0286)},
    "Piura": {"provincia": "Piura", "coords": (-5.1945, -80.6328)},
    "Tacna": {"provincia": "Tacna", "coords": (-18.0146, -70.2536)},
    "Moquegua": {"provincia": "Mariscal Nieto", "coords": (-17.1933, -70.9356)},
    "Junín": {"provincia": "Huancayo", "coords": (-12.0651, -75.2049)},
    "Loreto": {"provincia": "Maynas", "coords": (-3.7491, -73.2538)},
    "Puno": {"provincia": "Puno", "coords": (-15.8422, -70.0199)}
}

def asignar_ubicacion_administrativa(lat, lon):
    min_dist = float("inf")
    dep_cercano = "Costa / Mar"
    prov_cercana = "Litoral"
    for dep, data in UBICACIONES_PERU.items():
        dist = geodesic((lat, lon), data["coords"]).kilometers
        if dist < min_dist:
            min_dist = dist
            dep_cercano = dep
            prov_cercana = data["provincia"]
    return dep_cercano, prov_cercana, round(min_dist, 1)

@st.cache_data(ttl=300)
def preparar_master_dataset():
    df_live = obtener_sismos_en_vivo()
    if not df_live.empty:
        df_live["fuente"] = "IGP (Tiempo Real)"
        df_live["impacto"] = "Monitoreo Instrumental"
        df_live["anio"] = pd.to_datetime(df_live["fecha_hora"], errors="coerce").dt.year.fillna(2026).astype(int)
    
    df_hist = obtener_historico_peru(start_year=1970, min_mag=4.0)
    df_total = pd.concat([df_live, df_hist], ignore_index=True)
    df_total = df_total.drop_duplicates(subset=["latitud", "longitud", "magnitud", "fecha_hora"])
    
    deps, provs, dists, energias, radios, alertas, dist_fosas = [], [], [], [], [], [], []
    for _, row in df_total.iterrows():
        d, p, dist = asignar_ubicacion_administrativa(row["latitud"], row["longitud"])
        deps.append(row.get("departamento", d) if pd.notna(row.get("departamento")) else d)
        provs.append(p)
        dists.append(dist)
        
        _, tnt = calcular_energia_joules(row["magnitud"])
        energias.append(round(tnt, 2))
        
        radio = estimar_radio_percepcion_km(row["magnitud"], row["profundidad_km"])
        radios.append(radio)
        
        alerta = clasificar_alerta_riesgo(row["magnitud"], dist, row["profundidad_km"])
        alertas.append(alerta)
        
        d_fosa = calcular_distancia_fosa_km(row["latitud"], row["longitud"])
        dist_fosas.append(d_fosa)
        
    df_total["departamento"] = deps
    df_total["provincia_cercana"] = provs
    df_total["distancia_poblado_km"] = dists
    df_total["energia_tnt_ton"] = energias
    df_total["radio_afectacion_km"] = radios
    df_total["nivel_riesgo"] = alertas
    df_total["distancia_fosa_km"] = dist_fosas
    
    def clasificar_prof(p):
        if p <= 60: return "Superficial (0-60 km)"
        elif p <= 300: return "Intermedio (61-300 km)"
        return "Profundo (>300 km)"
        
    df_total["tipo_profundidad"] = df_total["profundidad_km"].apply(clasificar_prof)
    
    # Análisis de secuencias
    df_total = identificar_secuencias_sismicas(df_total)
    return df_total

df_master = preparar_master_dataset()

st.title("🇵🇪 Sistema Tectónico y Sismológico Avanzado - IGP")

# Filtros
st.sidebar.header("📍 Sectorización")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Parámetros Sismotectónicos")
mag_rango = st.sidebar.slider("Magnitud (M)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Rango Temporal", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))
filtro_rol = st.sidebar.multiselect("Clasificación de Evento", ["Evento Aislado", "Sismo Principal (Mainshock)", "Réplica (Aftershock)"], default=["Evento Aislado", "Sismo Principal (Mainshock)", "Réplica (Aftershock)"])

df_filtrado = df_master[
    (df_master["departamento"].isin(dep_sel)) &
    (df_master["magnitud"] >= mag_rango[0]) &
    (df_master["magnitud"] <= mag_rango[1]) &
    (df_master["profundidad_km"] >= prof_rango[0]) &
    (df_master["profundidad_km"] <= prof_rango[1]) &
    (df_master["anio"] >= rango_anios[0]) &
    (df_master["anio"] <= rango_anios[1]) &
    (df_master["rol_evento"].isin(filtro_rol))
].copy()

# Métricas
k1, k2, k3, k4 = st.columns(4)
k1.metric("Eventos Activos", len(df_filtrado))
k2.metric("Sismo Mayor", f"{df_filtrado['magnitud'].max() if not df_filtrado.empty else 0} M")
k3.metric("Enjambres / Secuencias", df_filtrado[df_filtrado['id_secuencia'] != 'None']['id_secuencia'].nunique())
k4.metric("Dist. Promedio a Fosa", f"{round(df_filtrado['distancia_fosa_km'].mean(), 1) if not df_filtrado.empty else 0} km")

tab_mapas, tab_timeline, tab_subduccion, tab_secuencias, tab_qgis = st.tabs([
    "🗺️ Visor Cartográfico",
    "⏳ Línea de Tiempo",
    "🌊 Tectónica & Fosa",
    "🔁 Enjambres y Réplicas",
    "📐 Integración QGIS"
])

# --- TAB 1: MAPAS ---
with tab_mapas:
    modo = st.radio("Capa Cartográfica:", ["2D (OpenStreetMap con Fosa)", "3D (PyDeck Tectónico)"], horizontal=True)
    colores_hex = {"Superficial (0-60 km)": "#E63946", "Intermedio (61-300 km)": "#F4A261", "Profundo (>300 km)": "#2A9D8F"}

    if modo == "2D (OpenStreetMap con Fosa)":
        m = folium.Map(location=[-9.19, -75.01], zoom_start=5, tiles="OpenStreetMap")
        
        # Trazo de la Fosa de Perú-Chile
        folium.PolyLine(FOSA_PERU_CHILE, color="#1D3557", weight=3.5, opacity=0.8, tooltip="Eje de Fosa Perú-Chile (Subducción Nazca-Sudamérica)").add_to(m)
        
        for _, r in df_filtrado.iterrows():
            folium.CircleMarker(
                location=[r["latitud"], r["longitud"]],
                radius=max(r["magnitud"] * 2.2, 3),
                color=colores_hex.get(r["tipo_profundidad"], "#333333"),
                fill=True,
                fill_opacity=0.75,
                popup=f"<b>{r['referencia']}</b><br>M: {r['magnitud']} | Prof: {r['profundidad_km']} km<br>Rol: {r['rol_evento']}<br>Dist. Fosa: {r['distancia_fosa_km']} km"
            ).add_to(m)
        st_folium(m, width=1100, height=520)
    else:
        df_filtrado["deck_color"] = df_filtrado["tipo_profundidad"].apply(
            lambda t: [230, 57, 70, 180] if "Superficial" in t else ([244, 162, 97, 180] if "Intermedio" in t else [42, 157, 143, 180])
        )
        layer = pdk.Layer(
            "ColumnLayer",
            data=df_filtrado,
            get_position=["longitud", "latitud"],
            get_elevation="profundidad_km",
            elevation_scale=1400,
            radius=7500,
            get_fill_color="deck_color",
            pickable=True
        )
        st.pydeck_chart(pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=-12.04, longitude=-75.50, zoom=5.1, pitch=50, bearing=-15),
            tooltip={"html": "<b>{referencia}</b><br/>Magnitud: {magnitud} M<br/>Profundidad: {profundidad_km} km<br/>Rol: {rol_evento}"}
        ))

# --- TAB 2: LÍNEA DE TIEMPO ---
with tab_timeline:
    st.subheader("Evolución Temporal de la Actividad")
    fig_time = px.scatter(
        df_filtrado,
        x="fecha_hora",
        y="magnitud",
        size="magnitud",
        color="tipo_profundidad",
        hover_data=["referencia", "rol_evento", "departamento"],
        color_discrete_map=colores_hex
    )
    st.plotly_chart(fig_time, width="stretch")

# --- TAB 3: TECTÓNICA Y SUBDUCCIÓN ---
with tab_subduccion:
    st.subheader("Perfil de Subducción (Plano de Wadati-Benioff)")
    st.markdown("Visualización transversal de la placa de Nazca hundiéndose bajo el continente: a mayor distancia hacia el este de la fosa, mayor es la profundidad del sismo.")
    
    fig_benioff = px.scatter(
        df_filtrado,
        x="distancia_fosa_km",
        y="profundidad_km",
        size="magnitud",
        color="tipo_profundidad",
        hover_data=["referencia", "departamento"],
        color_discrete_map=colores_hex,
        labels={"distancia_fosa_km": "Distancia al Eje de la Fosa Marina (km)", "profundidad_km": "Profundidad del Hipocentro (km)"}
    )
    fig_benioff.update_yaxes(autorange="reversed")  # Profundidad hacia abajo
    st.plotly_chart(fig_benioff, width="stretch")

# --- TAB 4: SECUENCIAS Y RÉPLICAS ---
with tab_secuencias:
    st.subheader("Detección de Secuencias Sísmicas (Mainshocks y Aftershocks)")
    df_sec = df_filtrado[df_filtrado["id_secuencia"] != "None"]
    
    if not df_sec.empty:
        fig_sec = px.scatter(
            df_sec,
            x="fecha_hora",
            y="magnitud",
            color="rol_evento",
            symbol="id_secuencia",
            size="magnitud",
            hover_data=["referencia", "id_secuencia"],
            title="Secuencias Agrupadas por Proximidad Temporal y Espacial"
        )
        st.plotly_chart(fig_sec, width="stretch")
        st.dataframe(df_sec[["fecha_hora", "id_secuencia", "rol_evento", "magnitud", "profundidad_km", "referencia"]], width="stretch")
    else:
        st.info("No se detectaron secuencias de sismo principal y réplicas con los filtros actuales.")

# --- TAB 5: QGIS ---
with tab_qgis:
    st.subheader("Exportación SIG Completa")
    def exportar_geojson(df):
        features = []
        for _, r in df.iterrows():
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["longitud"], r["latitud"]]},
                "properties": {
                    "fecha_hora": str(r["fecha_hora"]),
                    "magnitud": float(r["magnitud"]),
                    "profundidad_km": float(r["profundidad_km"]),
                    "rol_evento": r["rol_evento"],
                    "secuencia": r["id_secuencia"],
                    "distancia_fosa_km": float(r["distancia_fosa_km"]),
                    "departamento": r["departamento"],
                    "provincia": r["provincia_cercana"],
                    "nivel_riesgo": r["nivel_riesgo"]
                }
            })
        return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)

    st.download_button(
        label="📥 Descargar GeoJSON con Parámetros Tectónicos",
        data=exportar_geojson(df_filtrado),
        file_name="sismos_tectonica_peru.geojson",
        mime="application/geo+json"
    )