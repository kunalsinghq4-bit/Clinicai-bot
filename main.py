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

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
BAILEY_URL = os.environ.get("BAILEY_URL", "https://clinicai-baileys.onrender.com")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://kunalsinghq4_db_user:VyW79MN04Cfb1p5Z@cluster0.au9ssyw.mongodb.net/?appName=Cluster0")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "sudhanshukashyap95@gmail.com")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# MongoDB connect
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

# Google Calendar connect
def get_calendar_service():
    try:
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        else:
            # Local development mein file se load karo
            with open("clinicai-490904-058255af640a.json") as f:
                creds_dict = json.load(f)
        
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        service = build("calendar", "v3", credentials=creds)
        return service
    except Exception as e:
        print(f"Google Calendar error: {e}")
        return None


def add_to_google_calendar(name, phone, date_str, time_str, complaint):
    """Appointment Google Calendar mein add karo"""
    try:
        service = get_calendar_service()
        if not service:
            return None

        # Date aur time parse karo
        # date_str jaise: "25/03/2026" ya "25 march"
        # time_str jaise: "10:00 AM" ya "subah 10 baje"
        
        # Simple parsing - agar proper format nahi hai toh aaj ki date lo
        try:
            if "/" in date_str:
                date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            else:
                date_obj = datetime.now()
        except:
            date_obj = datetime.now()

        try:
            if "AM" in time_str.upper() or "PM" in time_str.upper():
                time_obj = datetime.strptime(time_str.upper().strip(), "%I:%M %p")
            elif ":" in time_str:
                time_obj = datetime.strptime(time_str.strip(), "%H:%M")
            else:
                time_obj = datetime.strptime("10:00", "%H:%M")
        except:
            time_obj = datetime.strptime("10:00", "%H:%M")

        start_dt = date_obj.replace(
            hour=time_obj.hour,
            minute=time_obj.minute,
            second=0
        )
        end_dt = start_dt + timedelta(minutes=30)

        event = {
            "summary": f"Patient: {name}",
            "description": f"📱 Phone: +{phone}\n🏥 Complaint: {complaint}\n\nBooked via ClinicAI WhatsApp Bot",
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Asia/Kolkata"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Kolkata"
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30}
                ]
            }
        }

        result = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event
        ).execute()

        print(f"Calendar event created: {result.get('htmlLink')}")
        return result.get("id")

    except Exception as e:
        print(f"Calendar add error: {e}")
        return None


groq_client = Groq(api_key=GROQ_API_KEY)
patients_memory = {}

bot_paused = False
bot_settings = {
    "clinic_name": "ClinicAI Demo Clinic",
    "doctor_name": "Dr. Kunal",
    "fees": "300",
    "language": "hinglish",
    "location": "Patna, Bihar"
}
schedule = {
    "Monday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Tuesday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Wednesday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Thursday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Friday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Saturday": {"on": True, "morning_start": "10:00", "morning_end": "13:00", "evening_start": "16:00", "evening_end": "19:00"},
    "Sunday": {"on": False, "morning_start": "", "morning_end": "", "evening_start": "", "evening_end": ""}
}
bot_stats = {"messages_today": 0}


def get_patient_from_db(phone):
    try:
        if patients_col is not None:
            p = patients_col.find_one({"phone": phone}, {"_id": 0})
            return p
    except:
        pass
    return None


def save_patient_to_db(phone, data):
    try:
        if patients_col is not None:
            patients_col.update_one(
                {"phone": phone},
                {"$set": data},
                upsert=True
            )
    except Exception as e:
        print(f"Patient save error: {e}")


def save_appointment_db(apt_data):
    try:
        if appointments_col is not None:
            appointments_col.insert_one(apt_data)
    except Exception as e:
        print(f"DB save error: {e}")


def get_appointments_db():
    try:
        if appointments_col is not None:
            apts = list(appointments_col.find({}, {"_id": 0}))
            return {f"APT{i+1}": apt for i, apt in enumerate(apts)}
    except Exception as e:
        print(f"DB fetch error: {e}")
    return {}


