import os
import json
import logging
from datetime import datetime, timezone
import pytz
from dotenv import load_dotenv
import database

load_dotenv()

logger = logging.getLogger("chipai.assistant")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "America/Chicago")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def get_current_user_time_info() -> dict:
    """Return current user local time and timezone metadata."""
    try:
        tz = pytz.timezone(USER_TIMEZONE)
    except Exception:
        tz = pytz.timezone("UTC")
    now_local = datetime.now(tz)
    return {
        "timezone": USER_TIMEZONE,
        "current_local_iso": now_local.isoformat(),
        "current_local_readable": now_local.strftime("%A, %B %d, %Y at %I:%M %p %Z"),
    }


def convert_to_utc_iso(target_time_str: str) -> str:
    """Parse a date/time string from Gemini and convert it to UTC ISO 8601."""
    from dateutil import parser

    try:
        tz = pytz.timezone(USER_TIMEZONE)
    except Exception:
        tz = pytz.timezone("UTC")

    dt = parser.parse(target_time_str)
    if dt.tzinfo is None:
        # Assume it's in user's local timezone
        dt = tz.localize(dt)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.isoformat()


def build_system_instruction() -> str:
    time_info = get_current_user_time_info()
    return f"""# Identity & Core Directive
You are ChipAI, an authentic, sharp, and practical AI partner built specifically for Chip (Boyce Lee Gowan III). You act like a trusted, experienced peer and close friend who wants the absolute best for him. When he wins, you win.
You are communicating with Chip directly over SMS text messaging.

# Core Personality & Demeanor
- Direct, candid, and grounded: Value honesty above all else. Tell it like it is with zero sugar-coating. Share strong, well-reasoned opinions without hesitation.
- No corporate cheerleading: Eliminate sycophantic praise, excessive validation ("You're so right!"), robotic motivational talk, and patronizing fluff. Acknowledge wins naturally, not performatively.
- Zero parenting or lecturing: Chip is a 49-year-old adult. Never lecture, scold, or police his choices, tech practices, or questions. Never drop unsolicited safety or life disclaimers.
- Playful and witty: Lean into casual, dry, or goofy humor when appropriate, but never let it get in the way of getting work done.
- Never guess: If critical info is missing, say you don't know and ask directly for clarification instead of making assumptions.

# Formatting & Communication Rules
- Medium: You are chatting over SMS. Keep responses reasonably concise and readable on a phone screen.
- Never use em dashes: Strictly ban em dashes (—) in all output. Use standard commas, parentheses, or clean line breaks.
- Direct openings only: Never waste time with greeting fluff or conversational filler ("Sure thing!", "Here is a guide to...", "That is a great question!"). Lead directly with the answer in sentence one.
- Structural TL;DR rule:
  * For general advice, casual queries, life organizing, or broad info: Always open with a punchy, one-sentence TL;DR summary before the details.
  * For tech, system admin, IT infrastructure, and scripting: NEVER include a TL;DR. Jump straight into clean code, exact commands, architectural specs, and step-by-step logic.

# Time & Scheduling Context
- Timezone: '{time_info["timezone"]}'. Current local time: {time_info["current_local_readable"]} ({time_info["current_local_iso"]}).
- One-Shot Reminders: When Chip asks for a one-time reminder (e.g., 'remind me in 30 minutes to check the mail', 'remind me tomorrow at 9am to check Wazuh'), compute the target date and time in his local timezone and invoke `set_reminder(reminder_text, target_time_iso, recurrence='none')`.
- Recurring Reminders: You have full native support for recurring reminders! When Chip asks for a repeating reminder (e.g. 'remind me every day at 6pm to give Liam his medicine', 'every weekday at 8am to check backups'):
  1. Calculate the target timestamp for the first upcoming occurrence. (If the target time has not passed yet today, set it for today. If it has already passed today, set it for tomorrow).
  2. Set recurrence to 'daily', 'weekdays', or 'weekly'.
  3. Invoke `set_reminder(reminder_text, target_time_iso, recurrence)`.
  4. Confirm to Chip clearly that the reminder is scheduled, what time it fires, and that it repeats daily/weekly.
- Tools available: `set_reminder`, `list_reminders`, `cancel_reminder`. Always confirm reminder schedule and subject clearly.

# Chip's Background & Profile
- Name & Age: Chip (legal name: Boyce Lee Gowan III), 49 years old.
- Location: Mansfield, Texas.
- Career: Sole IT Manager at Fox Scientific in Alvarado, TX. Over 29 years of hands-on experience in enterprise systems administration and IT infrastructure.
- Technical Wheelhouse: Active Directory, Group Policy (GPOs), PowerShell automation, Wazuh SIEM, Fortinet/FortiGate firewalls, Proxmox VE, Hyper-V, VMware, IIS, Zimbra, Openfire, Tailscale, RustDesk, Cockpit, and Linux/Windows hybrid networking.
- Current Studies: Enrolled in Maestro University, pursuing an Associate of Science in AI Software Engineering.
- Personal Life & Household:
  * Lives in Mansfield with his girlfriend, Jen.
  * Has three sons; Jen has one son (Liam).
  * Dogs: Newton (a Great Pyrenees) and Kirby (a Dachshund).
  * Vehicle: Drives a 2025 Hyundai Elantra Hybrid Blue.
- Personal Interests & Tools:
  * Gaming: World of Warcraft (talent builds, class mechanics) and Last War: Survival (handles account DigitlArthas).
  * Tech gear: PLAUD NotePin AI voice recorder, Renpho Lynx smart ring.
  * Coffee: Brews with a Ninja Luxe Café Premier machine using Lavazza Super Crema beans.
  * Movies/TV/Music: "The Crow", "Terminator 2", "SLC Punk!", "Dirty Dancing", "LOST", "The Sopranos", "The Walking Dead", Wheatus, Bryan Adams, Paula Abdul.
  * Hobbies: Out-The-Front (OTF) pocket knives, glamping (Postcard Cabins in Wimberley, Piney Woods in LaRue), cross-stitch while relaxing in the evenings, swimming pool maintenance (testing, CYA, alkalinity, timers).
"""


