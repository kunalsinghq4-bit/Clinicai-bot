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
ULTRAMSG_INSTANCE = os.environ.get("ULTRAMSG_INSTANCE", "instance166153")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN", "ch512e62wj5hxj36")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")

client = Groq(api_key=GROQ_API_KEY)
patients = {}
appointments = {}

# Bot state
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

CLINIC_INFO = """
Clinic Name: ClinicAI Demo Clinic
Doctor: Dr. Kunal
Timing: Monday to Saturday, 10am to 1pm and 4pm to 7pm
Fees: Rs. 300
Location: Patna, Bihar
"""

SYSTEM_PROMPT = f"""
Tu ek AI receptionist hai ClinicAI Demo Clinic ka. Tera naam "ClinicAI" hai.
Tu Hindi aur English dono mein baat kar sakta hai - Hinglish bhi chalega.
Tu friendly aur professional hai.
Clinic ki information: {CLINIC_INFO}
Tera kaam hai:
1. Patients ko appointment book karne mein help karna
2. Clinic ki timing, fees aur location batana
3. Doctor se milne ka schedule set karna
Appointment book karne ka process:
- Pehle patient ka naam poochh
- Phir date aur time poochh (available slots: 10am, 11am, 12pm, 4pm, 5pm, 6pm)
- Phir unki takleef/complaint poochh
- Confirm karke appointment book karo
Agar koi emergency ho toh doctor ka number dena: {DOCTOR_NUMBER}
Hamesha short aur clear replies do - 3-4 lines max.
"""

def send_whatsapp_message(to, message):
    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat"
    payload = {"token": ULTRAMSG_TOKEN, "to": to, "body": message, "priority": 10}
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def notify_doctor(patient_name, phone, time, complaint):
    message = f"🔔 *Naya Appointment Book Hua!*\n\n👤 Patient: {patient_name}\n📱 Phone: {phone}\n⏰ Time: {time}\n🏥 Complaint: {complaint}\n\n_ClinicAI System_"
    send_whatsapp_message(DOCTOR_NUMBER, message)

def get_ai_response(user_message, phone):
    try:
        patient = patients.get(phone, {})
        context = ""
        if patient.get("name"):
            context = f"\nPatient ka naam: {patient['name']}"
        if patient.get("appointment"):
            context += f"\nAppointment details: {json.dumps(patient['appointment'], ensure_ascii=False)}"
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + context},
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

    if patient["step"] == "new" or message_lower in ["hi", "hello", "namaste", "hii", "hey"]:
        patients[phone]["step"] = "greeted"
        return "Namaste! 🙏 ClinicAI Demo Clinic mein aapka swagat hai!\n\nMain aapki kaise madad kar sakta hun?\n\n1️⃣ Appointment book karni hai\n2️⃣ Clinic timing/fees jaanni hai\n3️⃣ Doctor se urgent milna hai"

    if any(word in message_lower for word in ["appointment", "book", "milna", "doctor", "1", "slot"]):
        if not patient.get("name"):
            patients[phone]["step"] = "getting_name"
            return "Zaroor! 😊 Pehle aapka naam batayein?"

    if patient["step"] == "getting_name":
        patients[phone]["name"] = message.strip().title()
        patients[phone]["step"] = "getting_time"
        return f"Shukriya {patients[phone]['name']} ji! 😊\n\nKab aana chahte hain? Available slots:\n\n🌅 *Subah:* 10am, 11am, 12pm\n🌆 *Shaam:* 4pm, 5pm, 6pm\n\n(Mon-Sat)"

    if patient["step"] == "getting_time":
        patients[phone]["appointment"]["time"] = message.strip()
        patients[phone]["step"] = "getting_complaint"
        return "Theek hai! 👍 Aur batayein - kya takleef hai ya kyun milna chahte hain doctor se?"

    if patient["step"] == "getting_complaint":
        patients[phone]["appointment"]["complaint"] = message.strip()
        patients[phone]["step"] = "confirmed"
        name = patients[phone]["name"]
        time = patients[phone]["appointment"].get("time", "TBD")
        complaint = patients[phone]["appointment"].get("complaint", "")
        apt_id = f"APT{len(appointments)+1}"
        appointments[apt_id] = {"name": name, "phone": phone, "time": time, "complaint": complaint, "source": "WhatsApp Bot"}
        notify_doctor(name, phone, time, complaint)
        patients[phone]["step"] = "done"
        return f"✅ *Appointment Confirm Ho Gayi!*\n\n👤 Naam: {name}\n⏰ Time: {time}\n🏥 Complaint: {complaint}\n📍 ClinicAI Demo Clinic, Patna\n\nAapko ek din pehle reminder bhi aayega! 🔔"

    if patient["step"] == "done":
        patients[phone]["step"] = "greeted"

    if any(word in message_lower for word in ["fees", "kitna", "charge", "price", "2"]):
        return "Dr. Kunal ki consultation fees *₹300* hai. 💊\nPayment cash ya UPI se clinic pe ho sakti hai."

    if any(word in message_lower for word in ["timing", "time", "kab", "khula", "open", "band"]):
        return "Clinic timing:\n🌅 *Subah:* 10am - 1pm\n🌆 *Shaam:* 4pm - 7pm\n📅 Monday to Saturday\n\n(Sunday band rehta hai)"

    if any(word in message_lower for word in ["address", "location", "kahan", "where", "3"]):
        return "📍 ClinicAI Demo Clinic\nPatna, Bihar"

    if any(word in message_lower for word in ["urgent", "emergency"]):
        return f"🚨 Emergency ke liye seedha call karein:\n📞 +{DOCTOR_NUMBER}"

    return get_ai_response(message, phone)


