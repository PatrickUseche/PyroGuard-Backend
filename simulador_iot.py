import requests
import time
import random
from datetime import datetime, timezone

API_URL = "https://pyroguard-backend.onrender.com/api/readings/"
NODE_ID = "NODE-001"
INTERVAL_SECONDS = 5

def generate_simulated_data():
    """Genera datos aleatorios que simulan la lectura de los sensores."""
    # Se simula variaciones normales de temperatura y humedad.
    temperature = round(random.uniform(15.0, 35.0), 1)
    humidity = round(random.uniform(40.0, 80.0), 1)
    
    # Se simula niveles bajos de humo (condicion normal).
    smoke = round(random. uniform(10.0, 30.0), 1)
    
    # 5% de probabilidad de simular un incendio para pruebas.
    flame = random.random() < 0.05
    if flame: 
        temperature += 20.0 # Se sube la temperatura dramaticamente.
        smoke += 60.0 # Se sube el humo dramaticamente.
    
    timestamp = datetime.now(timezone.utc).isoformat()
    
    return {
        "node_id": NODE_ID,
        "temperature": temperature,
        "humidity": humidity,
        "smoke": smoke,
        "flame": flame,
        "timestamp": timestamp
    }
    
def send_data():
    """Bucle principal que envia datos continuamente a la API."""
    print(f"Iniciando simulador IoT para el nodo {NODE_ID}")
    print(f"Enviando datos a {API_URL} cada {INTERVAL_SECONDS} segundos...")
    print("-" * 40)
    
    try:
        while True:
            payload = generate_simulated_data()
            print(f"Enviando: Temperatura: {payload['temperature']}°C | Humedad: {payload['humidity']}% | Humo: {payload['smoke']} | Llama: {payload['flame']}")
            
            try: 
                response = requests.post(API_URL, json = payload)
                if response.status_code == 201:
                    print("ENVIO EXITOSO")
                else:
                    print("Error en el envio. Codigo: {response.status_code}. Detalles: {responde.text}")
            except requests.exceptions.RequestException as error:
                print("No se pudo conectar al servidor. ¿Esta encendido? Detalle: {error}")
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nSimulador detenido por el usuario.")

if __name__ == "__main__":
    send_data()