def execute_tool(tool_name: str, args: dict, user_phone: str) -> dict:
    """Execute python functions called by Gemini tools."""
    logger.info(f"Executing tool {tool_name} with args: {args}")

    if tool_name == "set_reminder":
        text = args.get("reminder_text", "")
        time_str = args.get("target_time_iso", "")
        recurrence = args.get("recurrence", "none")
        try:
            utc_iso = convert_to_utc_iso(time_str)
            reminder_id = database.add_reminder(user_phone, text, utc_iso, recurrence=recurrence)
            rec_desc = f" (repeats {recurrence})" if recurrence and recurrence != "none" else ""
            return {
                "success": True,
                "reminder_id": reminder_id,
                "message": f"Reminder #{reminder_id} set for '{text}' at {time_str}{rec_desc} ({utc_iso} UTC).",
            }
        except Exception as e:
            logger.error(f"Failed to set reminder: {e}")
            return {"success": False, "error": str(e)}

    elif tool_name == "list_reminders":
        try:
            reminders = database.list_active_reminders(user_phone)
            tz = pytz.timezone(USER_TIMEZONE)
            formatted = []
            for r in reminders:
                dt_utc = datetime.fromisoformat(r["scheduled_time"])
                dt_local = dt_utc.astimezone(tz)
                rec = r.get("recurrence", "none")
                rec_label = f" [repeats {rec}]" if rec and rec != "none" else ""
                formatted.append({
                    "id": r["id"],
                    "text": r["reminder_text"] + rec_label,
                    "scheduled_local": dt_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                })
            return {"success": True, "active_reminders": formatted}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif tool_name == "cancel_reminder":
        reminder_id = args.get("reminder_id")
        try:
            ok = database.cancel_reminder(int(reminder_id), user_phone)
            return {"success": ok, "cancelled_id": reminder_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"error": f"Unknown tool: {tool_name}"}


def process_message(user_phone: str, incoming_text: str) -> str:
    """Process an incoming SMS message through Gemini with tool calling."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return "ChipAI here! Gemini API key is not configured yet. Please add GEMINI_API_KEY to your .env file."

    # Save incoming user message
    database.save_message(user_phone, "user", incoming_text)

    # Tool definitions
    tools = [
        {
            "name": "set_reminder",
            "description": "Schedule an outbound reminder text for the user at a specified date/time.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "reminder_text": {
                        "type": "STRING",
                        "description": "What the user wants to be reminded about.",
                    },
                    "target_time_iso": {
                        "type": "STRING",
                        "description": "The exact target date and time in ISO 8601 format (e.g. 2026-09-29T17:30:00).",
                    },
                    "recurrence": {
                        "type": "STRING",
                        "enum": ["none", "daily", "weekdays", "weekly"],
                        "description": "How often to repeat: 'none' for one-shot, 'daily' for every day, 'weekdays' for Monday-Friday, 'weekly' for once a week.",
                    },
                },
                "required": ["reminder_text", "target_time_iso"],
            },
        },
        {
            "name": "list_reminders",
            "description": "List all active upcoming reminders for the user.",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
            },
        },
        {
            "name": "cancel_reminder",
            "description": "Cancel a pending reminder by its numeric ID.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "reminder_id": {
                        "type": "INTEGER",
                        "description": "The ID number of the reminder to cancel.",
                    },
                },
                "required": ["reminder_id"],
            },
        },
    ]

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Retrieve recent history for context
        history_rows = database.get_recent_history(user_phone, limit=6)
        contents = []
        for row in history_rows:
            role = "user" if row["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=row["content"])]))

        system_instruction = build_system_instruction()

        # Build function declarations
        func_declarations = []
        for t in tools:
            func_declarations.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["parameters"],
                )
            )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=func_declarations)],
            temperature=0.7,
        )

        models_to_try = [MODEL_NAME]
        if MODEL_NAME != "gemini-3.5-flash-lite":
            models_to_try.append("gemini-3.5-flash-lite")

        last_error = None
        for current_model in models_to_try:
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )

                # Handle tool calling loop
                while response.function_calls:
                    call = response.function_calls[0]
                    tool_name = call.name
                    args = dict(call.args) if call.args else {}

                    tool_result = execute_tool(tool_name, args, user_phone)

                    # Append model's tool call & function response to contents
                    contents.append(response.candidates[0].content)
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_function_response(
                                    name=tool_name,
                                    response={"result": tool_result},
                                )
                            ],
                        )
                    )

                    # Follow-up generation after tool execution
                    response = client.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=config,
                    )

                reply = response.text or "I got your message!"
                # Strictly ban em dashes and en dashes
                reply = reply.replace("—", ", ").replace("–", "-")
                database.save_message(user_phone, "model", reply)
                return reply

            except Exception as e:
                last_error = e
                logger.warning(f"Model {current_model} error: {e}. Trying fallback if available...")
        logger.error(f"All models failed for message: {last_error}", exc_info=True)
        if last_error and ("429" in str(last_error) or "RESOURCE_EXHAUSTED" in str(last_error)):
            return "ChipAI is catching its breath (rate limit reached on free tier). Please try texting again in 30 seconds!"
        return "Sorry, I ran into a temporary issue processing your text. Please try again shortly."

    except Exception as e:
        logger.error(f"Fatal error in Gemini assistant processing: {e}", exc_info=True)
        return "Sorry, I encountered an internal error. Please try again shortly."
