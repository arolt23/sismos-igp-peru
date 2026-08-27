import streamlit as st
import pandas as pd
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.express as px
import json
from datetime import datetime, timezone
from geopy.distance import geodesic

from scraper import obtener_sismos_en_vivo
from historical_data import obtener_historico_peru
from analysis import (
    calcular_energia_joules,
    estimar_radio_percepcion_km,
    clasificar_alerta_riesgo,
    calcular_b_value_departamento,
    enviar_alerta_telegram
)
from tectonics import FOSA_PERU_CHILE, calcular_distancia_fosa_km, identificar_secuencias_sismicas
from geology import FALLAS_ACTIVAS_PERU

st.set_page_config(page_title="Geovisor Sísmico Profesional - IGP & INGEMMET", layout="wide")

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
    df_total = identificar_secuencias_sismicas(df_total)
    return df_total

df_master = preparar_master_dataset()

# ==================== ALERTA EN VIVO (BANNER SUPERIOR) ====================
ultimos_eventos = df_master[df_master["fuente"] == "IGP (Tiempo Real)"]
if not ultimos_eventos.empty:
    ultimo = ultimos_eventos.iloc[0]
    if ultimo["magnitud"] >= 4.5:
        st.error(
            f"🔔 **EVENTO RECIENTE REGISTRADO:** M {ultimo['magnitud']} en {ultimo['referencia']} "
            f"(Profundidad: {ultimo['profundidad_km']} km) - Nivel: {ultimo['nivel_riesgo']}"
        )

st.title("🇵🇪 Centro de Análisis Sismotectónico y Peligro Sísmico - IGP / INGEMMET")

# Filtros Laterales
st.sidebar.header("📍 Filtros Territoriales")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Parámetros Sísmicos")
mag_rango = st.sidebar.slider("Magnitud (M)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Periodo", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))

df_filtrado = df_master[
    (df_master["departamento"].isin(dep_sel)) &
    (df_master["magnitud"] >= mag_rango[0]) &
    (df_master["magnitud"] <= mag_rango[1]) &
    (df_master["profundidad_km"] >= prof_rango[0]) &
    (df_master["profundidad_km"] <= prof_rango[1]) &
    (df_master["anio"] >= rango_anios[0]) &
    (df_master["anio"] <= rango_anios[1])
].copy()

# KPIs
k1, k2, k3, k4 = st.columns(4)
k1.metric("Eventos Activos", len(df_filtrado))
k2.metric("Magnitud Máx.", f"{df_filtrado['magnitud'].max() if not df_filtrado.empty else 0} M")
criticos = len(df_filtrado[df_filtrado["nivel_riesgo"].str.contains("CRÍTICA|ROJA")])
k3.metric("Alertas Severas/Críticas", criticos)
k4.metric("Energía Acumulada", f"{df_filtrado['energia_tnt_ton'].sum():,.0f} Ton TNT" if not df_filtrado.empty else "0")

# Pestañas
tab_mapas, tab_gutenberg, tab_geologia, tab_telegram, tab_qgis = st.tabs([
    "🗺️ Mapas 2D/3D & Fallas",
    "📈 Peligro Sísmico (b-value)",
    "🌋 Fallas Activas INGEMMET",
    "📲 Notificaciones Telegram",
    "📐 Integración QGIS"
])

# --- TAB 1: MAPAS 2D Y 3D CON GEOLOGÍA ---
with tab_mapas:
    modo = st.radio("Tipo de Cartografía:", ["2D (OpenStreetMap con Fosa y Fallas Corticales)", "3D (PyDeck Tectónico)"], horizontal=True)
    colores_hex = {"Superficial (0-60 km)": "#E63946", "Intermedio (61-300 km)": "#F4A261", "Profundo (>300 km)": "#2A9D8F"}

    if modo == "2D (OpenStreetMap con Fosa y Fallas Corticales)":
        m = folium.Map(location=[-9.19, -75.01], zoom_start=5, tiles="OpenStreetMap")
        
        # 1. Fosa marina
        folium.PolyLine(FOSA_PERU_CHILE, color="#1D3557", weight=3.5, opacity=0.85, tooltip="Eje de Fosa Perú-Chile (Subducción)").add_to(m)
        
        # 2. Fallas INGEMMET
        for falla in FALLAS_ACTIVAS_PERU:
            folium.PolyLine(
                falla["coords"],
                color="#7209B7",
                weight=3,
                dash_array="5, 5",
                tooltip=f"Falla Activa INGEMMET: {falla['nombre']} ({falla['tipo']})"
            ).add_to(m)

        # 3. Puntos sísmicos
        for _, r in df_filtrado.iterrows():
            folium.CircleMarker(
                location=[r["latitud"], r["longitud"]],
                radius=max(r["magnitud"] * 2.2, 3),
                color=colores_hex.get(r["tipo_profundidad"], "#333333"),
                fill=True,
                fill_opacity=0.75,
                popup=f"<b>{r['referencia']}</b><br>M: {r['magnitud']} | Prof: {r['profundidad_km']} km<br>Nivel: {r['nivel_riesgo']}"
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
            tooltip={"html": "<b>{referencia}</b><br/>M: {magnitud} | Prof: {profundidad_km} km"}
        ))

