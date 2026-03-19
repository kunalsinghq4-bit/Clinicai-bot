from flask import Flask, request
import requests
import google.generativeai as genai
import json
import os
from datetime import datetime

app = Flask(__name__)

# Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAD8NbHlOocwmU1jP_a_pVtrnE2dDZcReU")
ULTRAMSG_INSTANCE = os.environ.get("ULTRAMSG_INSTANCE", "instance166153")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN", "ch512e62wj5hxj36")
DOCTOR_NUMBER = os.environ.get("DOCTOR_NUMBER", "916205131181")  # Doctor ka WhatsApp number

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# Patient data store (in-memory, resets on restart)
# Format: { "phone": { "name": "", "step": "", "appointment": {} } }
patients = {}

# Appointments store
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
    """Send WhatsApp message via UltraMsg"""
    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat"
    payload = {
        "token": ULTRAMSG_TOKEN,
        "to": to,
        "body": message,
        "priority": 10
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def notify_doctor(patient_name, phone, time, complaint):
    """Notify doctor about new appointment"""
    message = f"""🔔 *Naya Appointment Book Hua!*

👤 Patient: {patient_name}
📱 Phone: {phone}
⏰ Time: {time}
🏥 Complaint: {complaint}

_ClinicAI System_"""
    send_whatsapp_message(DOCTOR_NUMBER, message)

def get_ai_response(user_message, phone):
    """Get response from Gemini AI"""
    try:
        # Build conversation context
        patient = patients.get(phone, {})
        context = ""
        if patient.get("name"):
            context = f"\nPatient ka naam: {patient['name']}"
        if patient.get("appointment"):
            apt = patient["appointment"]
            context += f"\nAppointment details: {json.dumps(apt, ensure_ascii=False)}"

        full_prompt = SYSTEM_PROMPT + context + f"\n\nPatient ne kaha: {user_message}\n\nTera jawab:"
        
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        print(f"Gemini error: {e}")
        return "Maafi chahta hun, abhi kuch technical problem hai. Thodi der baad try karein. 🙏"

def process_message(phone, message):
    """Process incoming WhatsApp message"""
    message_lower = message.lower().strip()
    
    # Initialize patient if new
    if phone not in patients:
        patients[phone] = {"name": None, "step": "new", "appointment": {}}
    
    patient = patients[phone]
    
    # Staff command: ADD patient manually
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
    
    # Staff command: OFF days
    if message_lower.startswith("off:") and phone == DOCTOR_NUMBER:
        date_range = message[4:].strip()
        return f"✅ Off set ho gaya: {date_range}\nBot automatically patients ko batayega."
    
    # Staff command: FULL today
    if message_lower.startswith("full:") and phone == DOCTOR_NUMBER:
        return "✅ Aaj ke liye sab slots full mark ho gaye.\nBot nayi appointments nahi lega aaj."

    # Greeting - new patient
    if patient["step"] == "new" or message_lower in ["hi", "hello", "namaste", "hii", "hey"]:
        patients[phone]["step"] = "greeted"
        return """Namaste! 🙏 ClinicAI Demo Clinic mein aapka swagat hai!

Main aapki kaise madad kar sakta hun?

1️⃣ Appointment book karni hai
2️⃣ Clinic timing/fees jaanni hai  
3️⃣ Doctor se urgent milna hai"""

    # Appointment booking flow
    if any(word in message_lower for word in ["appointment", "book", "milna", "doctor", "1", "slot"]):
        if not patient.get("name"):
            patients[phone]["step"] = "getting_name"
            return "Zaroor! 😊 Pehle aapka naam batayein?"
    
    # Getting name
    if patient["step"] == "getting_name":
        patients[phone]["name"] = message.strip().title()
        patients[phone]["step"] = "getting_time"
        return f"""Shukriya {patients[phone]['name']} ji! 😊

Kab aana chahte hain? Available slots:

🌅 *Subah:* 10am, 11am, 12pm
🌆 *Shaam:* 4pm, 5pm, 6pm

(Mon-Sat)"""
    
    # Getting time
    if patient["step"] == "getting_time":
        patients[phone]["appointment"]["time"] = message.strip()
        patients[phone]["step"] = "getting_complaint"
        return "Theek hai! 👍 Aur batayein - kya takleef hai ya kyun milna chahte hain doctor se?"
    
    # Getting complaint
    if patient["step"] == "getting_complaint":
        patients[phone]["appointment"]["complaint"] = message.strip()
        patients[phone]["step"] = "confirmed"
        
        name = patients[phone]["name"]
        time = patients[phone]["appointment"].get("time", "TBD")
        complaint = patients[phone]["appointment"].get("complaint", "")
        
        # Save appointment
        apt_id = f"APT{len(appointments)+1}"
        appointments[apt_id] = {
            "name": name, "phone": phone,
            "time": time, "complaint": complaint,
            "source": "WhatsApp Bot"
        }
        
        # Notify doctor
        notify_doctor(name, phone, time, complaint)
        
        # Reset for next interaction
        patients[phone]["step"] = "done"
        
        return f"""✅ *Appointment Confirm Ho Gayi!*

👤 Naam: {name}
⏰ Time: {time}
🏥 Complaint: {complaint}
📍 ClinicAI Demo Clinic, Patna

Aapko ek din pehle reminder bhi aayega! 🔔

Koi aur sawaal ho toh batayein. 🙏"""
    
    # Reset after done
    if patient["step"] == "done":
        patients[phone]["step"] = "greeted"
    
    # Fees/timing queries
    if any(word in message_lower for word in ["fees", "kitna", "charge", "price", "2"]):
        return "Dr. Kunal ki consultation fees *₹300* hai. 💊\nPayment cash ya UPI se clinic pe ho sakti hai."
    
    if any(word in message_lower for word in ["timing", "time", "kab", "khula", "open", "band"]):
        return "Clinic timing:\n🌅 *Subah:* 10am - 1pm\n🌆 *Shaam:* 4pm - 7pm\n📅 Monday to Saturday\n\n(Sunday band rehta hai)"
    
    if any(word in message_lower for word in ["address", "location", "kahan", "where", "3"]):
        return "📍 ClinicAI Demo Clinic\nPatna, Bihar\n\nGoogle Maps pe 'ClinicAI Demo Clinic' search karein!"
    
    if any(word in message_lower for word in ["urgent", "emergency"]):
        return f"🚨 Emergency ke liye seedha call karein:\n📞 +{DOCTOR_NUMBER}\n\nClinic timing ke baad bhi available hain!"
    
    # Default - use Gemini AI
    return get_ai_response(message, phone)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive WhatsApp messages from UltraMsg"""
    try:
        data = request.json
        
        if not data:
            return "OK", 200
        
        # Extract message details
        msg_data = data.get("data", {})
        message = msg_data.get("body", "").strip()
        from_number = msg_data.get("from", "").replace("@c.us", "").replace("+", "")
        msg_type = msg_data.get("type", "")
        from_me = msg_data.get("fromMe", False)
        
        # Ignore if sent by bot itself or empty
        if from_me or not message or msg_type != "chat":
            return "OK", 200
        
        print(f"Message from {from_number}: {message}")
        
        # Process and respond
        response = process_message(from_number, message)
        
        if response:
            send_whatsapp_message(f"+{from_number}", response)
        
        return "OK", 200
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return "OK", 200


@app.route("/appointments", methods=["GET"])
def get_appointments():
    """Get all appointments - for staff panel"""
    return json.dumps(appointments, ensure_ascii=False), 200, {'Content-Type': 'application/json'}


@app.route("/send-report", methods=["POST"])
def send_report():
    """Send report to patient - from staff panel"""
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
    """Send reminder to patient"""
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
    """Send today's summary to doctor"""
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
