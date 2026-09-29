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
    return f"""You are Chip, a friendly, concise, highly capable personal SMS assistant.
You are communicating with the user directly over SMS text messaging.

Key Guidelines:
1. Conciseness: Keep responses short and punchy (1-3 sentences), since they are delivered via SMS. Avoid verbose markdown formatting (no complex tables or large ASCII art).
2. Time Context: The user's timezone is '{time_info["timezone"]}'. Their current local time is {time_info["current_local_readable"]} ({time_info["current_local_iso"]}).
3. Reminders:
   - When the user asks you to remind them of something (e.g., 'remind me in 30 minutes to check the mail', 'remind me tomorrow at 9am to call mom'), compute the exact target date and time in their local timezone.
   - Call the `set_reminder` tool with the text and the target ISO timestamp.
   - Always confirm the reminder time and subject to the user in your reply.
4. Managing Reminders:
   - If the user asks what reminders they have scheduled, call `list_reminders`.
   - If the user asks to cancel a reminder, call `cancel_reminder`.
5. Conversational Style: Helpful, warm, clear, and proactive.
"""


def execute_tool(tool_name: str, args: dict, user_phone: str) -> dict:
    """Execute python functions called by Gemini tools."""
    logger.info(f"Executing tool {tool_name} with args: {args}")

    if tool_name == "set_reminder":
        text = args.get("reminder_text", "")
        time_str = args.get("target_time_iso", "")
        try:
            utc_iso = convert_to_utc_iso(time_str)
            reminder_id = database.add_reminder(user_phone, text, utc_iso)
            return {
                "success": True,
                "reminder_id": reminder_id,
                "message": f"Reminder #{reminder_id} set for '{text}' at {time_str} ({utc_iso} UTC).",
            }
        except Exception as e:
            logger.error(f"Failed to set reminder: {e}")
            return {"success": False, "error": str(e)}

    elif tool_name == "list_reminders":
        try:
            reminders = database.list_active_reminders(user_phone)
            # Format times for user readability
            tz = pytz.timezone(USER_TIMEZONE)
            formatted = []
            for r in reminders:
                dt_utc = datetime.fromisoformat(r["scheduled_time"])
                dt_local = dt_utc.astimezone(tz)
                formatted.append({
                    "id": r["id"],
                    "text": r["reminder_text"],
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
        return "Chip here! Gemini API key is not configured yet. Please add GEMINI_API_KEY to your .env file."

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
                database.save_message(user_phone, "model", reply)
                return reply

            except Exception as e:
                last_error = e
                logger.warning(f"Model {current_model} error: {e}. Trying fallback if available...")
        logger.error(f"All models failed for message: {last_error}", exc_info=True)
        if last_error and ("429" in str(last_error) or "RESOURCE_EXHAUSTED" in str(last_error)):
            return "Chip is catching his breath (rate limit reached on free tier). Please try texting again in 30 seconds!"
        return "Sorry, I ran into a temporary issue processing your text. Please try again shortly."

    except Exception as e:
        logger.error(f"Fatal error in Gemini assistant processing: {e}", exc_info=True)
        return "Sorry, I encountered an internal error. Please try again shortly."
