from flask import Flask, request
from groq import Groq
import requests
import json
import os
from datetime import datetime

app = Flask(__name__)

# Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
BAILEYS_URL = os.environ.get("BAILEYS_URL", "https://clinicai-baileys.onrender.com")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")

# Groq Setup
client = Groq(api_key=GROQ_API_KEY)

# Patient data store
patients = {}
appointments = {}

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

Clinic ki information:
{CLINIC_INFO}

Tera kaam hai:
1. Patients ko appointment book karne mein help karna
2. Clinic ki timing, fees aur location batana
3. Doctor se milne ka schedule set karna
4. Politely aur clearly jawab dena

Appointment book karne ka process:
- Pehle patient ka naam poochh
- Phir date aur time poochh (available slots: 10am, 11am, 12pm, 4pm, 5pm, 6pm)
- Phir unki takleef/complaint poochh
- Confirm karke appointment book karo

Agar koi poochhe "slots kya hain" ya "kab available hai" toh available times batao.
Agar koi emergency ho toh doctor ka number dena: {DOCTOR_NUMBER}

Hamesha short aur clear replies do - 3-4 lines max.
Emojis use kar sakte ho but zyada nahi.
"""

def send_whatsapp_message(to, message):
    try:
        response = requests.post(f"{BAILEYS_URL}/send", json={
            "to": to,
            "message": message
        }, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def notify_doctor(patient_name, phone, time, complaint):
    message = f"""🔔 *Naya Appointment Book Hua!*

👤 Patient: {patient_name}
📱 Phone: {phone}
⏰ Time: {time}
🏥 Complaint: {complaint}

_ClinicAI System_"""
    send_whatsapp_message(DOCTOR_NUMBER, message)

def get_ai_response(user_message, phone):
    try:
        patient = patients.get(phone, {})
        context = ""
        if patient.get("name"):
            context = f"\nPatient ka naam: {patient['name']}"
        if patient.get("appointment"):
            apt = patient["appointment"]
            context += f"\nAppointment details: {json.dumps(apt, ensure_ascii=False)}"

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

    if message_lower.startswith("add:") and phone == DOCTOR_NUMBER:
        try:
            parts = message[4:].strip().split(",")
            name = parts[0].strip()
            time = parts[1].strip() if len(parts) > 1 else "TBD"
            complaint = parts[2].strip() if len(parts) > 2 else "Not specified"
            apt_id = f"APT{len(appointments)+1}"
            appointments[apt_id] = {
                "name": name, "time": time,
                "complaint": complaint, "source": "Staff Added"
            }
            return f"✅ Patient add ho gaya!\n👤 {name}\n⏰ {time}\n🏥 {complaint}"
        except:
            return "❌ Format sahi nahi hai. Ye use karein:\nADD: Naam, Time, Complaint"

    if message_lower.startswith("off:") and phone == DOCTOR_NUMBER:
        date_range = message[4:].strip()
        return f"✅ Off set ho gaya: {date_range}"

    if message_lower.startswith("full:") and phone == DOCTOR_NUMBER:
        return "✅ Aaj ke liye sab slots full mark ho gaye."

    if patient["step"] == "new" or message_lower in ["hi", "hello", "namaste", "hii", "hey"]:
        patients[phone]["step"] = "greeted"
        return """Namaste! 🙏 ClinicAI Demo Clinic mein aapka swagat hai!

Main aapki kaise madad kar sakta hun?

1️⃣ Appointment book karni hai
2️⃣ Clinic timing/fees jaanni hai  
3️⃣ Doctor se urgent milna hai"""

    if any(word in message_lower for word in ["appointment", "book", "milna", "doctor", "1", "slot"]):
        if not patient.get("name"):
            patients[phone]["step"] = "getting_name"
            return "Zaroor! 😊 Pehle aapka naam batayein?"

    if patient["step"] == "getting_name":
        patients[phone]["name"] = message.strip().title()
        patients[phone]["step"] = "getting_time"
        return f"""Shukriya {patients[phone]['name']} ji! 😊

