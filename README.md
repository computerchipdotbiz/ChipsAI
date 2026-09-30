# 🤖 Sarahzine 800 — Always-On 24/7 Personal AI Assistant & Proactive Companion

Sarahzine 800 is an authentic, sharp, and proactive personal AI companion built for Chip. Powered by **Google Gemini**, Telegram (text & voice), and Twilio SMS. It lives in the cloud, listens and speaks over voice memos and text, schedules intelligent reminders, and proactively reaches out like a real friend (anticipatory prep check-ins ~10h before talks/events, random friend check-ins, and zero corporate fluff).

---

## 🌟 Key Features

- **Direct Telegram & SMS Chat**: Text questions, brainstorm, or send voice memos with automated speech-to-text and Jenny neural voice replies.
- **Anticipatory Prep Check-ins**: When an important talk or event is coming up (e.g. talking with Andy about work study plans), Sarahzine 800 proactively reaches out ~10 hours before to see how you're feeling and help talk through points.
- **Random Friend Check-ins**: Reaches out periodically on random life topics (recent IT projects at Fox, personal tasks you're wrestling with, relationship dynamics, meals you're craving this week, hobbies/downtime) like a real friend.
- **Strict Quiet Hours & Deduping**: Absolute quiet hours between 10:00 PM and 7:00 AM local time. Deduplicated so every subject is only checked once.
- **Natural Language Reminders**: Natural scheduling with one-shot and recurring support (`daily`, `weekdays`, `weekly`).
- **Whitelist Security Filter**: Drops unauthorized senders to protect privacy and token usage.
- **Persistent Storage**: Full SQLite and PostgreSQL support.
- **100% Cloud Ready**: Includes Dockerfile, Procfile, and Render blueprint for easy 24/7 cloud hosting.

---

## 📋 Prerequisites

1. **Google AI Studio API Key**:
   - Get a free Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. **Twilio Account**:
   - Sign up at [twilio.com](https://www.twilio.com/).
   - Obtain a phone number with SMS capabilities (~$1.15/month).
   - Get your `Account SID`, `Auth Token`, and Twilio Phone Number from the Twilio Console.
3. **Cloud Host Account (Free / Low Cost)**:
   - [Render](https://render.com) (recommended), [Railway](https://railway.app), or [Fly.io](https://fly.io).

---

## 🚀 Quickstart (Local Testing)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in:
- `GEMINI_API_KEY`: Your Gemini API key.
- `USER_PHONE_NUMBER`: Your personal mobile phone number (e.g. `+15551234567`).
- `USER_TIMEZONE`: Your local timezone (e.g. `America/Chicago`, `America/New_York`, `America/Los_Angeles`).

*(Twilio keys are only required when sending actual SMS; you can test conversational replies and reminder scheduling locally without Twilio!)*

### 3. Run the Local Terminal Simulator
```bash
python test_cli.py
```
You can chat with Chip directly in your terminal:
- Try asking: *"What is the capital of France?"*
- Try scheduling: *"Remind me in 1 minute to stretch."*
- Type `/reminders` to inspect scheduled reminders in the SQLite database.

---

## 🌐 Cloud Deployment (24/7 Always-On)

### Option A: Render (Easiest)
1. Push this project folder to a GitHub repository (public or private).
2. Go to [dashboard.render.com](https://dashboard.render.com/) and click **New > Web Service**.
3. Select your repository.
4. Render will auto-detect the configuration using `render.yaml` or you can configure manually:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. In **Environment Variables**, add:
   - `GEMINI_API_KEY`
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_PHONE_NUMBER`
   - `USER_PHONE_NUMBER`
   - `USER_TIMEZONE`
6. Click **Deploy**. Note your service URL (e.g. `https://chipai-sms-assistant.onrender.com`).

---

## 📲 Connecting Twilio to Your Webhook

Once your cloud service is running:
1. Open the [Twilio Console](https://console.twilio.com/).
2. Navigate to **Phone Numbers > Manage > Active Numbers**.
3. Click on your Twilio Phone Number.
4. Scroll down to **Messaging Configuration**.
5. Under **A MESSAGE COMES IN**:
   - Set to **Webhook**.
   - URL: `https://your-app-name.onrender.com/sms`
   - HTTP Method: **HTTP POST**.
6. Click **Save Configuration**.

Now pick up your cell phone and send an SMS to your Twilio number! 🚀
