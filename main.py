from flask import Flask, request
from flask_cors import CORS
from groq import Groq
from pymongo import MongoClient
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests
import json
import os
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
BAILEY_URL = os.environ.get("BAILEY_URL", "https://clinicai-baileys.onrender.com")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")
MONGO_URI = os.environ.get("MONGO_URI", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

IST = pytz.timezone("Asia/Kolkata")

# MongoDB
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["clinicai"]
    appointments_col = db["appointments"]
    patients_col = db["patients"]
    print("MongoDB connected!")
except Exception as e:
    print(f"MongoDB error: {e}")
    appointments_col = None
    patients_col = None

groq_client = Groq(api_key=GROQ_API_KEY)
patients_memory = {}
bot_paused = False

bot_settings = {
    "clinic_name": "ClinicAI Demo Clinic",
    "doctor_name": "Dr. Kunal",
    "fees": "300",
    "location": "Patna, Bihar",
    "timing": "Monday to Saturday, 10am-1pm aur 4pm-7pm"
}


def get_ist_now():
    return datetime.now(IST)


def get_calendar_service():
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        print(f"Calendar service error: {e}")
        return None


def add_to_google_calendar(name, phone, date_str, time_str, complaint):
    try:
        service = get_calendar_service()
        if not service:
            return None

        now = get_ist_now()

        try:
            if "/" in date_str:
                date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            elif "-" in date_str:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                date_obj = now.replace(tzinfo=None)
        except:
            date_obj = now.replace(tzinfo=None)

        try:
            time_str_clean = time_str.upper().strip()
            if "AM" in time_str_clean or "PM" in time_str_clean:
                time_obj = datetime.strptime(time_str_clean, "%I:%M %p")
            elif ":" in time_str:
                time_obj = datetime.strptime(time_str.strip(), "%H:%M")
            else:
                time_obj = datetime.strptime("10:00", "%H:%M")
        except:
            time_obj = datetime.strptime("10:00", "%H:%M")

        start_dt = IST.localize(date_obj.replace(hour=time_obj.hour, minute=time_obj.minute, second=0))
        end_dt = start_dt + timedelta(minutes=30)

        event = {
            "summary": f"Patient: {name}",
            "description": f"📱 Phone: +{phone}\n🏥 Complaint: {complaint}\n\nBooked via ClinicAI WhatsApp Bot",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}
        }

        result = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        print(f"Calendar event created: {result.get('htmlLink')}")
        return result.get("id")
    except Exception as e:
        print(f"Calendar add error: {e}")
        return None


def save_appointment(name, phone, date, time, complaint):
    apt_data = {
        "name": name, "phone": phone,
        "date": date, "time": time,
        "complaint": complaint,
        "source": "WhatsApp AI Bot",
        "created_at": get_ist_now().isoformat()
    }
    try:
        if appointments_col is not None:
            appointments_col.insert_one(apt_data.copy())
    except Exception as e:
        print(f"DB save error: {e}")

    add_to_google_calendar(name, phone, date, time, complaint)

    msg = f"🔔 *Naya Appointment!*\n\n👤 {name}\n📱 +{phone}\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n\n_ClinicAI_"
    send_whatsapp(DOCTOR_NUMBER, msg)

    return apt_data


def send_whatsapp(to, message):
    try:
        phone = str(to).replace("+", "").replace(" ", "")
        response = requests.post(
            f"{BAILEY_URL}/send",
            json={"to": phone, "message": message},
            timeout=10
        )
        return response.json()
    except Exception as e:
        print(f"WhatsApp send error: {e}")
        return None


def get_ai_reply(phone, user_message):
    now = get_ist_now()
    history = patients_memory.get(phone, [])

    system_prompt = f"""Aap {bot_settings['clinic_name']} ke professional AI receptionist hain. Aapka naam "ClinicAI" hai.
Aap Hinglish mein baat karte hain — formal, warm aur caring tone mein. Jaise ek real clinic receptionist hota hai.

Aaj ki date aur time: {now.strftime("%d %B %Y, %I:%M %p")} (IST)

Clinic Info:
- Doctor: {bot_settings['doctor_name']}
- Fees: Rs. {bot_settings['fees']}
- Location: {bot_settings['location']}
- Timing: {bot_settings['timing']}
- Emergency: +{DOCTOR_NUMBER}

Aapka kaam:
1. Patient se formally aur warmly baat karein
2. Appointment ke liye naam, date, time aur problem poochhein
3. Jab sab info mil jaye toh SIRF is format mein ek line likhein:
   BOOK_APPOINTMENT|naam|date(DD/MM/YYYY)|time(HH:MM)|problem
4. Fees, timing, location ki sahi info dein
5. Short replies dein — 2-3 lines max
6. Hamesha "aap" aur "ji" use karein — kabhi "tu/tum" nahi
7. Aaj ki sahi date/time aapko pata hai — use karein

Important: BOOK_APPOINTMENT line ke saath koi aur text mat likhein."""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=200
        )
        reply = response.choices[0].message.content

        patients_memory.setdefault(phone, [])
        patients_memory[phone].append({"role": "user", "content": user_message})
        patients_memory[phone].append({"role": "assistant", "content": reply})

        if "BOOK_APPOINTMENT|" in reply:
            for line in reply.split("\n"):
                if line.startswith("BOOK_APPOINTMENT|"):
                    parts = line.split("|")
                    if len(parts) >= 5:
                        name = parts[1].strip()
                        date = parts[2].strip()
                        time = parts[3].strip()
                        complaint = parts[4].strip()
                        save_appointment(name, phone, date, time, complaint)
                        return f"✅ *Appointment Confirm!*\n\n👤 {name} ji\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n📍 {bot_settings['location']}\n\nSamay par aayein ji! 🙏\n_ClinicAI_"

        return reply

    except Exception as e:
        print(f"Groq error: {e}")
        return f"Maafi ji, thodi technical problem aa gayi. 🙏\nSeedha call karein: 📞 +{DOCTOR_NUMBER}"