@app.route("/process", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        if not data:
            return json.dumps({"reply": None}), 200

        # Bailey format
        phone = data.get("phone", "")
        message = data.get("message", "").strip()

        # UltraMsg format (fallback)
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
            status_msg = bot_settings.get("clinic_status_message") or "Maafi chahta hun, clinic abhi band hai. Baad mein try karein. 🙏"
            return json.dumps({"reply": status_msg}), 200
        
        # Check clinic status
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
            appointments[apt_id] = {
                "name": data.get("name"), "phone": data.get("phone"),
                "time": data.get("time", "TBD"), "complaint": data.get("complaint", ""),
                "source": data.get("source", "Staff Added")
            }
            return json.dumps({"success": True}), 200
        except Exception as e:
            return json.dumps({"success": False}), 500
    return json.dumps(appointments, ensure_ascii=False), 200, {'Content-Type': 'application/json'}


@app.route("/send-report", methods=["POST"])
def send_report():
    try:
        data = request.json
        phone = data.get("phone")
        patient_name = data.get("name")
        report_note = data.get("note", "")
        message = f"📋 *Aapki Report Ready Hai!*\n\n👤 {patient_name} ji,\n\nAapki report tayar ho gayi hai.\n\nDoctor ka note:\n_{report_note}_\n\nKoi sawaal ho toh reply karein. 🙏\n_ClinicAI Demo Clinic_"
        send_whatsapp_message(phone, message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}), 500


@app.route("/send-reminder", methods=["POST"])
def send_reminder():
    try:
        data = request.json
        phone = data.get("phone")
        patient_name = data.get("name")
        appointment_time = data.get("time")
        message = f"🔔 *Appointment Reminder*\n\nNamaste {patient_name} ji!\n\nKal aapka appointment hai:\n⏰ {appointment_time}\n📍 ClinicAI Demo Clinic, Patna\n\nPlease samay par aayein. 🙏\n\n_ClinicAI System_"
        send_whatsapp_message(phone, message)
        return json.dumps({"success": True}), 200
    except Exception as e:
        return json.dumps({"success": False}), 500


