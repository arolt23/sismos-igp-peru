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
from analysis import (
    calcular_energia_joules,
    estimar_radio_percepcion_km,
    clasificar_alerta_riesgo,
    calcular_b_value_departamento,
    enviar_alerta_telegram
)
from tectonics import FOSA_PERU_CHILE, calcular_distancia_fosa_km, identificar_secuencias_sismicas
from geology import FALLAS_ACTIVAS_PERU

st.set_page_config(page_title="Plataforma Sismotectónica del Perú - IGP", layout="wide")

# Corrección de renderizado de Folium y estilos de tarjetas
st.markdown("""
<style>
    iframe { width: 100% !important; border-radius: 8px; }
    .stMetric { background-color: #1a1c24; padding: 12px; border-radius: 8px; border: 1px solid #333; }
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

# Banner de evento reciente
ultimos_eventos = df_master[df_master["fuente"] == "IGP (Tiempo Real)"]
if not ultimos_eventos.empty:
    ultimo = ultimos_eventos.iloc[0]
    if ultimo["magnitud"] >= 4.5:
        st.error(
            f"🔔 **ÚLTIMO REPORTE SÍSMICO (IGP):** Magnitud {ultimo['magnitud']} M en {ultimo['referencia']} "
            f"| Profundidad: {ultimo['profundidad_km']} km | {ultimo['nivel_riesgo']}"
        )

st.title("🇵🇪 Sistema Integral de Geofísica Sísmica del Perú")
st.caption("Procesamiento de datos en tiempo real (IGP), registros históricos (USGS) y estructuras tectónicas (INGEMMET).")

# ==================== FILTROS LATERALES ====================
st.sidebar.header("📍 Filtros Territoriales")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

provs_list = sorted(list(df_master[df_master["departamento"].isin(dep_sel)]["provincia_cercana"].unique()))
prov_sel = st.sidebar.multiselect("Provincias", options=provs_list, default=provs_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Filtros Físicos y Temporales")
mag_rango = st.sidebar.slider("Rango de Magnitud (M)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Rango de Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Periodo Histórico (Años)", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))

df_filtrado = df_master[
    (df_master["departamento"].isin(dep_sel)) &
    (df_master["provincia_cercana"].isin(prov_sel)) &
    (df_master["magnitud"] >= mag_rango[0]) &
    (df_master["magnitud"] <= mag_rango[1]) &
    (df_master["profundidad_km"] >= prof_rango[0]) &
    (df_master["profundidad_km"] <= prof_rango[1]) &
    (df_master["anio"] >= rango_anios[0]) &
    (df_master["anio"] <= rango_anios[1])
].copy()

# KPIs Superiores
k1, k2, k3, k4 = st.columns(4)
k1.metric("Sismos Filtrados", len(df_filtrado), help="Cantidad total de eventos visibles.")
k2.metric("Sismo Mayor", f"{df_filtrado['magnitud'].max() if not df_filtrado.empty else 0} M", help="Mayor magnitud en el conjunto seleccionado.")
criticos = len(df_filtrado[df_filtrado["nivel_riesgo"].str.contains("CRÍTICA|ROJA")])
k3.metric("Alertas Severas/Críticas", criticos, help="Eventos de alta energía próximos a poblaciones.")
k4.metric("Energía Acumulada", f"{df_filtrado['energia_tnt_ton'].sum():,.0f} Ton TNT" if not df_filtrado.empty else "0", help="Equivalente en TNT de la energía elástica liberada.")

st.markdown("---")

colores_hex = {
    "Superficial (0-60 km)": "#E63946",
    "Intermedio (61-300 km)": "#F4A261",
    "Profundo (>300 km)": "#2A9D8F"
}

# ==================== PESTAÑAS ====================
tab_mapas, tab_timeline, tab_territorio, tab_tectonica, tab_energia, tab_secuencias, tab_gutenberg, tab_qgis = st.tabs([
    "🗺️ Visor Cartográfico",
    "⏳ Línea de Tiempo",
    "🏙️ Proximidad Urbana",
    "🌊 Subducción (Wadati-Benioff)",
    "💥 Física y Energía",
    "🔁 Réplicas y Enjambres",
    "📈 Peligro Sísmico (b-value)",
    "📐 QGIS / GeoJSON"
])

# --- TAB 1: MAPAS 2D / 3D ---
with tab_mapas:
    c_mapa, c_leyenda = st.columns([3, 1])
    
    with c_leyenda:
        st.markdown("### 📖 Leyenda del Mapa")
        st.markdown("""
        **Profundidad del Hipocentro:**
        * 🔴 **Superficial (0-60 km):** Mayor daño en superficie.
        * 🟠 **Intermedio (61-300 km):** Placa en subducción.
        * 🔵 **Profundo (>300 km):** Manto terrestre profundo.
        
        **Estructuras Geológicas:**
        * 🟦 **Línea Azul:** Fosa marina Perú-Chile.
        * 🟪 **Línea Púrpura Discontinua:** Fallas continentales activas (INGEMMET).
        * 🟢 **Marcadores Verdes:** Capitales / Zonas urbanas.
        """)
        modo = st.radio("Capa Cartográfica:", ["2D (Puntos y Fallas)", "2D (Clusters Agrupados)", "2D (Mapa de Calor)", "🌐 3D (Relieve y Profundidad)"])

    with c_mapa:
        if "2D" in modo:
            m = folium.Map(location=[-9.19, -75.01], zoom_start=5, tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png", attr="&copy; OpenStreetMap")
            
            # Fosa y Fallas
            folium.PolyLine(FOSA_PERU_CHILE, color="#1D3557", weight=3.5, tooltip="Fosa Perú-Chile").add_to(m)
            for f in FALLAS_ACTIVAS_PERU:
                folium.PolyLine(f["coords"], color="#7209B7", weight=3, dash_array="6, 6", tooltip=f"Falla {f['nombre']}").add_to(m)
            
            # Ciudades
            for dep, d_info in UBICACIONES_PERU.items():
                folium.Marker(location=d_info["coords"], tooltip=f"Zona Urbana: {dep}", icon=folium.Icon(color="green", icon="info-sign")).add_to(m)

            if modo == "2D (Puntos y Fallas)":
                for _, r in df_filtrado.iterrows():
                    folium.CircleMarker(
                        location=[r["latitud"], r["longitud"]],
                        radius=max(r["magnitud"] * 2.2, 3),
                        color=colores_hex.get(r["tipo_profundidad"], "#333"),
                        fill=True,
                        fill_opacity=0.75,
                        popup=f"<b>{r['referencia']}</b><br>M: {r['magnitud']} | Prof: {r['profundidad_km']} km<br>Dist. Población: {r['distancia_poblado_km']} km"
                    ).add_to(m)
            elif modo == "2D (Clusters Agrupados)":
                cluster = MarkerCluster().add_to(m)
                for _, r in df_filtrado.iterrows():
                    folium.CircleMarker(
                        location=[r["latitud"], r["longitud"]],
                        radius=max(r["magnitud"] * 2.2, 3),
                        color=colores_hex.get(r["tipo_profundidad"], "#333"),
                        fill=True, fill_opacity=0.8,
                        popup=f"<b>{r['referencia']}</b> ({r['magnitud']} M)"
                    ).add_to(cluster)
            else:
                heat_points = [[r["latitud"], r["longitud"], r["magnitud"]] for _, r in df_filtrado.iterrows()]
                HeatMap(heat_points, radius=22, blur=14, max_zoom=7).add_to(m)
                
            st_folium(m, width=None, height=520, returned_objects=[])
        else:
            st.caption("Usa **Ctrl + Clic izquierdo** (o clic derecho) para inclinar la vista tridimensional y evaluar la columna de profundidad.")
            df_filtrado["deck_color"] = df_filtrado["tipo_profundidad"].apply(
                lambda t: [230, 57, 70, 180] if "Superficial" in t else ([244, 162, 97, 180] if "Intermedio" in t else [42, 157, 143, 180])
            )
            layer_3d = pdk.Layer(
                "ColumnLayer", data=df_filtrado, get_position=["longitud", "latitud"],
                get_elevation="profundidad_km", elevation_scale=1500, radius=7500,
                get_fill_color="deck_color", pickable=True
            )
            st.pydeck_chart(pdk.Deck(
                layers=[layer_3d],
                initial_view_state=pdk.ViewState(latitude=-12.04, longitude=-75.50, zoom=5.1, pitch=50, bearing=-15),
                tooltip={"html": "<b>{referencia}</b><br/>M: {magnitud} | Profundidad: {profundidad_km} km"}
            ))

# --- TAB 2: LÍNEA DE TIEMPO HISTÓRICA ---
with tab_timeline:
    st.subheader("Evolución Temporal de la Sismicidad")
    with st.expander("📚 ¿Qué observas en estos gráficos temporales?"):
        st.markdown("""
        * **Dispersión Temporal (Gráfica superior):** Cada círculo representa un sismo a lo largo de las décadas. La escala de color refleja la profundidad y el tamaño su magnitud.
        * **Frecuencia Anual (Gráfica inferior izquierda):** Muestra los periodos con picos anormales de sismicidad por departamento.
        * **Eventos Notables (Gráfica inferior derecha):** Resalta los terremotos más destructivos de la historia instrumental peruana.
        """)
    
    fig_time = px.scatter(
        df_filtrado, x="fecha_hora", y="magnitud", size="magnitud", color="tipo_profundidad",
        hover_data=["referencia", "departamento", "impacto"], color_discrete_map=colores_hex,
        title="Secuencia Cronológica de Magnitud y Profundidad",
        labels={"fecha_hora": "Fecha del Sismo", "magnitud": "Magnitud (M)"}
    )
    st.plotly_chart(fig_time, width="stretch")
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        df_conteo_anio = df_filtrado.groupby(["anio", "departamento"]).size().reset_index(name="eventos")
        fig_hist_anio = px.bar(
            df_conteo_anio, x="anio", y="eventos", color="departamento",
            title="Frecuencia Sísmica Anual por Departamento", barmode="stack",
            labels={"anio": "Año", "eventos": "Cantidad de Sismos"}
        )
        st.plotly_chart(fig_hist_anio, width="stretch")
        
    with col_t2:
        df_dest = df_filtrado[df_filtrado["impacto"] != "Monitoreo Instrumental"]
        fig_dest = px.bar(
            df_dest, x="fecha_hora", y="magnitud", color="departamento",
            hover_data=["impacto", "referencia"],
            title="Terremotos Históricos de Gran Impacto",
            labels={"fecha_hora": "Fecha", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_dest, width="stretch")

# --- TAB 3: PROXIMIDAD Y TERRITORIO ---
with tab_territorio:
    st.subheader("Análisis Territorial y Cercanía a Centros Urbanos")
    with st.expander("📚 Interpretación de la exposición urbana"):
        st.markdown("""
        * **Profundidad vs. Distancia Urbana:** Los sismos situados en el cuadrante inferior izquierdo (muy superficiales y a pocos kilómetros de una ciudad) representan el mayor riesgo de colapso estructural.
        * **Dispersión por Departamento (Boxplot):** Identifica qué regiones concentran consistentemente los sismos de mayor intensidad media.
        """)
    
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        fig_dist_prof = px.scatter(
            df_filtrado, x="distancia_poblado_km", y="profundidad_km", size="magnitud",
            color="tipo_profundidad", hover_data=["referencia", "departamento", "provincia_cercana"],
            color_discrete_map=colores_hex,
            title="Distancia a Población vs. Profundidad del Hipocentro",
            labels={"distancia_poblado_km": "Distancia a Zona Urbana (km)", "profundidad_km": "Profundidad (km)"}
        )
        st.plotly_chart(fig_dist_prof, width="stretch")
        
    with col_u2:
        fig_box = px.box(
            df_filtrado, x="departamento", y="magnitud", color="departamento",
            title="Dispersión y Mediana de Magnitudes por Departamento",
            labels={"departamento": "Departamento", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_box, width="stretch")

# --- TAB 4: SUBDUCCIÓN (PLANO DE WADATI-BENIOFF) ---
with tab_tectonica:
    st.subheader("Perfil de Subducción Cortical (Plano de Wadati-Benioff)")
    with st.expander("📚 ¿Qué es el plano de Wadati-Benioff?"):
        st.markdown("""
        Esta gráfica muestra un corte transversal de la Tierra: el eje horizontal representa la distancia desde la fosa marina (océano) hacia el este (continente), y el eje vertical representa la profundidad invertida.
        Permite observar la **geometría real de la Placa de Nazca hundiéndose por debajo del Perú**.
        """)
    
    fig_benioff = px.scatter(
        df_filtrado, x="distancia_fosa_km", y="profundidad_km", size="magnitud",
        color="tipo_profundidad", hover_data=["referencia", "departamento"],
        color_discrete_map=colores_hex,
        title="Geometría del Plano de Subducción (Profundidad vs. Distancia a la Fosa)",
        labels={"distancia_fosa_km": "Distancia a la Fosa Marina (km)", "profundidad_km": "Profundidad Hipocentral (km)"}
    )
    fig_benioff.update_yaxes(autorange="reversed")
    st.plotly_chart(fig_benioff, width="stretch")

# --- TAB 5: FÍSICA Y ENERGÍA LIBERADA ---
with tab_energia:
    st.subheader("Física Sísmica y Energía Liberada (Gutenberg-Richter)")
    with st.expander("📚 ¿Cómo se calcula la energía?"):
        st.markdown(r"""
        La energía sísmica no crece de forma lineal, sino logarítmica:
        $$\log_{10} E = 4.8 + 1.5 M$$
        Un aumento de 1 grado en magnitud ($M+1$) equivale a liberar aproximadamente **32 veces más energía**.
        """)
        
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        top_energia = df_filtrado.sort_values(by="energia_tnt_ton", ascending=False).head(12)
        fig_en = px.bar(
            top_energia, x="energia_tnt_ton", y="referencia", orientation="h", color="departamento",
            title="Top 12 Eventos con Mayor Energía (Equivalente en Toneladas de TNT)",
            labels={"energia_tnt_ton": "Toneladas de TNT", "referencia": "Evento"}
        )
        st.plotly_chart(fig_en, width="stretch")
        
    with col_e2:
        fig_rad = px.scatter(
            df_filtrado, x="magnitud", y="radio_afectacion_km", size="energia_tnt_ton",
            color="tipo_profundidad", hover_data=["referencia", "departamento"],
            color_discrete_map=colores_hex,
            title="Radio de Percepción Superficial Estimado",
            labels={"radio_afectacion_km": "Radio de Afectación (km)", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_rad, width="stretch")

# --- TAB 6: ENJAMBRES Y RÉPLICAS ---
with tab_secuencias:
    st.subheader("Detección de Secuencias Sísmicas y Réplicas")
    with st.expander("📚 Análisis de Réplicas (Ley de Omori)"):
        st.markdown("""
        Agrupa eventos que ocurren dentro de una ventana de 7 días y un radio de 100 km respecto a un sismo principal ($M \ge 5.5$). Permite monitorear la disipación de réplicas tras un terremoto.
        """)
    
    df_sec = df_filtrado[df_filtrado["id_secuencia"] != "None"]
    if not df_sec.empty:
        fig_sec = px.scatter(
            df_sec, x="fecha_hora", y="magnitud", color="rol_evento", symbol="id_secuencia", size="magnitud",
            hover_data=["referencia", "id_secuencia"],
            title="Secuencias Agrupadas (Sismo Principal vs. Réplicas)",
            labels={"fecha_hora": "Fecha", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_sec, width="stretch")
        st.dataframe(df_sec[["fecha_hora", "id_secuencia", "rol_evento", "magnitud", "profundidad_km", "referencia"]], width="stretch")
    else:
        st.info("No se detectaron secuencias de sismo principal y réplicas con los filtros actuales.")

# --- TAB 7: PELIGRO SÍSMICO (B-VALUE) ---
with tab_gutenberg:
    st.subheader("Análisis de Esfuerzo Tectónico (b-value de Gutenberg-Richter)")
    with st.expander("📚 ¿Cómo interpretar el valor 'b'?"):
        st.markdown(r"""
        La pendiente $b$ de la relación $\log_{10} N = a - b M$ estima el estado de esfuerzos de la corteza:
        * **$b < 0.85$ (Crítico):** Alta acumulación de esfuerzo; la zona retiene energía y tiene mayor potencial para eventos de gran magnitud.
        * **$0.85 \le b \le 1.05$ (Normal):** Régimen tectónico estable.
        * **$b > 1.05$ (Bajo Esfuerzo):** Liberación continua mediante microsismicidad o enjambres.
        """)
        
    dep_analisis = st.selectbox("Seleccionar Departamento:", options=deps_list)
    df_dep = df_master[df_master["departamento"] == dep_analisis]
    b_val, diag = calcular_b_value_departamento(df_dep)
    
    c_b1, c_b2 = st.columns([1, 2])
    with c_b1:
        st.metric(f"b-value ({dep_analisis})", f"{b_val if b_val else 'N/A'}")
        st.info(f"**Diagnóstico:**\n\n{diag}")
    with c_b2:
        mags_c = df_dep[df_dep["magnitud"] >= 4.0]["magnitud"].round(1).value_counts().reset_index()
        mags_c.columns = ["magnitud", "conteo"]
        mags_c = mags_c.sort_values(by="magnitud")
        fig_gr = px.scatter(
            mags_c, x="magnitud", y="conteo", log_y=True,
            title=f"Curva Frecuencia-Magnitud ({dep_analisis})",
            labels={"magnitud": "Magnitud (M)", "conteo": "N° de Sismos (Escala Log)"}
        )
        st.plotly_chart(fig_gr, width="stretch")

# --- TAB 8: QGIS ---
with tab_qgis:
    st.subheader("Exportación de Datos Geoespaciales")
    st.markdown("Descarga la base vectorial completa en formato **GeoJSON** lista para abrirse en QGIS, ArcGIS o Google Earth.")
    
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
                    "distancia_poblado_km": float(r["distancia_poblado_km"]),
                    "departamento": r["departamento"],
                    "provincia": r["provincia_cercana"],
                    "nivel_riesgo": r["nivel_riesgo"]
                }
            })
        return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)

    st.download_button(
        label="📥 Descargar Capa Vectorial (.GeoJSON)",
        data=exportar_geojson(df_filtrado),
        file_name="sismos_peru_completo.geojson",
        mime="application/geo+json"
    )