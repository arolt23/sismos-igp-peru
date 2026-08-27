import numpy as np
import requests
from datetime import datetime, timezone

def calcular_energia_joules(magnitud):
    log_e = 4.8 + (1.5 * float(magnitud))
    energia_joules = 10 ** log_e
    toneladas_tnt = energia_joules / (4.184 * 10**9)
    return energia_joules, toneladas_tnt

def estimar_radio_percepcion_km(magnitud, profundidad_km):
    distancia_hipocentral_max = 10 ** (0.43 * float(magnitud) + 0.5)
    if distancia_hipocentral_max > float(profundidad_km):
        radio_superficial = np.sqrt(distancia_hipocentral_max**2 - float(profundidad_km)**2)
    else:
        radio_superficial = 5.0
    return round(float(radio_superficial), 1)

def clasificar_alerta_riesgo(magnitud, distancia_poblado_km, profundidad_km):
    if magnitud >= 7.0 and distancia_poblado_km <= 100 and profundidad_km <= 60:
        return "ALERTA CRÍTICA (Peligro Muy Alto)"
    elif magnitud >= 6.0 and distancia_poblado_km <= 150 and profundidad_km <= 80:
        return "ALERTA ROJA (Potencialmente Destructivo)"
    elif magnitud >= 5.0 and distancia_poblado_km <= 100:
        return "ALERTA AMARILLA (Moderado / Sentido Fuerte)"
    return "ALERTA VERDE (Bajo Impacto Inmediato)"

def calcular_b_value_departamento(df_dep, mc=4.2):
    """
    Calcula el b-value usando el estimador de máxima verosimilitud de Aki (1965):
    b = log10(e) / (mean(M) - (Mc - bin_width/2))
    """
    mags = df_dep[df_dep["magnitud"] >= mc]["magnitud"].values
    if len(mags) < 15:
        return None, "Datos insuficientes (< 15 eventos >= Mc)"
    
    m_prom = np.mean(mags)
    bin_width = 0.1
    b_val = np.log10(np.e) / (m_prom - (mc - bin_width / 2.0))
    b_val = round(float(b_val), 2)
    
    if b_val < 0.85:
        estado = "Crítico: Tensión acumulada severa (Aspereza tectónica)"
    elif b_val <= 1.05:
        estado = "Normal: Régimen de liberación estándar"
    else:
        estado = "Bajo: Predominio de microsismicidad / Enjambres"
        
    return b_val, estado

def enviar_alerta_telegram(bot_token, chat_id, sismo_info):
    """Envía un mensaje formateado a un canal/chat de Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    mensaje = (
        f"🚨 *ALERTA SÍSMICA IGP - PERÚ*\n\n"
        f"📍 *Referencia:* {sismo_info['referencia']}\n"
        f"⚡ *Magnitud:* {sismo_info['magnitud']} M\n"
        f"📏 *Profundidad:* {sismo_info['profundidad_km']} km\n"
        f"🏙️ *Cercanía:* A {sismo_info['distancia_poblado_km']} km de {sismo_info['departamento']}\n"
        f"⚠️ *Nivel:* {sismo_info['nivel_riesgo']}\n"
        f"🕒 *Fecha/Hora:* {sismo_info['fecha_hora']}"
    )
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except Exception:
        return False