Kab aana chahte hain? Available slots:

🌅 *Subah:* 10am, 11am, 12pm
🌆 *Shaam:* 4pm, 5pm, 6pm

(Mon-Sat)"""

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
        appointments[apt_id] = {
            "name": name, "phone": phone,
            "time": time, "complaint": complaint,
            "source": "WhatsApp Bot"
        }

        notify_doctor(name, phone, time, complaint)
        patients[phone]["step"] = "done"

        return f"""✅ *Appointment Confirm Ho Gayi!*

👤 Naam: {name}
⏰ Time: {time}
🏥 Complaint: {complaint}
📍 ClinicAI Demo Clinic, Patna

Aapko ek din pehle reminder bhi aayega! 🔔

Koi aur sawaal ho toh batayein. 🙏"""

    if patient["step"] == "done":
        patients[phone]["step"] = "greeted"

    if any(word in message_lower for word in ["fees", "kitna", "charge", "price", "2"]):
        return "Dr. Kunal ki consultation fees *₹300* hai. 💊\nPayment cash ya UPI se clinic pe ho sakti hai."

    if any(word in message_lower for word in ["timing", "time", "kab", "khula", "open", "band"]):
        return "Clinic timing:\n🌅 *Subah:* 10am - 1pm\n🌆 *Shaam:* 4pm - 7pm\n📅 Monday to Saturday\n\n(Sunday band rehta hai)"

    if any(word in message_lower for word in ["address", "location", "kahan", "where", "3"]):
        return "📍 ClinicAI Demo Clinic\nPatna, Bihar\n\nGoogle Maps pe 'ClinicAI Demo Clinic' search karein!"

    if any(word in message_lower for word in ["urgent", "emergency"]):
        return f"🚨 Emergency ke liye seedha call karein:\n📞 +{DOCTOR_NUMBER}\n\nClinic timing ke baad bhi available hain!"

    return get_ai_response(message, phone)


# Baileys se message aata hai yahan
@app.route("/process", methods=["POST"])
def process():
    try:
        data = request.json
        phone = data.get("phone", "").replace("+", "")
        message = data.get("message", "").strip()

        if not phone or not message:
            return json.dumps({"reply": None}), 200

        print(f"Message from {phone}: {message}")
        reply = process_message(phone, message)
        return json.dumps({"reply": reply}, ensure_ascii=False), 200

    except Exception as e:
        print(f"Process error: {e}")
        return json.dumps({"reply": None}), 200


@app.route("/appointments", methods=["GET"])
def get_appointments():
    return json.dumps(appointments, ensure_ascii=False), 200, {'Content-Type': 'application/json'}


@app.route("/send-report", methods=["POST"])
def send_report():
    try:
        data = request.json
        phone = data.get("phone")
        patient_name = data.get("name")
        report_note = data.get("note", "")

        message = f"""📋 *Aapki Report Ready Hai!*

👤 {patient_name} ji,

Aapki report tayar ho gayi hai.

Doctor ka note:
_{report_note}_

Koi sawaal ho toh reply karein. 🙏
_ClinicAI Demo Clinic_"""

        result = send_whatsapp_message(phone, message)
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

        message = f"""🔔 *Appointment Reminder*

Namaste {patient_name} ji! 

Kal aapka appointment hai:
⏰ {appointment_time}
📍 ClinicAI Demo Clinic, Patna

Please samay par aayein. 🙏

_ClinicAI System_"""

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
        summary = f"📊 *Aaj Ka Schedule - {datetime.now().strftime('%d %B %Y')}*\n\n"
        summary += f"Total Appointments: {len(today_appointments)}\n\n"
        for i, apt in enumerate(today_appointments, 1):
            summary += f"{i}. *{apt['name']}* - {apt['time']}\n   Complaint: {apt['complaint']}\n\n"

    send_whatsapp_message(DOCTOR_NUMBER, summary)
    return json.dumps({"success": True, "summary": summary}), 200


@app.route("/", methods=["GET"])
def home():
    return "ClinicAI Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
