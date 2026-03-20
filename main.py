from flask import Flask, request
from flask_cors import CORS
from groq import Groq
import requests
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
BAILEY_URL = os.environ.get("BAILEY_URL", "https://clinicai-baileys.onrender.com")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")

client = Groq(api_key=GROQ_API_KEY)
patients = {}
appointments = {}

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


def get_system_prompt():
    return f"""Tu ek AI receptionist hai {bot_settings['clinic_name']} ka. Tera naam "ClinicAI" hai.
Tu Hindi aur English dono mein baat kar sakta hai - Hinglish bhi chalega.
Tu friendly aur professional hai.

Clinic Info:
- Naam: {bot_settings['clinic_name']}
- Doctor: {bot_settings['doctor_name']}
- Fees: Rs. {bot_settings['fees']}
- Location: {bot_settings['location']}
- Timing: Mon-Sat, 10am-1pm aur 4pm-7pm

Agar fees poochhe: sirf Rs. {bot_settings['fees']} batao.
Agar location poochhe: sirf {bot_settings['location']} batao.
Emergency mein: +{DOCTOR_NUMBER}
Short replies do - 3-4 lines max."""


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
    message = f"🔔 *Naya Appointment!*\n\n👤 {patient_name}\n📱 +{phone}\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n\n_ClinicAI_"
    send_whatsapp_via_bailey(DOCTOR_NUMBER, message)


def get_ai_response(user_message, phone):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": user_message}
            ],
            max_tokens=200
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq error: {e}")
        return "Maafi chahta hun, abhi kuch technical problem hai. Thodi der baad try karein. 🙏"


def process_message(phone, message):
    message_lower = message.lower().strip()

    if phone not in patients:
        patients[phone] = {"name": None, "step": "new", "appointment": {}}
    
    patient = patients[phone]
    step = patient["step"]

    # Greet
    if step == "new" or message_lower in ["hi", "hello", "namaste", "hii", "hey", "helo", "hlw", "hye"]:
        patients[phone]["step"] = "greeted"
        return f"Namaste! 🙏 {bot_settings['clinic_name']} mein aapka swagat hai!\n\nMain aapki kaise madad kar sakta hun?\n\n1️⃣ Appointment book karni hai\n2️⃣ Clinic timing/fees jaanni hai\n3️⃣ Doctor se urgent milna hai"

    # STRICT STEP FLOW - kisi bhi keyword se interrupt nahi hoga
    if step == "getting_name":
        patients[phone]["name"] = message.strip().title()
        patients[phone]["step"] = "getting_date"
        return f"Shukriya {patients[phone]['name']} ji! 😊\n\nKis date ko aana chahte hain?\n📅 (jaise: kal, 25 march, shukrawar ko)"

    if step == "getting_date":
        patients[phone]["appointment"]["date"] = message.strip()
        patients[phone]["step"] = "getting_slot"
        return "Theek hai! ⏰ Kaunsa time chahiye?\n\n🌅 Subah: 10am, 11am, 12pm\n🌆 Shaam: 4pm, 5pm, 6pm"

    if step == "getting_slot":
        patients[phone]["appointment"]["time"] = message.strip()
        patients[phone]["step"] = "getting_complaint"
        return "Kya takleef hai ya kyun milna chahte hain doctor se? 🏥"

    if step == "getting_complaint":
        patients[phone]["appointment"]["complaint"] = message.strip()
        name = patients[phone]["name"]
        date = patients[phone]["appointment"].get("date", "TBD")
        time = patients[phone]["appointment"].get("time", "TBD")
        complaint = patients[phone]["appointment"].get("complaint", "")
        apt_id = f"APT{len(appointments)+1}"
        appointments[apt_id] = {
            "name": name, "phone": phone,
            "date": date, "time": time,
            "complaint": complaint, "source": "WhatsApp Bot"
        }
        notify_doctor(name, phone, date, time, complaint)
        patients[phone]["step"] = "done"
        return f"✅ *Appointment Confirm!*\n\n👤 {name}\n📅 {date}\n⏰ {time}\n🏥 {complaint}\n📍 {bot_settings['clinic_name']}\n\nEk din pehle reminder aayega! 🔔"

    if step == "done":
        patients[phone]["step"] = "greeted"

    # General queries
    if any(w in message_lower for w in ["appointment", "book", "milna", "1", "slot", "date"]):
        patients[phone]["step"] = "getting_name"
        return "Zaroor! 😊 Pehle aapka naam batayein?"

    if any(w in message_lower for w in ["fees", "kitna", "charge", "price", "paisa", "rupee", "2"]):
        return f"{bot_settings['doctor_name']} ki consultation fees *₹{bot_settings['fees']}* hai. 💊\nPayment cash ya UPI se clinic pe."

    if any(w in message_lower for w in ["timing", "kab", "khula", "open", "band", "time"]):
        return "Clinic timing:\n🌅 Subah: 10am - 1pm\n🌆 Shaam: 4pm - 7pm\n📅 Monday to Saturday\n(Sunday band)"

    if any(w in message_lower for w in ["address", "location", "kahan", "where", "3"]):
        return f"📍 {bot_settings['clinic_name']}\n{bot_settings['location']}"

    if any(w in message_lower for w in ["urgent", "emergency"]):
        return f"🚨 Emergency:\n📞 +{DOCTOR_NUMBER}"

    return get_ai_response(message, phone)


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
            status_msg = bot_settings.get("clinic_status_msg") or "Maafi chahta hun, clinic abhi band hai. Baad mein try karein. 🙏"
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
            apt_id = f"APT{len(appointments)+1}"
            phone = data.get("phone", "")
            name = data.get("name", "")
            time = data.get("time", "TBD")
            complaint = data.get("complaint", "")
            appointments[apt_id] = {
                "name": name, "phone": phone,
                "date": data.get("date", datetime.now().strftime("%d/%m/%Y")),
                "time": time, "complaint": complaint,
                "source": data.get("source", "Staff Added")
            }
            if data.get("send_whatsapp", True) and phone:
                msg = f"✅ *Appointment Confirm!*\n\n👤 {name}\n⏰ {time}\n🏥 {complaint}\n📍 {bot_settings['clinic_name']}, {bot_settings['location']}\n\nPlease samay par aayein. 🙏\n_ClinicAI_"
                send_whatsapp_via_bailey(phone, msg)
            return json.dumps({"success": True}), 200
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}), 500
    return json.dumps(appointments, ensure_ascii=False), 200, {'Content-Type': 'application/json'}