def get_system_prompt(patient_name=None):
    name_context = f"\nPatient ka naam: {patient_name}" if patient_name else ""
    return f"""Tu {bot_settings['clinic_name']} ki ek warm aur friendly AI receptionist hai. Tera naam "ClinicAI" hai.
Tu Hinglish mein baat karta hai — natural, caring aur human jaisi tone mein.
{name_context}

Clinic Info:
- Naam: {bot_settings['clinic_name']}
- Doctor: {bot_settings['doctor_name']}
- Fees: Rs. {bot_settings['fees']}
- Location: {bot_settings['location']}
- Timing: Mon-Sat, 10am-1pm aur 4pm-7pm

Important rules:
- Hamesha "ji" use karo patients ke saath
- Warm aur caring tone rakho — jaise ek real receptionist
- Fees sirf Rs. {bot_settings['fees']} batao
- Location sirf {bot_settings['location']} batao
- Agar kuch samajh na aaye toh clinic number dena: +{DOCTOR_NUMBER}
- 3 baar confuse ho toh seedha number dena
- Replies short rakho — 2-3 lines max"""


def send_whatsapp_via_bailey(to, message):
    try:
        phone = str(to).replace("+", "").replace(" ", "")
        response = requests.post(
            f"{BAILEY_URL}/send",
            json={"to": phone, "message": message},
            timeout=10
        )
        print(f"Bailey send to {phone}: {response.status_code}")
        return response.json()
    except Exception as e:
        print(f"Bailey send error: {e}")
        return None


def notify_doctor(patient_name, phone, date, time, complaint):
    message = f"🔔 *Naya Appointment!*\n\n👤 {patient_name} ji\n📱 +{phone}\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n\n_ClinicAI_"
    send_whatsapp_via_bailey(DOCTOR_NUMBER, message)


def get_ai_response(user_message, phone, patient_name=None, confusion_count=0):
    if confusion_count >= 2:
        return f"Maafi ji, main theek se samajh nahi paa raha. 😅\nSeedha clinic pe call karein:\n📞 +{DOCTOR_NUMBER}"
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": get_system_prompt(patient_name)},
                {"role": "user", "content": user_message}
            ],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq error: {e}")
        return f"Maafi ji, thodi technical problem aa gayi. 🙏\nSeedha call karein: 📞 +{DOCTOR_NUMBER}"


def get_patient_state(phone):
    if phone in patients_memory:
        return patients_memory[phone]
    
    db_patient = get_patient_from_db(phone)
    if db_patient:
        state = {
            "name": db_patient.get("name"),
            "step": "returning",
            "appointment": {},
            "confusion_count": 0
        }
        patients_memory[phone] = state
        return state
    
    state = {"name": None, "step": "new", "appointment": {}, "confusion_count": 0}
    patients_memory[phone] = state
    return state


