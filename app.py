import os
import base64
import io
import serial
import threading
import json
import re
import unicodedata   # 👈 para normalizar en Python
from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
from openai import OpenAI

# === Configuración ===
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__, static_folder="static", template_folder="templates")

# === Serial con ESP32 ===
ser = serial.Serial("/dev/cu.usbserial-0001", 115200, timeout=1)
eventos = []
event_id = 0

def leer_serial():
    global event_id
    while True:
        try:
            line = ser.readline().decode().strip()
            if line:
                try:
                    data = json.loads(line.replace("ESP32 → ", ""))
                    event_id += 1
                    data["id"] = event_id
                    eventos.append(data)
                    print("ESP32 →", data)
                except Exception as e:
                    print("Error parseando:", e, line)
        except Exception as e:
            print("Error leyendo serial:", e)

hilo = threading.Thread(target=leer_serial, daemon=True)
hilo.start()

# === Emociones permitidas ===
TARGET_EMOTIONS = ["Furia", "Desagrado", "Temor", "Alegria", "Tristeza"]

# === Función para limpiar y normalizar ===
def normalizar_emocion(texto):
    if not texto:
        return ""
    # Quitar acentos con unicodedata
    texto = unicodedata.normalize("NFD", texto)
    texto = texto.encode("ascii", "ignore").decode("utf-8")
    # Pasar a minúsculas y quitar puntuación
    texto = re.sub(r"[^\w\s]", "", texto).strip().lower()
    # Capitalizar
    return texto.capitalize()

# === Rutas Flask ===

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/estado")
def estado():
    if eventos:
        return jsonify({"last_event": eventos[-1]})
    return jsonify({"last_event": None})

@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()
        image_b64 = data["image"].split(",")[1]
        image_bytes = base64.b64decode(image_b64)

        prompt = (
            "Eres un experto en reconocimiento de emociones faciales. "
            "Mira SOLO el rostro de la persona en la imagen y responde con la emoción predominante. "
            "Elige estrictamente UNA entre estas categorías: Furia, Desagrado, Temor, Alegria, Tristeza. "
            "No inventes otras palabras ni expliques. Responde solo con la palabra exacta."
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
                            }
                        }
                    ],
                }
            ],
        )

        emotion_raw = response.choices[0].message.content.strip()
        emotion_clean = normalizar_emocion(emotion_raw)

        if emotion_clean not in TARGET_EMOTIONS:
            print("⚠️ OpenAI devolvió algo fuera de rango:", emotion_raw)
            emotion_clean = "Desconocida"

        return jsonify({"emotion": emotion_clean})

    except Exception as e:
        print("Error en /predict:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/speak", methods=["POST"])
def speak():
    data = request.get_json()
    texto = data.get("text", "")

    try:
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="shimmer",
            input=texto
        )

        audio_bytes = response.read()
        return send_file(
            io.BytesIO(audio_bytes),
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="voz.mp3"
        )

    except Exception as e:
        print("Error en TTS:", e)
        return jsonify({"error": str(e)}), 500

# === Run ===
if __name__ == "__main__":
    print("✅ Conectado a", ser.port)
    app.run(host="0.0.0.0", port=8080)