@app.route("/send-report", methods=["POST"])
def send_report():
    try:
        data = request.json
        phone = data.get("phone", "")
        patient_name = data.get("name", "")
        report_note = data.get("note", "")
        message = f"📋 *Report Ready!*\n\n👤 {patient_name} ji,\n\nAapki report tayar ho gayi.\n\nDoctor ka note:\n_{report_note}_\n\n🙏\n_{bot_settings['clinic_name']}_"
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
        message = f"🔔 *Reminder*\n\nNamaste {patient_name} ji!\n\nKal aapka appointment:\n⏰ {appointment_time}\n📍 {bot_settings['clinic_name']}, {bot_settings['location']}\n\nSamay par aayein. 🙏\n_ClinicAI_"
        send_whatsapp_via_bailey(phone, message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False}), 500


@app.route("/doctor-summary", methods=["GET"])
def doctor_summary():
    today_apts = list(appointments.values())
    if not today_apts:
        summary = "📊 *Aaj Ka Schedule*\n\nAaj koi appointment nahi hai."
    else:
        summary = f"📊 *Schedule - {datetime.now().strftime('%d %B %Y')}*\nTotal: {len(today_apts)}\n\n"
        for i, apt in enumerate(today_apts, 1):
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
    return json.dumps({"paused": bot_paused, "messages_today": bot_stats["messages_today"], "total_appointments": len(appointments)}), 200


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
    return json.dumps({"messages_today": bot_stats["messages_today"], "total_appointments": len(appointments), "bot_paused": bot_paused}), 200


@app.route("/", methods=["GET"])
def home():
    return "ClinicAI Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