@app.route("/process", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        if not data:
            return json.dumps({"reply": None}), 200

        phone = data.get("phone", "")
        message = data.get("message", "").strip()

        if not phone or not message:
            msg_data = data.get("data", {})
            message = msg_data.get("body", "").strip()
            phone = msg_data.get("from", "").replace("@c.us", "").replace("+", "")
            if msg_data.get("fromMe", False) or not message or msg_data.get("type", "") != "chat":
                return json.dumps({"reply": None}), 200

        if not phone or not message:
            return json.dumps({"reply": None}), 200

        if bot_paused:
            status_msg = bot_settings.get("clinic_status_msg") or "Maafi ji, clinic abhi band hai. Baad mein try karein. 🙏"
            return json.dumps({"reply": status_msg}), 200

        print(f"Message from {phone}: {message}")
        reply = get_ai_reply(phone, message)
        return json.dumps({"reply": reply}, ensure_ascii=False), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return json.dumps({"reply": None}), 200


@app.route("/appointments", methods=["GET", "POST"])
def get_appointments():
    if request.method == "POST":
        try:
            data = request.json
            save_appointment(
                data.get("name", ""),
                data.get("phone", ""),
                data.get("date", get_ist_now().strftime("%d/%m/%Y")),
                data.get("time", "TBD"),
                data.get("complaint", "")
            )
            return json.dumps({"success": True}), 200
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}), 500
    try:
        apts = list(appointments_col.find({}, {"_id": 0})) if appointments_col else []
        return json.dumps({f"APT{i+1}": apt for i, apt in enumerate(apts)}, ensure_ascii=False), 200
    except:
        return json.dumps({}), 200


@app.route("/bot-status", methods=["GET", "POST"])
def bot_status():
    global bot_paused
    if request.method == "POST":
        bot_paused = request.json.get("paused", False)
        return json.dumps({"success": True, "paused": bot_paused}), 200
    return json.dumps({"paused": bot_paused}), 200


@app.route("/bot-settings", methods=["GET", "POST"])
def handle_bot_settings():
    global bot_settings
    if request.method == "POST":
        data = request.json
        for key in ["clinic_name", "doctor_name", "fees", "location", "timing"]:
            if data.get(key):
                bot_settings[key] = data[key]
        return json.dumps({"success": True, "settings": bot_settings}), 200
    return json.dumps(bot_settings), 200


@app.route("/send-reminder", methods=["POST"])
def send_reminder():
    try:
        data = request.json
        message = f"🔔 *Appointment Reminder*\n\nNamaste {data.get('name', '')} ji! 😊\n\nKal aapka appointment hai:\n⏰ {data.get('time', '')}\n📍 {bot_settings['clinic_name']}, {bot_settings['location']}\n\nSamay par aana na bhoolein! 🙏\n_ClinicAI_"
        send_whatsapp(data.get("phone", ""), message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False}), 500


@app.route("/send-report", methods=["POST"])
def send_report():
    try:
        data = request.json
        message = f"📋 *Report Ready Hai Ji!*\n\n👤 {data.get('name', '')} ji,\nAapki report tayar ho gayi hai. 😊\n\nDoctor ka note:\n_{data.get('note', '')}_\n\nKoi sawaal ho toh batayein. 🙏\n_{bot_settings['clinic_name']}_"
        send_whatsapp(data.get("phone", ""), message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False}), 500


@app.route("/stats", methods=["GET"])
def get_stats():
    try:
        total = appointments_col.count_documents({}) if appointments_col else 0
    except:
        total = 0
    return json.dumps({"total_appointments": total, "bot_paused": bot_paused}), 200


@app.route("/", methods=["GET"])
def home():
    return "ClinicAI Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
