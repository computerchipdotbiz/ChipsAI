"""
Interactive Terminal Simulator for ChipAI
Allows testing conversations, reminders, and tool calling without needing Twilio.
"""
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

import database
import scheduler
import assistant

USER_PHONE = os.getenv("USER_PHONE_NUMBER", "+15555555555")


def main():
    print("=" * 60)
    print("🤖 Welcome to ChipAI Terminal Simulator")
    print(f"📱 Simulated Phone: {USER_PHONE}")
    print(f"⏰ User Timezone: {os.getenv('USER_TIMEZONE', 'America/Chicago')}")
    print("Type your message below. Type 'exit' or 'quit' to quit.")
    print("=" * 60)

    # Initialize database
    database.init_db()

    # Start background scheduler to watch reminders in real-time
    scheduler.start_scheduler(interval_seconds=5)

    try:
        while True:
            try:
                user_input = input("\nYou > ").strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "q"]:
                print("\nGoodbye!")
                break

            if user_input.lower() == "/reminders":
                active = database.list_active_reminders(USER_PHONE)
                print(f"\n[DB] Active Reminders ({len(active)}):")
                for r in active:
                    print(f"  #{r['id']}: {r['reminder_text']} @ {r['scheduled_time']} (UTC)")
                continue

            print("Chip is thinking...", end="\r", flush=True)
            response = assistant.process_message(USER_PHONE, user_input)
            print(f"Chip > {response}")

    finally:
        scheduler.stop_scheduler()


if __name__ == "__main__":
    main()
