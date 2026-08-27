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
    .credit-box a { color: #4cc9f0; text-decoration: none; font-weight: bold; }
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
    
    deps, provs, dists, energias, radios, alertas, dist_fosas, regiones = [], [], [], [], [], [], [], []
    for _, row in df_total.iterrows():
        d, p, dist = asignar_ubicacion_administrativa(row["latitud"], row["longitud"])
        deps.append(row.get("departamento", d) if pd.notna(row.get("departamento")) else d)
        provs.append(p)
        dists.append(dist)
        
        _, tnt = calcular_energia_joules(row["magnitud"])
        energias.append(round(tnt, 2))
        
        radios.append(estimar_radio_percepcion_km(row["magnitud"], row["profundidad_km"]))
        alertas.append(clasificar_alerta_riesgo(row["magnitud"], dist, row["profundidad_km"]))
        
        d_fosa = calcular_distancia_fosa_km(row["latitud"], row["longitud"])
        dist_fosas.append(d_fosa)
        
        # Sectorización Morfodinámica
        if row["profundidad_km"] <= 60 and d_fosa <= 220:
            regiones.append("Costa (Frente de Subducción)")
        elif row["profundidad_km"] <= 150:
            regiones.append("Sierra (Fallas Corticales)")
        else:
            regiones.append("Selva / Manto Profundo")
        
    df_total["departamento"] = deps
    df_total["provincia_cercana"] = provs
    df_total["distancia_poblado_km"] = dists
    df_total["energia_tnt_ton"] = energias
    df_total["radio_afectacion_km"] = radios
    df_total["nivel_riesgo"] = alertas
    df_total["distancia_fosa_km"] = dist_fosas
    df_total["region_tectonica"] = regiones
    
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

st.title("🇵🇪 Plataforma Sismotectónica & Live VJ Core - IGP")
st.caption("Desarrollado por Arolt para **Máquina Tierna** | Monitoreo territorial y síntesis generativa reactiva.")

# Filtros laterales
st.sidebar.header("📍 Filtros Territoriales")
deps_list = sorted(list(df_master["departamento"].unique()))
dep_sel = st.sidebar.multiselect("Departamentos", options=deps_list, default=deps_list)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Filtros Físicos")
mag_rango = st.sidebar.slider("Rango de Magnitud (M)", 3.5, 8.5, (4.0, 8.5), step=0.1)
prof_rango = st.sidebar.slider("Rango de Profundidad (km)", 0, 700, (0, 700), step=10)
rango_anios = st.sidebar.slider("Periodo (Años)", int(df_master["anio"].min()), int(df_master["anio"].max()), (1970, 2026))

df_filtrado = df_master[
    (df_master["departamento"].isin(dep_sel)) &
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

tab_vj, tab_mapas, tab_timeline, tab_territorio, tab_tectonica, tab_energia, tab_secuencias, tab_gutenberg, tab_qgis = st.tabs([
    "🎛️ VJ Multi-Región & Hydra Core",
    "🗺️ Visor Cartográfico",
    "⏳ Línea de Tiempo",
    "🏙️ Proximidad Urbana",
    "🌊 Subducción (Wadati-Benioff)",
    "💥 Física y Energía",
    "🔁 Réplicas y Enjambres",
    "📈 Peligro Sísmico (b-value)",
    "📐 QGIS / GeoJSON"
])

# ==================== TAB VJ: MULTI-REGIÓN & FAST CLIENT DIMMERS ====================
with tab_vj:
    st.subheader("🎛️ Matriz Visual Sísmica: Síntesis Multi-Región a 60 FPS")
    st.markdown("Ajusta los dimmers en tiempo real (renderizado directo en GPU/Canvas sin recargar la app) y copia los parches de Hydra específicos por cada contexto tectónico regional.")

    # Agrupar el sismo más representativo de cada región
    regiones_disponibles = ["Costa (Frente de Subducción)", "Sierra (Fallas Corticales)", "Selva / Manto Profundo"]
    sismos_regionales = {}
    for reg in regiones_disponibles:
        sub = df_filtrado[df_filtrado["region_tectonica"] == reg]
        if not sub.empty:
            sismos_regionales[reg] = sub.iloc[0].to_dict()
        else:
            sub_global = df_master[df_master["region_tectonica"] == reg]
            sismos_regionales[reg] = sub_global.iloc[0].to_dict() if not sub_global.empty else df_master.iloc[0].to_dict()

    s_costa = sismos_regionales["Costa (Frente de Subducción)"]
    s_sierra = sismos_regionales["Sierra (Fallas Corticales)"]
    s_selva = sismos_regionales["Selva / Manto Profundo"]

    # Componente integrado de Ultra-Baja Latencia con Dimmers en JS
    vj_multicanal_html = f"""
    <div style="background: #0d0b14; padding: 15px; border-radius: 10px; border: 1px solid #7209b7; color: white; font-family: sans-serif;">
        <!-- CONTROLES NATIVOS EN JS (SIN RECARGAS DE STREAMLIT) -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; background: #181528; padding: 12px; border-radius: 8px; margin-bottom: 15px;">
            <div>
                <label style="font-size: 11px; color: #f72585; font-weight: bold;">CANAL REGIONAL:</label><br>
                <select id="channelSelect" style="width: 100%; background: #0a0812; color: #4cc9f0; border: 1px solid #7209b7; border-radius: 4px; padding: 4px; margin-top: 4px;">
                    <option value="costa">🌊 Costa (Subducción Nazca) - M {s_costa['magnitud']}</option>
                    <option value="sierra">⛰️ Sierra (Fallas Activas) - M {s_sierra['magnitud']}</option>
                    <option value="selva">🌴 Selva (Manto Profundo) - M {s_selva['magnitud']}</option>
                    <option value="triptico">⚡ Tríptico Multi-Canal (Simultáneo)</option>
                </select>
            </div>
            <div>
                <label style="font-size: 11px; color: #4cc9f0; font-weight: bold;">GANANCIA SÍSMICA (GAIN): <span id="val_gain">1.0</span>x</label>
                <input type="range" id="dim_gain" min="0.2" max="3.0" step="0.1" value="1.0" style="width: 100%;">
            </div>
            <div>
                <label style="font-size: 11px; color: #4cc9f0; font-weight: bold;">VELOCIDAD DE FASE: <span id="val_speed">1.0</span>x</label>
                <input type="range" id="dim_speed" min="0.1" max="4.0" step="0.1" value="1.0" style="width: 100%;">
            </div>
            <div>
                <label style="font-size: 11px; color: #4cc9f0; font-weight: bold;">RETROALIMENTACIÓN (TRAIL): <span id="val_trail">0.15</span></label>
                <input type="range" id="dim_trail" min="0.01" max="0.45" step="0.01" value="0.15" style="width: 100%;">
            </div>
            <div>
                <label style="font-size: 11px; color: #4cc9f0; font-weight: bold;">RUIDO TECTÓNICO: <span id="val_noise">15</span></label>
                <input type="range" id="dim_noise" min="0" max="40" step="1" value="15" style="width: 100%;">
            </div>
        </div>

        <canvas id="vjMaster" width="960" height="420" style="width: 100%; border-radius: 6px; background: #000; display: block;"></canvas>
        
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px;">
            <span id="telemetry" style="font-family: monospace; font-size: 12px; color: #aaa;">Telemetría activa: Costa (M {s_costa['magnitud']} | Prof {s_costa['profundidad_km']}km)</span>
            <button onclick="downloadCapture()" style="background: #f72585; color: white; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-weight: bold;">💾 Guardar Captura PNG</button>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('vjMaster');
        const ctx = canvas.getContext('2d');
        
        // Datos por región inyectados
        const datasets = {{
            costa: {{ mag: {s_costa['magnitud']}, prof: {s_costa['profundidad_km']}, ref: "{s_costa['referencia']}", fosa: {s_costa['distancia_fosa_km']} }},
            sierra: {{ mag: {s_sierra['magnitud']}, prof: {s_sierra['profundidad_km']}, ref: "{s_sierra['referencia']}", fosa: {s_sierra['distancia_fosa_km']} }},
            selva: {{ mag: {s_selva['magnitud']}, prof: {s_selva['profundidad_km']}, ref: "{s_selva['referencia']}", fosa: {s_selva['distancia_fosa_km']} }}
        }};

        let t = 0;
        const sel = document.getElementById('channelSelect');
        const dGain = document.getElementById('dim_gain');
        const dSpeed = document.getElementById('dim_speed');
        const dTrail = document.getElementById('dim_trail');
        const dNoise = document.getElementById('dim_noise');

        // Actualización numérica de labels instantánea
        dGain.oninput = () => document.getElementById('val_gain').innerText = dGain.value;
        dSpeed.oninput = () => document.getElementById('val_speed').innerText = dSpeed.value;
        dTrail.oninput = () => document.getElementById('val_trail').innerText = dTrail.value;
        dNoise.oninput = () => document.getElementById('val_noise').innerText = dNoise.value;

        function renderSubVisual(cx, cy, w, h, data, modeName) {{
            const freq = data.mag * 3.2 * parseFloat(dGain.value);
            const depth = data.prof / 20.0;
            const noise = parseFloat(dNoise.value);

            ctx.save();
            ctx.beginPath();
            ctx.rect(cx - w/2, cy - h/2, w, h);
            ctx.clip();

            if (modeName === 'costa') {{
                // Ondas concéntricas de subducción marina
                const rings = 8 + Math.floor(freq);
                for (let i = 0; i < rings; i++) {{
                    ctx.beginPath();
                    const rBase = (i * 18 + (t * 50) % 200);
                    for (let a = 0; a < Math.PI * 2; a += 0.15) {{
                        const wave = Math.sin(a * freq + t) * depth + Math.cos(a * 4 - t) * (noise * 0.5);
                        const r = rBase + wave;
                        const x = cx + Math.cos(a) * r;
                        const y = cy + Math.sin(a) * r;
                        if (a === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                    }}
                    ctx.closePath();
                    ctx.strokeStyle = `hsl(${{(i * 20 + t * 40) % 360}}, 90%, 65%)`;
                    ctx.lineWidth = 1.8;
                    ctx.stroke();
                }}
            }} else if (modeName === 'sierra') {{
                // Malla de fallas corticales y picos escarpados
                const lines = 12;
                for (let i = 0; i < lines; i++) {{
                    ctx.beginPath();
                    const yPos = cy - h/2 + (i * (h / lines));
                    for (let x = cx - w/2; x < cx + w/2; x += 10) {{
                        const yOffset = Math.sin(x * 0.03 * freq + t) * (depth * 2) + (Math.random() - 0.5) * noise;
                        if (x === cx - w/2) ctx.moveTo(x, yPos + yOffset);
                        else ctx.lineTo(x, yPos + yOffset);
                    }}
                    ctx.strokeStyle = `hsl(${{(i * 30 + 120) % 360}}, 85%, 60%)`;
                    ctx.lineWidth = 1.5;
                    ctx.stroke();
                }}
            }} else {{
                // Vórtice profundo del manto
                const spirals = 10;
                for (let i = 0; i < spirals; i++) {{
                    ctx.beginPath();
                    const rad = Math.pow(i / spirals, 1.6) * (w * 0.45);
                    const rot = t * (i % 2 === 0 ? 1 : -1) * 0.7;
                    for (let a = 0; a < Math.PI * 2; a += 0.2) {{
                        const x = cx + Math.cos(a + rot) * (rad + Math.sin(a * 5 + t) * noise);
                        const y = cy + Math.sin(a + rot) * (rad + Math.cos(a * 5 - t) * depth);
                        if (a === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                    }}
                    ctx.closePath();
                    ctx.strokeStyle = `hsl(${{(i * 25 + t * 60 + 200) % 360}}, 95%, 55%)`;
                    ctx.lineWidth = 2;
                    ctx.stroke();
                }}
            }}
            ctx.restore();
        }}

        function loop() {{
            const spd = parseFloat(dSpeed.value);
            t += 0.02 * spd;
            
            ctx.fillStyle = `rgba(5, 3, 10, ${{parseFloat(dTrail.value)}})`;
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const mode = sel.value;
            const telem = document.getElementById('telemetry');

            if (mode === 'triptico') {{
                const w3 = canvas.width / 3;
                renderSubVisual(w3 * 0.5, canvas.height/2, w3 - 10, canvas.height, datasets.costa, 'costa');
                renderSubVisual(w3 * 1.5, canvas.height/2, w3 - 10, canvas.height, datasets.sierra, 'sierra');
                renderSubVisual(w3 * 2.5, canvas.height/2, w3 - 10, canvas.height, datasets.selva, 'selva');
                telem.innerText = `Tríptico Simultáneo: Costa (M${{datasets.costa.mag}}) | Sierra (M${{datasets.sierra.mag}}) | Selva (M${{datasets.selva.mag}})`;
            }} else {{
                renderSubVisual(canvas.width/2, canvas.height/2, canvas.width, canvas.height, datasets[mode], mode);
                telem.innerText = `Canal Activo: ${{mode.toUpperCase()}} (${{datasets[mode].ref}} | M ${{datasets[mode].mag}} | Prof ${{datasets[mode].prof}} km)`;
            }}

            requestAnimationFrame(loop);
        }}
        loop();

        function downloadCapture() {{
            const link = document.createElement('a');
            link.download = `vj_sismos_peru_${{Date.now()}}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        }}
    </script>
    """
    components.html(vj_multicanal_html, height=550)

    # CÓDIGO HYDRA DIFERENCIADO POR REGIÓN
    st.markdown("### 🔮 Patches de Hydra Synth por Dominio Tectónico")
    st.caption("Copia estos parches directamente en [hydra.ojack.xyz](https://hydra.ojack.xyz):")
    
    col_h1, col_h2, col_h3 = st.columns(3)
    
    with col_h1:
        st.markdown(f"**🌊 Costa (Subducción Nazca)**\n\n*Ref: {s_costa['referencia']} (M {s_costa['magnitud']})*")
        st.code(f"""// 1. Costa: Frecuencia de Ondas Marinas
osc({float(s_costa['magnitud'])*3.5:.1f}, 0.2, {float(s_costa['profundidad_km'])/20.0:.2f})
  .modulate(noise({float(s_costa['distancia_fosa_km'])/40.0:.2f}), () => Math.sin(time)*0.4)
  .color(0.1, 0.6, 0.9)
  .kaleid({max(3, int(s_costa['magnitud']))})
  .rotate(0.1, 0.05)
  .out(o0)""", language="javascript")

    with col_h2:
        st.markdown(f"**⛰️ Sierra (Fallas Corticales)**\n\n*Ref: {s_sierra['referencia']} (M {s_sierra['magnitud']})*")
        st.code(f"""// 2. Sierra: Malla Geológica Voronoi
voronoi({float(s_sierra['magnitud'])*4.0:.1f}, 0.3, 1.5)
  .color(0.9, 0.3, 0.1)
  .modulatePixelate(noise({float(s_sierra['profundidad_km'])/10.0:.2f}), 16)
  .add(osc(12, 0.1, 0.8), 0.3)
  .out(o1)""", language="javascript")

    with col_h3:
        st.markdown(f"**🌴 Selva (Manto Profundo)**\n\n*Ref: {s_selva['referencia']} (M {s_selva['magnitud']})*")
        st.code(f"""// 3. Selva: Vórtice de Hipocentro Profundo
shape({max(3, int(s_selva['magnitud']))}, 0.6, 0.01)
  .scale(() => 1 + Math.sin(time*0.5)*0.3)
  .repeat({int(s_selva['profundidad_km']/40 + 3)}, {int(s_selva['profundidad_km']/40 + 3)})
  .rotate(0.2, 0.1)
  .modulate(osc(6, 0.05))
  .color(0.8, 0.1, 0.9)
  .out(o2)""", language="javascript")

# --- TAB MAPAS 2D / 3D ---
with tab_mapas:
    c_mapa, c_leyenda = st.columns([3, 1])
    with c_leyenda:
        st.markdown("### 📖 Leyenda")
        st.markdown("""
        * 🔴 **Superficial (0-60 km)**
        * 🟠 **Intermedio (61-300 km)**
        * 🔵 **Profundo (>300 km)**
        * 🟦 **Fosa Perú-Chile**
        * 🟪 **Fallas INGEMMET**
        """)
        modo = st.radio("Capa Cartográfica:", ["2D (Puntos y Fallas)", "2D (Clusters)", "2D (Mapa de Calor)", "🌐 3D (PyDeck)"])

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
                        popup=f"<b>{r['referencia']}</b><br>M: {r['magnitud']} | Prof: {r['profundidad_km']} km<br>Región: {r['region_tectonica']}"
                    ).add_to(m)
            elif modo == "2D (Clusters)":
                cluster = MarkerCluster().add_to(m)
                for _, r in df_filtrado.iterrows():
                    folium.CircleMarker(
                        location=[r["latitud"], r["longitud"]], radius=max(r["magnitud"] * 2.2, 3),
                        color=colores_hex.get(r["tipo_profundidad"], "#333"), fill=True, fill_opacity=0.8,
                        popup=f"<b>{r['referencia']}</b> ({r['magnitud']} M)"
                    ).add_to(cluster)
            else:
                heat_points = [[r["latitud"], r["longitud"], r["magnitud"]] for _, r in df_filtrado.iterrows()]
                HeatMap(heat_points, radius=22, blur=14, max_zoom=7).add_to(m)
                
            st_folium(m, width=None, height=520, returned_objects=[])
        else:
            df_filtrado["deck_color"] = df_filtrado["tipo_profundidad"].apply(
                lambda t: [230, 57, 70, 180] if "Superficial" in t else ([244, 162, 97, 180] if "Intermedio" in t else [42, 157, 143, 180])
            )
            layer_3d = pdk.Layer(
                "ColumnLayer", data=df_filtrado, get_position=["longitud", "latitud"],
                get_elevation="profundidad_km", elevation_scale=1500, radius=7500,
                get_fill_color="deck_color", pickable=True
            )
            st.pydeck_chart(pdk.Deck(
                layers=[layer_3d], initial_view_state=pdk.ViewState(latitude=-12.04, longitude=-75.50, zoom=5.1, pitch=50, bearing=-15),
                tooltip={"html": "<b>{referencia}</b><br/>M: {magnitud} | Profundidad: {profundidad_km} km"}
            ))

# --- TAB LÍNEA DE TIEMPO ---
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
            df_dest, x="fecha_hora", y="magnitud", color="departamento", hover_data=["impacto", "referencia"],
            title="Terremotos Históricos de Gran Impacto", labels={"fecha_hora": "Fecha", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_dest, width="stretch")

# --- TAB PROXIMIDAD Y TERRITORIO ---
with tab_territorio:
    st.subheader("Análisis Territorial y Cercanía Urbana")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        fig_dist_prof = px.scatter(
            df_filtrado, x="distancia_poblado_km", y="profundidad_km", size="magnitud",
            color="tipo_profundidad", hover_data=["referencia", "departamento", "provincia_cercana"],
            color_discrete_map=colores_hex, title="Distancia a Población vs. Profundidad del Hipocentro",
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

# --- TAB SUBDUCCIÓN ---
with tab_tectonica:
    st.subheader("Perfil de Subducción (Plano de Wadati-Benioff)")
    fig_benioff = px.scatter(
        df_filtrado, x="distancia_fosa_km", y="profundidad_km", size="magnitud",
        color="tipo_profundidad", hover_data=["referencia", "departamento"],
        color_discrete_map=colores_hex, title="Geometría del Plano de Subducción (Profundidad vs. Distancia a la Fosa)",
        labels={"distancia_fosa_km": "Distancia a la Fosa Marina (km)", "profundidad_km": "Profundidad Hipocentral (km)"}
    )
    fig_benioff.update_yaxes(autorange="reversed")
    st.plotly_chart(fig_benioff, width="stretch")

# --- TAB FÍSICA Y ENERGÍA ---
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
            color_discrete_map=colores_hex, title="Radio de Percepción Superficial Estimado",
            labels={"radio_afectacion_km": "Radio de Afectación (km)", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_rad, width="stretch")

# --- TAB RÉPLICAS Y ENJAMBRES ---
with tab_secuencias:
    st.subheader("Detección de Secuencias Sísmicas y Réplicas")
    df_sec = df_filtrado[df_filtrado["id_secuencia"] != "None"]
    if not df_sec.empty:
        fig_sec = px.scatter(
            df_sec, x="fecha_hora", y="magnitud", color="rol_evento", symbol="id_secuencia", size="magnitud",
            hover_data=["referencia", "id_secuencia"], title="Secuencias Agrupadas (Sismo Principal vs. Réplicas)",
            labels={"fecha_hora": "Fecha", "magnitud": "Magnitud (M)"}
        )
        st.plotly_chart(fig_sec, width="stretch")
        st.dataframe(df_sec[["fecha_hora", "id_secuencia", "rol_evento", "magnitud", "profundidad_km", "referencia"]], width="stretch")
    else:
        st.info("No se detectaron secuencias de sismo principal y réplicas con los filtros actuales.")

# --- TAB PELIGRO SÍSMICO (B-VALUE) ---
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

# --- TAB QGIS ---
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
                    "region": r["region_tectonica"],
                    "departamento": r["departamento"],
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

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #888; font-size: 0.85rem;'>"
    "Desarrollado por <b>Arolt</b> para <b>Máquina Tierna</b> | "
    "<a href='https://instagram.com/maquinatierna' target='_blank' style='color:#7209b7;'>Instagram @maquinatierna</a> | "
    "<a href='https://instagram.com/arolt23' target='_blank' style='color:#7209b7;'>Instagram @arolt23</a>"
    "</div>",
    unsafe_allow_html=True
)