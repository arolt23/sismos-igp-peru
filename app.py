import streamlit as st
import pandas as pd
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.express as px
import json
import streamlit.components.v1 as components
import random
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

st.set_page_config(page_title="Monitor Sísmico & VJ Core - Máquina Tierna", layout="wide")

# Estilos e interfaz
st.markdown("""
<style>
    iframe { width: 100% !important; border-radius: 8px; }
    .stMetric { background-color: #161922; padding: 12px; border-radius: 8px; border: 1px solid #2a2e3d; }
    .credit-box {
        background: linear-gradient(135deg, #1f1235, #0f0c1b);
        border: 1px solid #7209b7;
        padding: 15px;
        border-radius: 10px;
        color: #f72585;
        text-align: center;
        margin-bottom: 20px;
    }
    .credit-box a {
        color: #4cc9f0;
        text-decoration: none;
        font-weight: bold;
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

# Branding
st.sidebar.markdown("""
<div class="credit-box">
    <h3 style="margin:0; font-size: 1.1rem; color: #fff;">⚡ MÁQUINA TIERNA</h3>
    <p style="margin: 4px 0 10px 0; font-size: 0.85rem; color: #bbb;">Desarrollado por <b>Arolt</b></p>
    <a href="https://instagram.com/maquinatierna" target="_blank">📷 @maquinatierna</a> &nbsp;|&nbsp;
    <a href="https://instagram.com/arolt23" target="_blank">👤 @arolt23</a>
</div>
""", unsafe_allow_html=True)

# Banner en vivo
ultimos_eventos = df_master[df_master["fuente"] == "IGP (Tiempo Real)"]
if not ultimos_eventos.empty:
    ultimo = ultimos_eventos.iloc[0]
    if ultimo["magnitud"] >= 4.5:
        st.error(
            f"🔔 **ÚLTIMO REPORTE SÍSMICO:** Magnitud {ultimo['magnitud']} M en {ultimo['referencia']} "
            f"| Profundidad: {ultimo['profundidad_km']} km | {ultimo['nivel_riesgo']}"
        )

st.title("🇵🇪 Plataforma Sismotectónica & Live Visuals - IGP")
st.caption("Desarrollado por Arolt para **Máquina Tierna** | Análisis territorial, geofísica e interpretación generativa.")

# Filtros laterales
st.sidebar.header("📍 Filtros Territoriales")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

provs_list = sorted(list(df_master[df_master["departamento"].isin(dep_sel)]["provincia_cercana"].unique()))
prov_sel = st.sidebar.multiselect("Provincias", options=provs_list, default=provs_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Filtros Sismológicos")
mag_rango = st.sidebar.slider("Rango de Magnitud (M)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Rango de Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Periodo (Años)", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))

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
k1.metric("Sismos Visibles", len(df_filtrado))
k2.metric("Sismo Mayor", f"{df_filtrado['magnitud'].max() if not df_filtrado.empty else 0} M")
criticos = len(df_filtrado[df_filtrado["nivel_riesgo"].str.contains("CRÍTICA|ROJA")])
k3.metric("Alertas Severas/Críticas", criticos)
k4.metric("Energía Acumulada", f"{df_filtrado['energia_tnt_ton'].sum():,.0f} Ton TNT" if not df_filtrado.empty else "0")

st.markdown("---")

colores_hex = {
    "Superficial (0-60 km)": "#E63946",
    "Intermedio (61-300 km)": "#F4A261",
    "Profundo (>300 km)": "#2A9D8F"
}

# ==================== PESTAÑAS ====================
tab_mapas, tab_vj, tab_timeline, tab_territorio, tab_tectonica, tab_energia, tab_secuencias, tab_gutenberg, tab_qgis = st.tabs([
    "🗺️ Visor Cartográfico",
    "🎛️ VJ Live Visuals & Synth",
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
        * 🔴 **Superficial (0-60 km):** Mayor impacto superficial.
        * 🟠 **Intermedio (61-300 km):** Placa en subducción.
        * 🔵 **Profundo (>300 km):** Manto terrestre profundo.
        
        **Estructuras Geológicas:**
        * 🟦 **Línea Azul:** Fosa marina Perú-Chile.
        * 🟪 **Línea Púrpura:** Fallas activas (INGEMMET).
        * 🟢 **Marcadores Verdes:** Zonas urbanas clave.
        """)
        modo = st.radio("Capa Cartográfica:", ["2D (Puntos y Fallas)", "2D (Clusters Agrupados)", "2D (Mapa de Calor)", "🌐 3D (Relieve y Profundidad)"])

    with c_mapa:
        if "2D" in modo:
            m = folium.Map(location=[-9.19, -75.01], zoom_start=5, tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png", attr="&copy; OpenStreetMap")
            folium.PolyLine(FOSA_PERU_CHILE, color="#1D3557", weight=3.5, tooltip="Fosa Perú-Chile").add_to(m)
            for f in FALLAS_ACTIVAS_PERU:
                folium.PolyLine(f["coords"], color="#7209B7", weight=3, dash_array="6, 6", tooltip=f"Falla {f['nombre']}").add_to(m)
            for dep, d_info in UBICACIONES_PERU.items():
                folium.Marker(location=d_info["coords"], tooltip=f"Zona Urbana: {dep}", icon=folium.Icon(color="green", icon="info-sign")).add_to(m)

            if modo == "2D (Puntos y Fallas)":
                for _, r in df_filtrado.iterrows():
                    folium.CircleMarker(
                        location=[r["latitud"], r["longitud"]],
                        radius=max(r["magnitud"] * 2.2, 3),
                        color=colores_hex.get(r["tipo_profundidad"], "#333"),
                        fill=True, fill_opacity=0.75,
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
            st.caption("Usa **Ctrl + Clic izquierdo** para inclinar la vista tridimensional.")
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

# --- TAB 2: VJ LIVE VISUALS & HYDRA SYNTH CONSOLA PRO ---
with tab_vj:
    st.subheader("🎛️ Consola VJ & Sintetizador Generativo Reactivo")
    st.markdown("Genera visuales en tiempo real modulados por datos sísmicos del Perú, ajusta sliders manuales (dimmers) o descarga las capturas para proyecciones.")
    
    if not df_filtrado.empty:
        # Estado de sesión para presets aleatorios
        if "vj_seed" not in st.session_state:
            st.session_state.vj_seed = 100
        
        # Selección del Sismo Modulador
        c_sel1, c_sel2 = st.columns([2.5, 1])
        with c_sel1:
            opciones_sismos = [f"{r['fecha_hora']} | M {r['magnitud']} - {r['referencia']}" for _, r in df_filtrado.head(40).iterrows()]
            sismo_sel_str = st.selectbox("🎯 Seleccionar Sismo Portador (Carrier Data):", opciones_sismos)
            idx_sel = opciones_sismos.index(sismo_sel_str)
            sismo_vj = df_filtrado.iloc[idx_sel]
        with c_sel2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🎲 Mutar / Randomizar Visual"):
                st.session_state.vj_seed = random.randint(1, 9999)
                st.rerun()

        st.markdown("---")

        # CONSOLA DE DIMMERS / SLIDERS MANUALES
        st.markdown("#### 🎚️ Rack de Control & Dimmers Audiovisuales")
        dim1, dim2, dim3, dim4, dim5 = st.columns(5)
        
        with dim1:
            modo_visual = st.selectbox(
                "Modo de Renderizado",
                ["Ondas Concéntricas (Pulsos)", "Malla de Placas (Partículas)", "Túnel Hipocentral (Vórtice)", "Espectro Glitch Tectónico"]
            )
        with dim2:
            dim_gain = st.slider("Ganancia Sísmica (Gain)", 0.2, 3.0, 1.0, 0.1, help="Multiplica la energía sísmica sobre el dibujo.")
        with dim3:
            dim_speed = st.slider("Velocidad de Fase (Speed)", 0.1, 5.0, 1.2, 0.1, help="Controla la tasa de refresco y movimiento.")
        with dim4:
            dim_trail = st.slider("Retroalimentación (Trail)", 0.01, 0.50, 0.15, 0.01, help="Persistencia de la imagen / Estela oscura.")
        with dim5:
            dim_noise = st.slider("Ruido Tectónico (Turbulence)", 0.0, 50.0, 15.0, 1.0, help="Deformación estocástica de las coordenadas.")

        # Inyección de datos sísmicos normalizados
        base_freq = float(sismo_vj["magnitud"]) * 3.5 * dim_gain
        base_speed = float(sismo_vj["magnitud"]) * 0.25 * dim_speed
        base_depth = float(sismo_vj["profundidad_km"]) / 25.0
        base_fosa = float(sismo_vj["distancia_fosa_km"]) / 40.0
        
        col_view, col_code = st.columns([1.7, 1.1])
        
        with col_view:
            st.markdown(f"#### 📺 Pantalla de Emisión: **{modo_visual}**")
            
            # Canvas Generativo WebGL / 2D con motor multicapa y descarga PNG nativa
            canvas_script = f"""
            <div style="background: #000; border-radius: 10px; padding: 12px; border: 1px solid #7209b7; text-align: center;">
                <canvas id="vjCanvas" width="700" height="420" style="width: 100%; border-radius: 6px;"></canvas>
                <div style="margin-top: 10px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #bbb; font-size: 12px; font-family: monospace;">Sismo: M {sismo_vj['magnitud']} | Prof: {sismo_vj['profundidad_km']}km | Seed: {st.session_state.vj_seed}</span>
                    <button onclick="downloadVisual()" style="background: #f72585; color: white; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-weight: bold;">💾 Guardar Captura (.PNG)</button>
                </div>
            </div>
            <script>
                const canvas = document.getElementById('vjCanvas');
                const ctx = canvas.getContext('2d');
                let t = {st.session_state.vj_seed};
                
                const mode = "{modo_visual}";
                const freq = {base_freq};
                const speed = {base_speed};
                const depth = {base_depth};
                const fosa = {base_fosa};
                const trail = {dim_trail};
                const noiseAmt = {dim_noise};

                // Inicializar partículas si es modo malla
                const particles = [];
                for(let i = 0; i < 70; i++) {{
                    particles.push({{
                        x: Math.random() * canvas.width,
                        y: Math.random() * canvas.height,
                        vx: (Math.random() - 0.5) * speed * 2,
                        vy: (Math.random() - 0.5) * speed * 2,
                        size: Math.random() * freq + 2
                    }});
                }}

                function draw() {{
                    t += 0.02 * speed;
                    
                    // Fondo con trail / feedback
                    ctx.fillStyle = `rgba(5, 3, 10, ${{trail}})`;
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    
                    const cx = canvas.width / 2;
                    const cy = canvas.height / 2;

                    if (mode === "Ondas Concéntricas (Pulsos)") {{
                        const rings = 10 + Math.floor(freq * 1.5);
                        for (let i = 0; i < rings; i++) {{
                            ctx.beginPath();
                            const rBase = (i * 20 + (t * 50) % 300);
                            for (let a = 0; a < Math.PI * 2; a += 0.15) {{
                                const wave = Math.sin(a * freq + t) * (depth * 3) + Math.cos(a * 4 - t) * noiseAmt;
                                const r = rBase + wave;
                                const x = cx + Math.cos(a) * r;
                                const y = cy + Math.sin(a) * r;
                                if (a === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                            }}
                            ctx.closePath();
                            ctx.strokeStyle = `hsl(${{(i * 30 + t * 60) % 360}}, 90%, 65%)`;
                            ctx.lineWidth = 1.5 + (depth > 6 ? 2 : 0.8);
                            ctx.stroke();
                        }}
                    }} 
                    else if (mode === "Malla de Placas (Partículas)") {{
                        for (let i = 0; i < particles.length; i++) {{
                            let p = particles[i];
                            p.x += p.vx;
                            p.y += p.vy;
                            if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
                            if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
                            
                            ctx.fillStyle = `hsl(${{(p.x + t * 40) % 360}}, 85%, 60%)`;
                            ctx.beginPath();
                            ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                            ctx.fill();

                            for (let j = i + 1; j < particles.length; j++) {{
                                let p2 = particles[j];
                                let dist = Math.hypot(p.x - p2.x, p.y - p2.y);
                                if (dist < 100 + noiseAmt) {{
                                    ctx.strokeStyle = `rgba(180, 50, 240, ${{1 - dist / 120}})`;
                                    ctx.lineWidth = 1;
                                    ctx.beginPath();
                                    ctx.moveTo(p.x, p.y);
                                    ctx.lineTo(p2.x, p2.y);
                                    ctx.stroke();
                                }}
                            }}
                        }}
                    }}
                    else if (mode === "Túnel Hipocentral (Vórtice)") {{
                        const spirals = 16;
                        for (let i = 0; i < spirals; i++) {{
                            ctx.beginPath();
                            const rad = Math.pow(i / spirals, 1.8) * (canvas.width * 0.6);
                            const rot = t * (i % 2 === 0 ? 1 : -1) * 0.8;
                            for (let a = 0; a < Math.PI * 2; a += 0.2) {{
                                const x = cx + Math.cos(a + rot) * (rad + Math.sin(a * 6 + t) * noiseAmt);
                                const y = cy + Math.sin(a + rot) * (rad + Math.cos(a * 6 - t) * depth);
                                if (a === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                            }}
                            ctx.closePath();
                            ctx.strokeStyle = `hsl(${{(i * 20 + t * 80) % 360}}, 100%, ${{50 + i * 2}}%)`;
                            ctx.lineWidth = 2;
                            ctx.stroke();
                        }}
                    }}
                    else if (mode === "Espectro Glitch Tectónico") {{
                        const bars = 32;
                        const w = canvas.width / bars;
                        for (let i = 0; i < bars; i++) {{
                            const h = Math.abs(Math.sin(i * 0.5 + t * 2) * (canvas.height * 0.8) * (freq / 15)) + (Math.random() * noiseAmt * 2);
                            const hue = (i * 12 + t * 100) % 360;
                            ctx.fillStyle = `hsl(${{hue}}, 90%, 55%)`;
                            ctx.fillRect(i * w, cy - h/2, w - 2, h);
                            
                            // Líneas horizontales de glitch
                            if (Math.random() > 0.85) {{
                                ctx.fillStyle = "rgba(255,255,255,0.7)";
                                ctx.fillRect(0, Math.random() * canvas.height, canvas.width, 2);
                            }}
                        }}
                    }}
                    requestAnimationFrame(draw);
                }}
                draw();

                function downloadVisual() {{
                    const link = document.createElement('a');
                    link.download = `sismo_visual_${{Date.now()}}.png`;
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                }}
            </script>
            """
            components.html(canvas_script, height=480)

        with col_code:
            st.markdown("#### ⚡ Parámetros Sísmicos Mapeados")
            st.code(f"""// Telemetría del Sismo Seleccionado
MAGNITUD:      {sismo_vj['magnitud']} M  -> Frecuencia: {base_freq:.1f}
PROFUNDIDAD:   {sismo_vj['profundidad_km']} km -> Deformación: {base_depth:.2f}
DISTANCIA FOSA:{sismo_vj['distancia_fosa_km']} km -> Modulador: {base_fosa:.2f}
ESTADO DIMMER: Gain={dim_gain}x | Speed={dim_speed}x | Noise={dim_noise}
            """, language="javascript")

            st.markdown("#### 🔮 Live Patch para Hydra Synth")
            st.caption("Copia y pega en [hydra.ojack.xyz](https://hydra.ojack.xyz):")
            
            if modo_visual == "Ondas Concéntricas (Pulsos)":
                hydra_patch = f"""// Patch Ondas Máquina Tierna - Sismo M {sismo_vj['magnitud']}
osc({base_freq:.1f}, {base_speed:.2f}, {base_depth:.2f})
  .modulate(noise({base_fosa:.2f}), () => Math.sin(time) * 0.5)
  .color(0.9, 0.2, 0.8)
  .kaleid({max(3, int(sismo_vj['magnitud']))})
  .rotate(0.1, 0.05)
  .out()"""
            elif modo_visual == "Malla de Placas (Partículas)":
                hydra_patch = f"""// Patch Voronoi Cortical - Sismo M {sismo_vj['magnitud']}
voronoi({base_freq:.1f}, {base_speed:.2f}, {dim_noise/10.0:.2f})
  .color(0.2, 0.8, 0.9)
  .modulatePixelate(noise({base_fosa:.2f}), 12)
  .add(osc(10, 0.1, 0.5), 0.3)
  .out()"""
            elif modo_visual == "Túnel Hipocentral (Vórtice)":
                hydra_patch = f"""// Patch Vórtice Wadati-Benioff - Prof {sismo_vj['profundidad_km']}km
shape({max(3, int(sismo_vj['magnitud']))}, 0.5, 0.01)
  .scale(() => 1 + Math.sin(time * {base_speed:.2f}) * 0.4)
  .repeat({int(base_depth + 4)}, {int(base_depth + 4)})
  .rotate(0.2, 0.1)
  .modulate(osc(8, 0.05))
  .out()"""
            else:
                hydra_patch = f"""// Patch Glitch Sismológico - Máquina Tierna
osc(40, {base_speed:.2f}, 1.5)
  .modulateScale(noise({base_fosa:.2f}), () => Math.sin(time * 3) * {dim_gain:.1f})
  .pixelate(32, 32)
  .color(1.0, 0.1, 0.6)
  .out()"""
                
            st.code(hydra_patch, language="javascript")
            st.markdown("#### 📡 Streaming OSC / Resolume / TouchDesigner")
            st.code(f"/maquinatierna/sismo [float:{sismo_vj['magnitud']}], [float:{sismo_vj['profundidad_km']}], [float:{dim_gain}]", language="text")

    else:
        st.info("No hay datos disponibles para generar visuales con los filtros seleccionados.")

# --- TAB 3: LÍNEA DE TIEMPO ---
with tab_timeline:
    st.subheader("Evolución Temporal de la Sismicidad")
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

# --- TAB 4: PROXIMIDAD Y TERRITORIO ---
with tab_territorio:
    st.subheader("Análisis Territorial y Cercanía Urbana")
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

# --- TAB 5: SUBDUCCIÓN ---
with tab_tectonica:
    st.subheader("Perfil de Subducción (Plano de Wadati-Benioff)")
    fig_benioff = px.scatter(
        df_filtrado, x="distancia_fosa_km", y="profundidad_km", size="magnitud",
        color="tipo_profundidad", hover_data=["referencia", "departamento"],
        color_discrete_map=colores_hex,
        title="Geometría del Plano de Subducción (Profundidad vs. Distancia a la Fosa)",
        labels={"distancia_fosa_km": "Distancia a la Fosa Marina (km)", "profundidad_km": "Profundidad Hipocentral (km)"}
    )
    fig_benioff.update_yaxes(autorange="reversed")
    st.plotly_chart(fig_benioff, width="stretch")

# --- TAB 6: FÍSICA Y ENERGÍA ---
with tab_energia:
    st.subheader("Física Sísmica y Energía Liberada")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        top_energia = df_filtrado.sort_values(by="energia_tnt_ton", ascending=False).head(12)
        fig_en = px.bar(
            top_energia, x="energia_tnt_ton", y="referencia", orientation="h", color="departamento",
            title="Top 12 Eventos con Mayor Energía (Toneladas de TNT)",
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

# --- TAB 7: RÉPLICAS Y ENJAMBRES ---
with tab_secuencias:
    st.subheader("Detección de Secuencias Sísmicas y Réplicas")
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

# --- TAB 8: PELIGRO SÍSMICO (B-VALUE) ---
with tab_gutenberg:
    st.subheader("Análisis de Esfuerzo Tectónico (b-value de Gutenberg-Richter)")
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

# --- TAB 9: QGIS ---
with tab_qgis:
    st.subheader("Exportación de Datos Geoespaciales")
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

# Pie de página
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #888; font-size: 0.85rem;'>"
    "Desarrollado por <b>Arolt</b> para <b>Máquina Tierna</b> | "
    "<a href='https://instagram.com/maquinatierna' target='_blank' style='color:#7209b7;'>Instagram @maquinatierna</a> | "
    "<a href='https://instagram.com/arolt23' target='_blank' style='color:#7209b7;'>Instagram @arolt23</a>"
    "</div>",
    unsafe_allow_html=True
)