def process_message(phone, message):
    message_lower = message.lower().strip()
    patient = get_patient_state(phone)
    step = patient["step"]
    known_name = patient.get("name")

    if step == "new" or step == "returning" or message_lower in ["hi", "hello", "namaste", "hii", "hey", "helo", "hlw", "hye"]:
        patients_memory[phone]["step"] = "greeted"
        patients_memory[phone]["confusion_count"] = 0
        if known_name:
            return f"Namaste {known_name} ji! 🙏 Wapas aaye — kaisa mahsoos kar rahe hain?\n\nKya main aapki kuch madad kar sakta hun?\n\n1️⃣ Appointment book karni hai\n2️⃣ Timing/fees jaanni hai\n3️⃣ Koi aur sawaal"
        return f"Namaste ji! 🙏 {bot_settings['clinic_name']} mein aapka swagat hai!\n\nMain aapki kaise madad kar sakta hun?\n\n1️⃣ Appointment book karni hai\n2️⃣ Clinic timing/fees jaanni hai\n3️⃣ Doctor se urgent milna hai"

    if step == "getting_name":
        name = message.strip().title()
        patients_memory[phone]["name"] = name
        patients_memory[phone]["step"] = "getting_date"
        patients_memory[phone]["confusion_count"] = 0
        save_patient_to_db(phone, {"phone": phone, "name": name})
        return f"Shukriya {name} ji! 😊\n📅 Kis date ko aana chahte hain?\n(jaise: kal, 25 march)"

    if step == "getting_date":
        patients_memory[phone]["appointment"]["date"] = message.strip()
        patients_memory[phone]["step"] = "getting_time"
        patients_memory[phone]["confusion_count"] = 0
        return f"Theek hai ji! ⏰ Kaunsa time pasand karenge?\n\n🌅 Subah: 10am - 1pm\n🌆 Shaam: 4pm - 7pm"

    if step == "getting_time":
        patients_memory[phone]["appointment"]["time"] = message.strip()
        patients_memory[phone]["step"] = "getting_complaint"
        patients_memory[phone]["confusion_count"] = 0
        return "Samajh gaye ji! 🏥 Thodi si baat batayein — kya takleef hai? (2-3 words mein)"

    if step == "getting_complaint":
        complaint = message.strip()
        patients_memory[phone]["appointment"]["complaint"] = complaint
        patients_memory[phone]["step"] = "greeted"
        patients_memory[phone]["confusion_count"] = 0

        name = patients_memory[phone].get("name", "Patient")
        apt = patients_memory[phone]["appointment"]
        date = apt.get("date", datetime.now().strftime("%d/%m/%Y"))
        time = apt.get("time", "TBD")

        # MongoDB mein save karo
        apt_data = {
            "name": name,
            "phone": phone,
            "date": date,
            "time": time,
            "complaint": complaint,
            "source": "WhatsApp Bot",
            "created_at": datetime.now().isoformat()
        }
        save_appointment_db(apt_data)

        # Google Calendar mein add karo
        calendar_event_id = add_to_google_calendar(name, phone, date, time, complaint)
        calendar_msg = "📅 Google Calendar mein bhi add ho gayi!" if calendar_event_id else ""

        # Doctor ko notify karo
        notify_doctor(name, phone, date, time, complaint)

        return f"✅ *Appointment Confirm!*\n\n👤 {name} ji\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n\n{calendar_msg}\n\nSamay par aayein ji! 🙏\n_{bot_settings['clinic_name']}_"

    if any(w in message_lower for w in ["appointment", "book", "milna", "doctor", "1"]):
        if known_name:
            patients_memory[phone]["step"] = "getting_date"
            return f"Zaroor {known_name} ji! 😊 Kis date ko aana chahte hain?\n📅 (jaise: kal, 25 march)"
        else:
            patients_memory[phone]["step"] = "getting_name"
            return "Zaroor ji! 😊 Pehle aapka naam batayein?"

    if any(w in message_lower for w in ["fees", "kitna", "charge", "price", "paisa", "2"]):
        patients_memory[phone]["confusion_count"] = 0
        return f"{bot_settings['doctor_name']} ki fees *₹{bot_settings['fees']}* hai ji. 💊\nCash ya UPI — dono chalega!"

    if any(w in message_lower for w in ["timing", "kab", "khula", "open", "band", "time"]):
        patients_memory[phone]["confusion_count"] = 0
        return "Clinic timing ji:\n🌅 Subah: 10am - 1pm\n🌆 Shaam: 4pm - 7pm\n📅 Monday to Saturday\n(Sunday band rehta hai 🙏)"

    if any(w in message_lower for w in ["address", "location", "kahan", "where", "3"]):
        patients_memory[phone]["confusion_count"] = 0
        return f"📍 {bot_settings['clinic_name']}\n{bot_settings['location']}\n\nKoi aur sawaal ho toh batayein ji! 😊"

    if any(w in message_lower for w in ["urgent", "emergency"]):
        patients_memory[phone]["confusion_count"] = 0
        return f"🚨 Emergency ke liye seedha call karein ji:\n📞 +{DOCTOR_NUMBER}\n\nDhyan rakhein! 🙏"

    patients_memory[phone]["confusion_count"] = patients_memory[phone].get("confusion_count", 0) + 1
    return get_ai_response(message, phone, known_name, patients_memory[phone]["confusion_count"])


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

        print(f"Message from {phone}: {message}")

        if bot_paused:
            status_msg = bot_settings.get("clinic_status_msg") or "Maafi ji, clinic abhi band hai. Baad mein try karein. 🙏"
            return json.dumps({"reply": status_msg}), 200

        clinic_st = bot_settings.get("clinic_status", "normal")
        if clinic_st != "normal" and bot_settings.get("clinic_status_msg"):
            return json.dumps({"reply": bot_settings["clinic_status_msg"]}, ensure_ascii=False), 200

        bot_stats["messages_today"] += 1
        response = process_message(phone, message)
        return json.dumps({"reply": response}, ensure_ascii=False), 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return json.dumps({"reply": None}), 200


@app.route("/appointments", methods=["GET", "POST"])
def get_appointments():
    if request.method == "POST":
        try:
            data = request.json
            phone = data.get("phone", "")
            name = data.get("name", "")
            time = data.get("time", "TBD")
            complaint = data.get("complaint", "")
            apt_data = {
                "name": name, "phone": phone,
                "date": data.get("date", datetime.now().strftime("%d/%m/%Y")),
                "time": time, "complaint": complaint,
                "source": data.get("source", "Staff Added"),
                "created_at": datetime.now().isoformat()
            }
            save_appointment_db(apt_data)

            # Google Calendar mein bhi add karo
            add_to_google_calendar(name, phone, apt_data["date"], time, complaint)

            if data.get("send_whatsapp", True) and phone:
                msg = f"✅ Appointment confirm ho gayi ji!\n\n👤 {name}\n⏰ {time}\n🏥 {complaint}\n📍 {bot_settings['clinic_name']}, {bot_settings['location']}\n\nSamay par aayein. 🙏\n_ClinicAI_"
                send_whatsapp_via_bailey(phone, msg)
            return json.dumps({"success": True}), 200
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}), 500
    apts = get_appointments_db()
    return json.dumps(apts, ensure_ascii=False), 200, {'Content-Type': 'application/json'}