@app.route("/doctor-summary", methods=["GET"])
def doctor_summary():
    today_appointments = list(appointments.values())
    if not today_appointments:
        summary = "📊 *Aaj Ka Schedule*\n\nAaj koi appointment nahi hai."
    else:
        summary = f"📊 *Aaj Ka Schedule - {datetime.now().strftime('%d %B %Y')}*\n\nTotal Appointments: {len(today_appointments)}\n\n"
        for i, apt in enumerate(today_appointments, 1):
            summary += f"{i}. *{apt['name']}* - {apt['time']}\n   Complaint: {apt['complaint']}\n\n"
    send_whatsapp_message(DOCTOR_NUMBER, summary)
    return json.dumps({"success": True, "summary": summary}), 200


@app.route("/bot-status", methods=["GET", "POST"])
def bot_status():
    global bot_paused
    if request.method == "POST":
        data = request.json
        bot_paused = data.get("paused", False)
        return json.dumps({"success": True, "paused": bot_paused}), 200
    return json.dumps({
        "paused": bot_paused,
        "messages_today": bot_stats["messages_today"],
        "total_appointments": len(appointments)
    }), 200


@app.route("/bot-settings", methods=["GET", "POST"])
def handle_bot_settings():
    global bot_settings, CLINIC_INFO, SYSTEM_PROMPT
    if request.method == "POST":
        data = request.json
        bot_settings.update({
            "clinic_name": data.get("clinic_name", bot_settings["clinic_name"]),
            "doctor_name": data.get("doctor_name", bot_settings["doctor_name"]),
            "fees": data.get("fees", bot_settings["fees"]),
            "language": data.get("language", bot_settings["language"]),
        })
        CLINIC_INFO = f"""
Clinic Name: {bot_settings['clinic_name']}
Doctor: {bot_settings['doctor_name']}
Timing: Monday to Saturday, 10am to 1pm and 4pm to 7pm
Fees: Rs. {bot_settings['fees']}
Location: Patna, Bihar
"""
        SYSTEM_PROMPT = f"""
Tu ek AI receptionist hai {bot_settings['clinic_name']} ka. Tera naam "ClinicAI" hai.
Tu Hindi aur English dono mein baat kar sakta hai - Hinglish bhi chalega.
Tu friendly aur professional hai.
Clinic ki information: {CLINIC_INFO}
Tera kaam hai:
1. Patients ko appointment book karne mein help karna
2. Clinic ki timing, fees aur location batana
3. Doctor se milne ka schedule set karna
Appointment book karne ka process:
- Pehle patient ka naam poochh
- Phir date aur time poochh (available slots: 10am, 11am, 12pm, 4pm, 5pm, 6pm)
- Phir unki takleef/complaint poochh
- Confirm karke appointment book karo
Agar koi emergency ho toh doctor ka number dena: {DOCTOR_NUMBER}
Hamesha short aur clear replies do - 3-4 lines max.
"""
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
        status = data.get("status", "normal")
        custom_msg = data.get("message", None)
        bot_settings["clinic_status"] = status
        bot_settings["clinic_status_msg"] = custom_msg
        return json.dumps({"success": True, "status": status}), 200
    return json.dumps({"status": bot_settings.get("clinic_status", "normal")}), 200


@app.route("/reminder-settings", methods=["GET", "POST"])
def reminder_settings():
    global bot_settings
    if request.method == "POST":
        data = request.json
        bot_settings["reminders"] = data
        return json.dumps({"success": True}), 200
    return json.dumps(bot_settings.get("reminders", {})), 200


@app.route("/stats", methods=["GET"])
def get_stats():
    return json.dumps({
        "messages_today": bot_stats["messages_today"],
        "total_appointments": len(appointments),
        "bot_paused": bot_paused
    }), 200


@app.route("/", methods=["GET"])
def home():
    return "ClinicAI Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
