import streamlit as st
import pandas as pd
import pydeck as pdk
import folium
from streamlit_folium import st_folium
import plotly.express as px
import json
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

st.set_page_config(page_title="Plataforma de Análisis Sísmico Perú - IGP", layout="wide")

# CSS para evitar que Folium renderice gris y estilizar leyendas
st.markdown("""
<style>
    iframe {
        width: 100% !important;
        border-radius: 8px;
    }
    .legend-box {
        background-color: #1e1e1e;
        color: white;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #444;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

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

# Banner de alerta reciente
ultimos_eventos = df_master[df_master["fuente"] == "IGP (Tiempo Real)"]
if not ultimos_eventos.empty:
    ultimo = ultimos_eventos.iloc[0]
    if ultimo["magnitud"] >= 4.5:
        st.error(
            f"🔔 **ÚLTIMO SISMO DETECTADO (IGP):** Magnitud {ultimo['magnitud']} M en {ultimo['referencia']} "
            f"| Profundidad: {ultimo['profundidad_km']} km | {ultimo['nivel_riesgo']}"
        )

st.title("🇵🇪 Monitor y Geovisor Sísmico del Perú")
st.caption("Sistema de procesamiento, análisis físico y visualización de la actividad sismotectónica nacional.")

# --- BARRA LATERAL ---
st.sidebar.header("📍 Sectorización Geográfica")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Filtros Sismológicos")
mag_rango = st.sidebar.slider("Rango de Magnitud (Momento / Richter)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Rango de Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Ventana Temporal (Años)", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))

df_filtrado = df_master[
    (df_master["departamento"].isin(dep_sel)) &
    (df_master["magnitud"] >= mag_rango[0]) &
    (df_master["magnitud"] <= mag_rango[1]) &
    (df_master["profundidad_km"] >= prof_rango[0]) &
    (df_master["profundidad_km"] <= prof_rango[1]) &
    (df_master["anio"] >= rango_anios[0]) &
    (df_master["anio"] <= rango_anios[1])
].copy()

# --- PANEL DE MÉTRICAS PRINCIPALES ---
k1, k2, k3, k4 = st.columns(4)
k1.metric("Sismos Visibles", len(df_filtrado), help="Total de eventos que cumplen con los filtros seleccionados.")
k2.metric("Magnitud Máxima", f"{df_filtrado['magnitud'].max() if not df_filtrado.empty else 0} M", help="Mayor magnitud registrada en el conjunto filtrado.")
criticos = len(df_filtrado[df_filtrado["nivel_riesgo"].str.contains("CRÍTICA|ROJA")])
k3.metric("Eventos Severos / Críticos", criticos, help="Sismos de alta magnitud ocurridos a poca distancia de zonas pobladas.")
k4.metric("Energía Acumulada", f"{df_filtrado['energia_tnt_ton'].sum():,.0f} Ton TNT" if not df_filtrado.empty else "0", help="Equivalente en dinamita de la energía elástica liberada.")

st.markdown("---")

# --- PESTAÑAS PRINCIPALES ---
tab_mapas, tab_gutenberg, tab_geologia, tab_telegram, tab_qgis = st.tabs([
    "🗺️ Visor Cartográfico (2D / 3D)",
    "📈 Peligro Sísmico (b-value)",
    "🌋 Fallas Geológicas Activas",
    "📲 Centro de Alertas",
    "📐 Exportación SIG / QGIS"
])

# ==================== PESTAÑA 1: MAPAS ====================
with tab_mapas:
    col_izq, col_der = st.columns([3, 1])
    
    with col_der:
        st.markdown("### 📖 Leyenda del Mapa")
        st.markdown("""
        **Profundidad del Hipocentro:**
        * 🔴 **Superficial (0 - 60 km):** Mayor potencial destructivo en superficie.
        * 🟠 **Intermedio (61 - 300 km):** Ocurren dentro de la placa en subducción.
        * 🔵 **Profundo (> 300 km):** Sismos en el manto terrestre (selva baja/frontera).
        
        **Estructuras Geológicas:**
        * 🟦 **Línea Azul Continua:** Fosa oceánica Perú-Chile (límite de placas).
        * 🟪 **Línea Púrpura Discontinua:** Fallas continentales activas (INGEMMET).
        
        **Tamaño del Círculo:**
        * Proporcional a la **Magnitud ($M$)** del sismo.
        """)
        
        modo = st.radio("Tipo de Visor:", ["🗺️ Mapa 2D con Fallas", "🌐 Relieve 3D de Hipocentros"])

    with col_izq:
        if modo == "🗺️ Mapa 2D con Fallas":
            # Mapbox / OpenStreetMap con configuración anti-parpadeo
            m = folium.Map(
                location=[-9.19, -75.01],
                zoom_start=5,
                tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                attr="&copy; OpenStreetMap contributors",
                control_scale=True
            )
            
            # Trazo de la Fosa Perú-Chile
            folium.PolyLine(
                FOSA_PERU_CHILE,
                color="#1D3557",
                weight=3.5,
                opacity=0.9,
                tooltip="Eje de Fosa Perú-Chile (Zona de Subducción)"
            ).add_to(m)
            
            # Fallas activas
            for falla in FALLAS_ACTIVAS_PERU:
                folium.PolyLine(
                    falla["coords"],
                    color="#7209B7",
                    weight=3,
                    dash_array="6, 6",
                    tooltip=f"Falla: {falla['nombre']} ({falla['tipo']})"
                ).add_to(m)

            colores_hex = {
                "Superficial (0-60 km)": "#E63946",
                "Intermedio (61-300 km)": "#F4A261",
                "Profundo (>300 km)": "#2A9D8F"
            }

            for _, r in df_filtrado.iterrows():
                folium.CircleMarker(
                    location=[r["latitud"], r["longitud"]],
                    radius=max(r["magnitud"] * 2.2, 3.5),
                    color=colores_hex.get(r["tipo_profundidad"], "#333333"),
                    fill=True,
                    fill_opacity=0.75,
                    popup=f"<b>{r['referencia']}</b><br>"
                          f"Magnitud: <b>{r['magnitud']} M</b><br>"
                          f"Profundidad: <b>{r['profundidad_km']} km</b><br>"
                          f"Distancia a fosa: <b>{r['distancia_fosa_km']} km</b><br>"
                          f"Riesgo poblacional: <b>{r['nivel_riesgo']}</b>"
                ).add_to(m)

            # Renderizado responsivo
            st_folium(m, width=None, height=520, returned_objects=[])
            
        else:
            st.caption("Usa **Ctrl + Clic izquierdo** (o clic derecho) para inclinar la vista y analizar la profundidad hacia el interior de la Tierra.")
            
            df_filtrado["deck_color"] = df_filtrado["tipo_profundidad"].apply(
                lambda t: [230, 57, 70, 180] if "Superficial" in t else ([244, 162, 97, 180] if "Intermedio" in t else [42, 157, 143, 180])
            )
            
            layer_3d = pdk.Layer(
                "ColumnLayer",
                data=df_filtrado,
                get_position=["longitud", "latitud"],
                get_elevation="profundidad_km",
                elevation_scale=1500,
                radius=7500,
                get_fill_color="deck_color",
                pickable=True
            )
            
            st.pydeck_chart(pdk.Deck(
                layers=[layer_3d],
                initial_view_state=pdk.ViewState(latitude=-12.04, longitude=-75.50, zoom=5.1, pitch=50, bearing=-15),
                tooltip={"html": "<b>{referencia}</b><br/>Magnitud: {magnitud} M<br/>Profundidad: {profundidad_km} km"}
            ))

# ==================== PESTAÑA 2: GUTENBERG-RICHTER ====================
with tab_gutenberg:
    st.subheader("Análisis de Tensión y Acumulación Tectónica (Ley de Gutenberg-Richter)")
    
    with st.expander("📚 ¿Qué significa este gráfico y el valor 'b'?", expanded=True):
        st.markdown(r"""
        La relación de Gutenberg-Richter modela cuántos sismos pequeños ocurren por cada sismo grande:
        $$\log_{10} N = a - b M$$
        * **El valor $b$ (Pendiente):** Mide el estado de esfuerzos de la corteza.
          * **$b < 0.85$ (Crítico):** La zona acumula mucha tensión sin liberar energía suficiente. Mayor probabilidad de un evento mayor en el mediano/largo plazo.
          * **$0.85 \le b \le 1.05$ (Normal):** Liberación homogénea y constante de energía.
          * **$b > 1.05$ (Bajo esfuerzo):** Predominio de enjambres o microsismos que disipan energía fácilmente.
        """)

    dep_analisis = st.selectbox("Seleccionar Departamento a evaluar:", options=deps_list)
    df_dep = df_master[df_master["departamento"] == dep_analisis]
    b_val, diag = calcular_b_value_departamento(df_dep)
    
    c_b1, c_b2 = st.columns([1, 2])
    with c_b1:
        st.metric(f"Valor 'b' calculado ({dep_analisis})", f"{b_val if b_val else 'N/A'}")
        st.info(f"**Diagnóstico de Tensión:**\n\n{diag}")
        
    with c_b2:
        mags_conteo = df_dep[df_dep["magnitud"] >= 4.0]["magnitud"].round(1).value_counts().reset_index()
        mags_conteo.columns = ["magnitud", "conteo"]
        mags_conteo = mags_conteo.sort_values(by="magnitud")
        fig_gr = px.scatter(
            mags_conteo, x="magnitud", y="conteo", log_y=True,
            title=f"Distribución Frecuencia vs. Magnitud ({dep_analisis})",
            labels={"magnitud": "Magnitud (M)", "conteo": "Cantidad de Sismos (Escala Logarítmica)"}
        )
        st.plotly_chart(fig_gr, width="stretch")

# ==================== PESTAÑA 3: FALLAS GEOLÓGICAS ====================
with tab_geologia:
    st.subheader("Catálogo de Fallas Geológicas Activas (INGEMMET)")
    with st.expander("📚 ¿Cómo interpretar las fallas geológicas continentales?"):
        st.markdown("""
        En el Perú existen dos grandes fuentes sísmicas:
        1. **Sismos de Interplaca (Subducción):** Ocurren en la costa donde la placa de Nazca se hunde bajo el continente.
        2. **Sismos Corticales (Fallas Activas):** Ocurren en la cordillera y selva por fracturas directas en la corteza superficial continental. Suelen ser poco profundos ($< 20\text{ km}$) y muy dañinos a nivel local (como el terremoto de Ancash en 1970 o Cusco en 1950).
        """)
    df_fallas = pd.DataFrame([{"Falla": f["nombre"], "Tipo Cinemático": f["tipo"]} for f in FALLAS_ACTIVAS_PERU])
    st.table(df_fallas)

# ==================== PESTAÑA 4: ALERTAS TELEGRAM ====================
with tab_telegram:
    st.subheader("Centro de Alertas Sísmicas por Telegram")
    st.markdown("Conecta tu bot para recibir un reporte estructurado cuando ocurra un evento crítico.")
    
    t_token = st.text_input("Bot Token de Telegram", type="password")
    t_chat = st.text_input("Chat ID de Destino")
    
    if st.button("Enviar Alerta de Prueba"):
        if t_token and t_chat:
            if not df_filtrado.empty:
                s_test = df_filtrado.iloc[0].to_dict()
                exito = enviar_alerta_telegram(t_token, t_chat, s_test)
                if exito:
                    st.success("✅ Alerta enviada correctamente a Telegram.")
                else:
                    st.error("❌ Fallo al conectar. Revisa el Token y Chat ID.")
        else:
            st.warning("Completa las credenciales de Telegram para realizar el envío.")

# ==================== PESTAÑA 5: QGIS ====================
with tab_qgis:
    st.subheader("Exportación de Datos Geoespaciales")
    st.markdown("Descarga la base de datos completa procesada en formato **GeoJSON** lista para abrirse en QGIS, ArcGIS o Google Earth.")
    
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
        label="📥 Descargar Capa Vectorial (.GeoJSON)",
        data=exportar_geojson(df_filtrado),
        file_name="sismos_completo_peru.geojson",
        mime="application/geo+json"
    )