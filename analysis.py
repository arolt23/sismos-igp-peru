import numpy as np

def calcular_energia_joules(magnitud):
    """
    Calcula la energía sísmica liberada en Joules usando la relación de Gutenberg-Richter:
    log10(E) = 4.8 + 1.5 * M
    """
    log_e = 4.8 + (1.5 * float(magnitud))
    energia_joules = 10 ** log_e
    toneladas_tnt = energia_joules / (4.184 * 10**9)
    return energia_joules, toneladas_tnt

def estimar_radio_percepcion_km(magnitud, profundidad_km):
    """
    Estima el radio superficial (km) de percepción del sismo considerando la atenuación geométrica.
    """
    # Modelo simplificado de atenuación cortical
    distancia_hipocentral_max = 10 ** (0.43 * float(magnitud) + 0.5)
    
    if distancia_hipocentral_max > float(profundidad_km):
        radio_superficial = np.sqrt(distancia_hipocentral_max**2 - float(profundidad_km)**2)
    else:
        radio_superficial = 5.0
        
    return round(float(radio_superficial), 1)

def clasificar_alerta_riesgo(magnitud, distancia_poblado_km, profundidad_km):
    """
    Determina el nivel de riesgo para la población más cercana.
    """
    if magnitud >= 7.0 and distancia_poblado_km <= 100 and profundidad_km <= 60:
        return "ALERTA CRÍTICA (Peligro Muy Alto)"
    elif magnitud >= 6.0 and distancia_poblado_km <= 150 and profundidad_km <= 80:
        return "ALERTA ROJA (Potencialmente Destructivo)"
    elif magnitud >= 5.0 and distancia_poblado_km <= 100:
        return "ALERTA AMARILLA (Moderado / Sentido Fuerte)"
    return "ALERTA VERDE (Bajo Impacto Inmediato)"