# --- TAB 2: GUTENBERG-RICHTER (B-VALUE) ---
with tab_gutenberg:
    st.subheader("Estimación de Asperezas y Tensión Tectónica (b-value de Gutenberg-Richter)")
    st.markdown(
        r"La relación $\log_{10} N = a - b M$ describe la frecuencia de sismos por magnitud. "
        "Un valor **$b < 0.85$** indica que la corteza está sometida a altos esfuerzos tectónicos y retiene energía sin liberar con sismos menores."
    )
    
    dep_analisis = st.selectbox("Seleccionar Departamento para análisis de b-value:", options=deps_list)
    df_dep = df_master[df_master["departamento"] == dep_analisis]
    
    b_val, diag = calcular_b_value_departamento(df_dep)
    
    col_b1, col_b2 = st.columns([1, 2])
    with col_b1:
        st.metric(f"b-value ({dep_analisis})", f"{b_val if b_val else 'N/A'}")
        st.info(f"**Diagnóstico Geotectónico:**\n{diag}")
    
    with col_b2:
        mags_conteo = df_dep[df_dep["magnitud"] >= 4.0]["magnitud"].round(1).value_counts().reset_index()
        mags_conteo.columns = ["magnitud", "conteo"]
        mags_conteo = mags_conteo.sort_values(by="magnitud")
        fig_gr = px.scatter(
            mags_conteo, x="magnitud", y="conteo", log_y=True,
            title=f"Curva Frecuencia-Magnitud: {dep_analisis}",
            labels={"magnitud": "Magnitud (M)", "conteo": "N° de Eventos (Escala Log)"}
        )
        st.plotly_chart(fig_gr, width="stretch")

# --- TAB 3: FALLAS ACTIVAS INGEMMET ---
with tab_geologia:
    st.subheader("Catálogo de Fallas Cuaternarias Continentales")
    df_fallas = pd.DataFrame([{"Falla": f["nombre"], "Tipo Cinemático": f["tipo"]} for f in FALLAS_ACTIVAS_PERU])
    st.table(df_fallas)

# --- TAB 4: ALERTAS TELEGRAM ---
with tab_telegram:
    st.subheader("Configuración de Notificaciones Automáticas por Telegram")
    st.markdown("Permite enviar el último evento crítico detectado directamente a un canal o chat privado.")
    
    t_token = st.text_input("Telegram Bot Token (ej: 123456:ABC-DEF1234ghIkl)", type="password")
    t_chat = st.text_input("Chat ID (ej: -100123456789 o tu ID numérico)")
    
    if st.button("Enviar Alerta de Prueba"):
        if t_token and t_chat:
            if not df_filtrado.empty:
                s_test = df_filtrado.iloc[0].to_dict()
                exito = enviar_alerta_telegram(t_token, t_chat, s_test)
                if exito:
                    st.success("✅ ¡Mensaje de alerta enviado a Telegram correctamente!")
                else:
                    st.error("❌ Error al enviar. Verifica el Token y Chat ID.")
        else:
            st.warning("Ingresa el Token y Chat ID para realizar la prueba.")

# --- TAB 5: QGIS ---
with tab_qgis:
    st.subheader("Exportación de Capa Vectorial Completa")
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
                    "energia_tnt_ton": float(r["energia_tnt_ton"]),
                    "distancia_fosa_km": float(r["distancia_fosa_km"]),
                    "departamento": r["departamento"],
                    "nivel_riesgo": r["nivel_riesgo"]
                }
            })
        return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)

    st.download_button(
        label="📥 Descargar GeoJSON Completo",
        data=exportar_geojson(df_filtrado),
        file_name="sismos_geologia_peru.geojson",
        mime="application/geo+json"
    )