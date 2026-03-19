const { default: makeWASocket, DisconnectReason, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys')
const express = require('express')
const qrcode = require('qrcode')
const axios = require('axios')
const pino = require('pino')

const app = express()
app.use(express.json())

let sock = null
let qrCodeData = null
let isConnected = false
let connectionAttempts = 0

const PYTHON_BOT_URL = process.env.PYTHON_BOT_URL || 'https://clinicai-bot.onrender.com'

async function connectWhatsApp() {
    connectionAttempts++
    console.log(`Connection attempt #${connectionAttempts}`)

    const { state, saveCreds } = await useMultiFileAuthState('auth_info')
    const { version } = await fetchLatestBaileysVersion()
    console.log(`Using WA v${version.join('.')}`)

    sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: true,
        browser: ['ClinicAI', 'Chrome', '1.0'],
        connectTimeoutMs: 60000,
        defaultQueryTimeoutMs: 60000,
        keepAliveIntervalMs: 30000,
    })

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update

        if (qr) {
            console.log('QR Code generated! Visit /qr to scan.')
            qrCodeData = await qrcode.toDataURL(qr)
        }

        if (connection === 'close') {
            isConnected = false
            const statusCode = lastDisconnect?.error?.output?.statusCode
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut

            console.log(`Connection closed. Status: ${statusCode}. Reconnecting: ${shouldReconnect}`)

            if (shouldReconnect && connectionAttempts < 20) {
                setTimeout(connectWhatsApp, 5000)
            } else {
                console.log('Max reconnection attempts reached or logged out.')
            }
        } else if (connection === 'open') {
            isConnected = true
            qrCodeData = null
            connectionAttempts = 0
            console.log('WhatsApp Connected Successfully!')
        }
    })

    sock.ev.on('creds.update', saveCreds)

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

app.get('/qr', (req, res) => {
    if (isConnected) {
        return res.send('<h2 style="color:green;font-family:sans-serif;text-align:center;margin-top:100px;">✅ WhatsApp Connected Hai!</h2>')
    }
    if (!qrCodeData) {
        return res.send(`
            <html>
            <head><meta http-equiv="refresh" content="5"></head>
            <body style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#0a0a0a;color:white;">
                <h2>⏳ QR Generate ho raha hai...</h2>
                <p style="color:#aaa;">Page automatically refresh hoga. Attempts: ${connectionAttempts}</p>
            </body>
            </html>
        `)
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

app.get('/status', (req, res) => {
    res.json({ connected: isConnected, attempts: connectionAttempts })
})

app.get('/', (req, res) => {
    res.send(`ClinicAI Baileys Server Running! 🚀 Connected: ${isConnected}`)
})

const PORT = process.env.PORT || 3000
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`)
    connectWhatsApp()
})