@app.route("/send-report", methods=["POST"])
def send_report():
    try:
        data = request.json
        phone = data.get("phone", "")
        patient_name = data.get("name", "")
        report_note = data.get("note", "")
        message = f"📋 *Report Ready Hai Ji!*\n\n👤 {patient_name} ji,\n\nAapki report tayar ho gayi hai. 😊\n\nDoctor ka note:\n_{report_note}_\n\nKoi sawaal ho toh batayein. 🙏\n_{bot_settings['clinic_name']}_"
        send_whatsapp_via_bailey(phone, message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}), 500


@app.route("/send-reminder", methods=["POST"])
def send_reminder():
    try:
        data = request.json
        phone = data.get("phone", "")
        patient_name = data.get("name", "")
        appointment_time = data.get("time", "")
        message = f"🔔 *Appointment Reminder*\n\nNamaste {patient_name} ji! 😊\n\nKal aapka appointment hai:\n⏰ {appointment_time}\n📍 {bot_settings['clinic_name']}, {bot_settings['location']}\n\nSamay par aana na bhoolein! 🙏\n_ClinicAI_"
        send_whatsapp_via_bailey(phone, message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False}), 500


@app.route("/doctor-summary", methods=["GET"])
def doctor_summary():
    apts = list(get_appointments_db().values())
    if not apts:
        summary = "📊 *Aaj Ka Schedule*\n\nAaj koi appointment nahi hai ji."
    else:
        summary = f"📊 *Schedule - {datetime.now().strftime('%d %B %Y')}*\nTotal: {len(apts)}\n\n"
        for i, apt in enumerate(apts, 1):
            summary += f"{i}. *{apt['name']}* - {apt.get('date','')} {apt['time']}\n   {apt['complaint']}\n\n"
    send_whatsapp_via_bailey(DOCTOR_NUMBER, summary)
    return json.dumps({"success": True, "summary": summary}), 200


@app.route("/bot-status", methods=["GET", "POST"])
def bot_status():
    global bot_paused
    if request.method == "POST":
        data = request.json
        bot_paused = data.get("paused", False)
        return json.dumps({"success": True, "paused": bot_paused}), 200
    return json.dumps({"paused": bot_paused, "messages_today": bot_stats["messages_today"], "total_appointments": len(get_appointments_db())}), 200


@app.route("/bot-settings", methods=["GET", "POST"])
def handle_bot_settings():
    global bot_settings
    if request.method == "POST":
        data = request.json
        for key in ["clinic_name", "doctor_name", "fees", "language", "location"]:
            if data.get(key):
                bot_settings[key] = data[key]
        return json.dumps({"success": True, "settings": bot_settings}), 200
    return json.dumps(bot_settings), 200


@app.route("/schedule", methods=["GET", "POST"])
def handle_schedule():
    global schedule
    if request.method == "POST":
        data = request.json
        schedule.update(data)
        return json.dumps({"success": True}), 200
    return json.dumps(schedule), 200


@app.route("/clinic-status", methods=["GET", "POST"])
def handle_clinic_status():
    global bot_settings
    if request.method == "POST":
        data = request.json
        bot_settings["clinic_status"] = data.get("status", "normal")
        bot_settings["clinic_status_msg"] = data.get("message", None)
        return json.dumps({"success": True}), 200
    return json.dumps({"status": bot_settings.get("clinic_status", "normal")}), 200


@app.route("/reminder-settings", methods=["GET", "POST"])
def reminder_settings():
    global bot_settings
    if request.method == "POST":
        bot_settings["reminders"] = request.json
        return json.dumps({"success": True}), 200
    return json.dumps(bot_settings.get("reminders", {})), 200


@app.route("/stats", methods=["GET"])
def get_stats():
    return json.dumps({"messages_today": bot_stats["messages_today"], "total_appointments": len(get_appointments_db()), "bot_paused": bot_paused}), 200


@app.route("/", methods=["GET"])
def home():
    return "ClinicAI Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
