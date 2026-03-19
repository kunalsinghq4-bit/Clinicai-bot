const { default: makeWASocket, DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys')
const express = require('express')
const qrcode = require('qrcode')
const axios = require('axios')
const pino = require('pino')

const app = express()
app.use(express.json())

let sock = null
let qrCodeData = null
let isConnected = false

// Yahan apna Python bot ka Render URL daalo
const PYTHON_BOT_URL = process.env.PYTHON_BOT_URL || 'https://clinicai-bot.onrender.com'

async function connectWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info')

    sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false
    })

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update

        if (qr) {
            console.log('QR Code ready - visit /qr to scan')
            qrCodeData = await qrcode.toDataURL(qr)
        }

        if (connection === 'close') {
            isConnected = false
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut
            console.log('Connection closed. Reconnecting:', shouldReconnect)
            if (shouldReconnect) {
                connectWhatsApp()
            }
        } else if (connection === 'open') {
            isConnected = true
            qrCodeData = null
            console.log('WhatsApp Connected!')
        }
    })

    sock.ev.on('creds.update', saveCreds)

    // Incoming messages handle karo
    sock.ev.on('messages.upsert', async ({ messages }) => {
        for (const msg of messages) {
            if (msg.key.fromMe) continue
            if (!msg.message) continue

            const from = msg.key.remoteJid
            const text = msg.message?.conversation || 
                         msg.message?.extendedTextMessage?.text || ''

            if (!text) continue

            const phone = from.replace('@s.whatsapp.net', '').replace('+', '')
            console.log(`Message from ${phone}: ${text}`)

            try {
                // Python bot ko message bhejo processing ke liye
                const response = await axios.post(`${PYTHON_BOT_URL}/process`, {
                    phone: phone,
                    message: text
                })

                const reply = response.data.reply
                if (reply) {
                    await sock.sendMessage(from, { text: reply })
                }
            } catch (err) {
                console.error('Error processing message:', err.message)
                await sock.sendMessage(from, { 
                    text: 'Maafi chahta hun, abhi kuch technical problem hai. Thodi der baad try karein. 🙏' 
                })
            }
        }
    })
}

// QR Code page
app.get('/qr', (req, res) => {
    if (isConnected) {
        return res.send('<h2 style="color:green;font-family:sans-serif;">✅ WhatsApp Connected Hai!</h2>')
    }
    if (!qrCodeData) {
        return res.send('<h2 style="font-family:sans-serif;">⏳ QR Generate ho raha hai... Thodi der baad refresh karein.</h2>')
    }
    res.send(`
        <html>
        <body style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#0a0a0a;color:white;">
            <h2>📱 WhatsApp Scan Karein</h2>
            <img src="${qrCodeData}" style="width:300px;border-radius:12px;" />
            <p style="color:#aaa;">Scan ke baad page refresh karein</p>
        </body>
        </html>
    `)
})

// Send message endpoint (Python bot use karega)
app.post('/send', async (req, res) => {
    const { to, message } = req.body
    if (!isConnected || !sock) {
        return res.json({ success: false, error: 'WhatsApp connected nahi hai' })
    }
    try {
        const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`
        await sock.sendMessage(jid, { text: message })
        res.json({ success: true })
    } catch (err) {
        res.json({ success: false, error: err.message })
    }
})

// Status endpoint
app.get('/status', (req, res) => {
    res.json({ connected: isConnected })
})

app.get('/', (req, res) => {
    res.send('ClinicAI Baileys Server Running! 🚀')
})

const PORT = process.env.PORT || 3000
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`)
    connectWhatsApp()
})
