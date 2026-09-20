import os
import json
import traceback
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from groq import Groq

import requests

app = Flask(__name__)

MODEL = "openai/gpt-oss-120b"
WEB_MODEL = "groq/compound"

MEMORY_FILE = "data/kyvon_memory.json"
ERROR_LOG = "data/kyvon_errors.log"
REPAIR_LOG = "data/kyvon_repairs.json"

os.makedirs("data", exist_ok=True)

API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY was not found. "
        "Make sure your GitHub Codespaces secret is configured."
    )

client = Groq(api_key=API_KEY)


# ============================================================
# MEMORY
# ============================================================

def load_memory():
    try:
        if not os.path.exists(MEMORY_FILE):
            return []

        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception:
        return []


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=4)


memory = load_memory()


def add_memory(text):
    global memory

    memory.append({
        "date": datetime.now().isoformat(),
        "memory": text
    })

    memory = memory[-100:]

    save_memory(memory)


def memory_text():
    if not memory:
        return "No saved memories."

    return "\n".join(
        f"- {item.get('memory', '')}"
        for item in memory[-20:]
    )


# ============================================================
# ERROR LOGGING
# ============================================================

def log_error(error_type, message, details=""):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write("=" * 70 + "\n")
            f.write(f"TIME: {datetime.now().isoformat()}\n")
            f.write(f"TYPE: {error_type}\n")
            f.write(f"MESSAGE: {message}\n")
            f.write(f"DETAILS:\n{details}\n")

    except Exception:
        pass


# ============================================================
# LOCATION / WEATHER
# ============================================================

def get_location(latitude, longitude):

    try:
        # Reverse geocode coordinates using OpenStreetMap/Nominatim
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "zoom": 10
            },
            headers={
                "User-Agent": "KYVON-Personal-Assistant"
            },
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        address = data.get("address", {})

        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or "Unknown"
        )

        state = (
            address.get("state")
            or ""
        )

        country = (
            address.get("country")
            or ""
        )

        return {
            "city": city,
            "state": state,
            "country": country,
            "display": ", ".join(
                part for part in [city, state, country]
                if part
            )
        }

    except Exception as error:

        log_error(
            "Location Error",
            str(error),
            traceback.format_exc()
        )

        return {
            "city": "Unknown",
            "state": "",
            "country": "",
            "display": "Unknown location"
        }


def get_weather(latitude, longitude):

    try:

        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "apparent_temperature,"
                    "precipitation,"
                    "weather_code,"
                    "wind_speed_10m"
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto"
            },
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        current = data.get("current", {})

        weather_codes = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail"
        }

        code = current.get("weather_code")

        return {
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind": current.get("wind_speed_10m"),
            "condition": weather_codes.get(
                code,
                "Unknown conditions"
            ),
            "time": current.get("time"),
            "timezone": data.get("timezone")
        }

    except Exception as error:

        log_error(
            "Weather Error",
            str(error),
            traceback.format_exc()
        )

        raise


# ============================================================
# KYVON SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are KYVON, a personal AI assistant.

Personality:
- Intelligent
- Calm
- Professional
- Slightly futuristic
- Helpful
- Occasionally humorous
- Natural conversational style

You are assisting the user through a personal KYVON application.

Capabilities:
- Answer questions
- Explain things
- Help with coding
- Help troubleshoot problems
- Research information
- Remember information the user asks you to remember
- Help plan projects
- Analyze errors
- Access the user's current location when permission is granted
- Access real current weather information
- Access real local time information

Important rules:

1. Never claim to have performed an action that you did not actually perform.

2. Never claim unrestricted control of iOS or iPadOS.

3. Apple limits what third-party applications can access.

4. If something requires Apple Shortcuts or another bridge,
   explain that requirement.

5. Never reveal API keys or secrets.

6. Never execute arbitrary AI-generated code automatically.

7. Be honest about your capabilities.

8. When real location, weather, or time information is provided,
   use that information rather than guessing.

Saved memories:

{memory}

Current environment information:

{environment}
"""


# ============================================================
# AI
# ============================================================

def ask_kyvon(message, environment="No location information available."):

    prompt = SYSTEM_PROMPT.format(
        memory=memory_text(),
        environment=environment
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": message
            }
        ],
        temperature=0.7,
        max_tokens=1500
    )

    return response.choices[0].message.content.strip()


# ============================================================
# WEB SEARCH
# ============================================================

def web_search(query):

    response = client.chat.completions.create(
        model=WEB_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are KYVON's web research system. "
                    "Research the request and provide an accurate "
                    "and useful answer."
                )
            },
            {
                "role": "user",
                "content": query
            }
        ],
        max_tokens=1500
    )

    return response.choices[0].message.content.strip()


# ============================================================
# DIAGNOSTICS
# ============================================================

def diagnostics():

    results = []

    results.append({
        "name": "Python",
        "status": "ONLINE",
        "details": "Python runtime operational"
    })

    try:

        load_memory()

        results.append({
            "name": "Memory",
            "status": "ONLINE",
            "details": f"{len(memory)} memories loaded"
        })

    except Exception as error:

        results.append({
            "name": "Memory",
            "status": "ERROR",
            "details": str(error)
        })

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: ONLINE"
                }
            ],
            temperature=0,
            max_tokens=10
        )

        results.append({
            "name": "Groq AI",
            "status": "ONLINE",
            "details": response.choices[0].message.content.strip()
        })

    except Exception as error:

        results.append({
            "name": "Groq AI",
            "status": "ERROR",
            "details": str(error)
        })

    return results


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():

    results = diagnostics()

    online = all(
        result["status"] == "ONLINE"
        for result in results
    )

    return jsonify({
        "online": online,
        "diagnostics": results
    })


@app.route("/api/memory")
def get_memory():

    return jsonify({
        "memories": memory
    })


@app.route("/api/environment", methods=["POST"])
def environment():

    try:

        data = request.get_json()

        latitude = float(data["latitude"])
        longitude = float(data["longitude"])

        location = get_location(
            latitude,
            longitude
        )

        weather = get_weather(
            latitude,
            longitude
        )

        return jsonify({
            "location": location,
            "weather": weather
        })

    except Exception as error:

        log_error(
            "Environment Error",
            str(error),
            traceback.format_exc()
        )

        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/chat", methods=["POST"])
def chat():

    try:

        data = request.get_json()

        if not data or "message" not in data:

            return jsonify({
                "error": "No message provided."
            }), 400

        message = data["message"].strip()

        if not message:

            return jsonify({
                "error": "Empty message."
            }), 400

        lower = message.lower()

        # ----------------------------------------------------
        # MEMORY
        # ----------------------------------------------------

        if lower.startswith("remember "):

            text = message[9:].strip()

            if text:

                add_memory(text)

                return jsonify({
                    "response": (
                        "Understood. I have saved that "
                        "to my memory."
                    ),
                    "memory_saved": True
                })

        memory_phrases = [
            "remember that ",
            "don't forget that ",
            "keep in mind that "
        ]

        for phrase in memory_phrases:

            if lower.startswith(phrase):

                text = message[len(phrase):].strip()

                if text:

                    add_memory(text)

                    return jsonify({
                        "response": (
                            "Understood. I have saved that "
                            "to my memory."
                        ),
                        "memory_saved": True
                    })

        # ----------------------------------------------------
        # WEB
        # ----------------------------------------------------

        if lower.startswith("web "):

            query = message[4:].strip()

            if not query:

                return jsonify({
                    "response": (
                        "What would you like me to research?"
                    )
                })

            result = web_search(query)

            return jsonify({
                "response": result,
                "web": True
            })

        # ----------------------------------------------------
        # ENVIRONMENT
        # ----------------------------------------------------

        environment = data.get(
            "environment",
            "No location or weather information available."
        )

        result = ask_kyvon(
            message,
            environment
        )

        return jsonify({
            "response": result
        })

    except Exception as error:

        error_message = str(error)

        trace = traceback.format_exc()

        log_error(
            "Chat Error",
            error_message,
            trace
        )

        return jsonify({
            "error": error_message,
            "diagnosed": True
        }), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print()

    print("=" * 60)

    print("                 J.A.R.V.I.S.")

    print("=" * 60)

    print()

    print("Kyvon: Web interface starting...")

    print("Kyvon: Systems online.")

    print()

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False
    )