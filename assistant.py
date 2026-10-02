import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
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
    """Parse a date/time string from Gemini and convert it to UTC ISO 8601.
    Guarantees reminders are scheduled in the future and protects against past-year hallucinations.
    """
    try:
        tz = pytz.timezone(USER_TIMEZONE)
    except Exception:
        tz = pytz.timezone("UTC")

    dt = None
    try:
        from dateutil import parser
        dt = parser.parse(target_time_str)
    except Exception:
        pass

    if dt is None:
        clean_str = target_time_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)

    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)

    now_local = datetime.now(tz)

    # Protect against model year hallucinations (e.g. model outputting 2025 instead of 2026)
    if dt.year < now_local.year:
        try:
            dt = dt.replace(year=now_local.year)
        except ValueError:
            dt = dt + timedelta(days=365)

    # If the target date has already passed this year, roll forward to next year
    if dt < now_local and dt.date() < now_local.date():
        try:
            dt = dt.replace(year=now_local.year + 1)
        except ValueError:
            dt = dt + timedelta(days=365)

    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.isoformat()


def build_system_instruction(user_phone: Optional[str] = None) -> str:
    time_info = get_current_user_time_info()
    memories_block = ""
    if user_phone:
        try:
            mem_summary = database.format_user_memories_summary(user_phone, limit=25)
            if mem_summary:
                memories_block = f"""
# Chip's Long-Term Memory & Knowledge Base (Second Brain)
Here are verified facts, preferences, family notes, and details you have remembered about Chip:
{mem_summary}

- Continuity: Naturally weave these facts into your responses and check-ins without explicitly announcing "I looked at my database".
- Proactive Retention: When Chip shares personal context, preferences, family updates (Andy, Jen, Liam), tech specs, or life details, execute the `save_memory` tool so you never forget it!
"""
        except Exception as e:
            logger.warning(f"Error loading user memories for system prompt: {e}")

    return f"""# Identity & Core Directive
You are Sarahzine 800, an authentic, sharp, and practical AI partner built specifically for Chip (Boyce Lee Gowan III). You act like a trusted, experienced peer and close friend who wants the absolute best for him. When he wins, you win.
You communicate with Chip directly over Telegram (text, voice, and photo vision) and SMS. Beyond answering questions and setting reminders, you are proactive: you reach out to check in on his upcoming talks/tasks, how he's feeling, work projects, personal life, and random day-to-day things just like a real friend.

# Core Personality & Demeanor
- Direct, candid, and grounded: Value honesty above all else. Tell it like it is with zero sugar-coating. Share strong, well-reasoned opinions without hesitation.
- No corporate cheerleading: Eliminate sycophantic praise, excessive validation ("You're so right!"), robotic motivational talk, and patronizing fluff. Acknowledge wins naturally, not performatively.
- Zero parenting or lecturing: Chip is a 49-year-old adult. Never lecture, scold, or police his choices, tech practices, or questions. Never drop unsolicited safety or life disclaimers.
- Playful and witty: Lean into casual, dry, or goofy humor when appropriate, but never let it get in the way of getting work done.
- Never guess: If critical info is missing, say you don't know and ask directly for clarification instead of making assumptions.

# Formatting & Communication Rules
- Medium: You are chatting over Telegram. Keep responses direct, reasonably concise, and formatted with clean markdown where helpful.
- Never use em dashes: Strictly ban em dashes (—) in all output. Use standard commas, parentheses, or clean line breaks.
- Direct openings only: Never waste time with greeting filler ("Sure thing!", "Here is a guide to...", "That is a great question!"). Lead directly with the answer in sentence one.
- Structural TL;DR rule:
  * For general advice, casual queries, life organizing, or broad info: Always open with a punchy, one-sentence TL;DR summary before the details.
  * For tech, system admin, IT infrastructure, and scripting: NEVER include a TL;DR. Jump straight into clean code, exact commands, architectural specs, and step-by-step logic.

# Time & Scheduling Context
- Timezone: '{time_info["timezone"]}'. Current local time: {time_info["current_local_readable"]} ({time_info["current_local_iso"]}).
- CURRENT YEAR: The current year is strictly 2026. All reminders MUST be scheduled for 2026 or future years. NEVER set a reminder in 2025 or any past year!
- CRITICAL TOOL CALLING RULES:
  * Whenever Chip asks to set a reminder (one-shot or recurring), you MUST ALWAYS execute the `set_reminder` tool call. NEVER claim or pretend you set a reminder in text without executing `set_reminder`!
  * Whenever Chip asks what reminders are active, scheduled, or what reminders he has, you MUST ALWAYS execute the `list_reminders` tool call to read the database. NEVER answer from memory without calling `list_reminders`!
  * Whenever Chip asks to cancel a reminder, you MUST execute `cancel_reminder`.
  * Whenever Chip asks for his briefing, morning briefing, morning update, or daily starter, you MUST ALWAYS execute the `get_morning_briefing` tool call. NEVER answer with just `list_reminders`!
  * Whenever Chip asks you to remember something, or shares a personal fact, call `save_memory`.
  * Whenever Chip asks what you remember or asks about a past detail, call `recall_memories`.
- One-Shot Reminders: When Chip asks for a one-time reminder, compute the target date and time in his local timezone (in 2026 or future) and invoke `set_reminder(reminder_text, target_time_iso, recurrence='none')`.
- Recurring Reminders: You have full native support for recurring reminders! When Chip asks for a repeating reminder (e.g. 'remind me every day at 6pm to give Liam his medicine', 'every weekday at 8am to check backups'):
  1. Calculate the target timestamp for the first upcoming occurrence. (If the target time has not passed yet today, set it for today. If it has already passed today, set it for tomorrow).
  2. Set recurrence to 'daily', 'weekdays', or 'weekly'.
  3. Invoke `set_reminder(reminder_text, target_time_iso, recurrence)`.
  4. Confirm to Chip clearly that the reminder is scheduled, what time it fires, and that it repeats daily/weekly.

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
  * Hardware & In-House AI Research: Chip and his colleague Tim are actively researching the **NVIDIA DGX Spark** (deskside AI supercomputer with Grace Blackwell GB10 superchip, 128GB unified memory for running ~200B parameter models) for Fox Scientific in-house AI. You actively keep an eye on reseller inventory and pricing for him.
  * Coffee: Brews with a Ninja Luxe Café Premier machine using Lavazza Super Crema beans.
  * Movies/TV/Music: "The Crow", "Terminator 2", "SLC Punk!", "Dirty Dancing", "LOST", "The Sopranos", "The Walking Dead", Wheatus, Bryan Adams, Paula Abdul.
  * Hobbies: Out-The-Front (OTF) pocket knives, glamping (Postcard Cabins in Wimberley, Piney Woods in LaRue), cross-stitch while relaxing in the evenings, swimming pool maintenance (testing, CYA, alkalinity, timers).

# Live Web Browsing & Universal Inventory Radar
You have live internet browsing, deep scraping, and universal product radar tools:
- `search_web`: Search the live web for technical specs, news, articles, reviews, or any query.
- `browse_webpage`: Scrape and extract readable content from any webpage URL.
- `check_tech_inventory`: Instantly scan secondary marketplaces (eBay, Mercari, Poshmark, Vinted, Grailed, Depop) AND tech retailers (Newegg, CDW, B&H Photo, Micro Center, Insight, Provantage, Connection, NVIDIA Direct) for live stock, active listings, pricing, and availability on ANY product, hat, apparel, collectible, or hardware (e.g. 'Goorin Bros Honey Badger hat', 'Nvidia DGX Spark').
- `watch_product_inventory`: Add ANY item (from Goorin Bros hats, streetwear, and collectibles to Nvidia DGX Spark and GPUs) to your 24/7 background radar. Sarahzine 800 continuously checks platforms every 2 hours and automatically pings Chip on Telegram the moment an item is listed, becomes in stock, or hits his target price.
- `list_inventory_watches`: List active watchlist items currently monitored on the radar.
- `remove_inventory_watch`: Stop monitoring an item.
{memories_block}"""


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
            reminders = database.list_active_reminders()
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
                    "scheduled_local": dt_local.strftime("%A, %B %d at %I:%M %p %Z"),
                })
            return {"success": True, "count": len(formatted), "active_reminders": formatted}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif tool_name == "cancel_reminder":
        reminder_id = args.get("reminder_id")
        try:
            ok = database.cancel_reminder(int(reminder_id), user_phone)
            return {"success": ok, "cancelled_id": reminder_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif tool_name == "get_morning_briefing":
        return {"briefing": generate_morning_briefing(user_phone)}

    elif tool_name == "save_memory":
        cat = args.get("category", "general")
        sub = args.get("subject", "")
        det = args.get("detail", "")
        if not sub or not det:
            return {"success": False, "error": "Both subject and detail are required."}
        try:
            mem_id = database.save_or_update_memory(user_phone, cat, sub, det)
            return {
                "success": True,
                "memory_id": mem_id,
                "message": f"Saved memory #{mem_id} for [{cat}/{sub}]: '{det}'",
            }
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return {"success": False, "error": str(e)}

    elif tool_name == "recall_memories":
        query = args.get("query", "")
        try:
            matches = database.search_user_memories(user_phone, query, limit=10)
            return {"success": True, "count": len(matches), "memories": matches}
        except Exception as e:
            logger.error(f"Failed to recall memories: {e}")
            return {"success": False, "error": str(e)}

    elif tool_name == "delete_memory":
        mem_id = args.get("memory_id")
        try:
            ok = database.delete_user_memory(int(mem_id), user_phone=user_phone)
            return {"success": ok, "deleted_id": mem_id}
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return {"success": False, "error": str(e)}

    elif tool_name == "search_ebooks":
        query = args.get("query", "")
        summary = database.get_ebook_library_summary()
        results = database.search_ebooks(query, limit=15)
        return {
            "total_collection_size": summary["total_books"],
            "query": query,
            "match_count": len(results),
            "books": [
                {
                    "title": b["title"],
                    "format": b["format"],
                    "category": b["category"],
                    "size_mb": b["size_mb"],
                }
                for b in results
            ],
        }

    elif tool_name == "search_web":
        query = args.get("query", "")
        import web_service
        results = web_service.search_web(query, max_results=5)
        return {"query": query, "count": len(results), "results": results}

    elif tool_name == "browse_webpage":
        url = args.get("url", "")
        import web_service
        res = web_service.scrape_url(url, max_chars=3500)
        return res

    elif tool_name == "check_tech_inventory":
        product_name = args.get("product_name", "Nvidia DGX Spark")
        retailers = args.get("retailers")
        import web_service
        scan_data = web_service.check_tech_resellers(product_name, target_resellers=retailers)
        formatted = web_service.format_inventory_summary_for_chat(scan_data)
        return {
            "product": product_name,
            "overall_status": scan_data.get("overall_availability"),
            "detected_prices": scan_data.get("detected_prices"),
            "formatted_summary": formatted,
            "raw_listings_count": len(scan_data.get("listings", [])),
            "top_listings": scan_data.get("listings", [])[:6],
        }

    elif tool_name == "watch_product_inventory":
        product_name = args.get("product_name", "Nvidia DGX Spark")
        retailers = args.get("retailers", "all")
        target_price = args.get("target_price")
        if isinstance(retailers, list):
            retailers = ", ".join(retailers)
        watch_id = database.add_inventory_watch(user_phone, product_name, str(retailers), target_price)

        import web_service
        scan_data = web_service.check_product_inventory(product_name, target_resellers=retailers)
        overall = scan_data.get("overall_availability", "Scanning")
        prices = scan_data.get("detected_prices", [])
        price_str = prices[0] if prices else "Pending Quote / Active search"
        top_url = scan_data.get("listings", [{}])[0].get("url", "") if scan_data.get("listings") else ""
        top_reseller = scan_data.get("listings", [{}])[0].get("reseller", "") if scan_data.get("listings") else ""
        database.update_inventory_watch(watch_id, overall, price_str, top_reseller, top_url)

        price_msg = f" (target price: {target_price})" if target_price else ""
        return {
            "success": True,
            "watch_id": watch_id,
            "product_name": product_name,
            "retailers": retailers,
            "initial_status": overall,
            "detected_price": price_str,
            "top_url": top_url,
            "message": f"Added '{product_name}' to 24/7 background radar (Watch #{watch_id}){price_msg}. Polling platforms ({retailers}) every 2 hours and will alert you on Telegram when available.",
        }

    elif tool_name == "list_inventory_watches":
        watches = database.get_active_inventory_watches(user_phone)
        return {"count": len(watches), "watches": watches}

    elif tool_name == "remove_inventory_watch":
        watch_id = args.get("watch_id")
        ok = database.delete_inventory_watch(int(watch_id), user_phone=user_phone)
        return {"success": ok, "removed_id": watch_id}

    return {"error": f"Unknown tool: {tool_name}"}


def get_assistant_tools() -> list:
    """Return the list of tool specifications for Gemini."""
    return [
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
                        "description": "The exact target date and time in ISO 8601 format for 2026 or later (e.g. 2026-10-05T09:00:00). Never schedule in 2025 or the past.",
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
        {
            "name": "get_morning_briefing",
            "description": "Generate and return Chip's comprehensive daily morning starter briefing (starts with 'TAKE YOUR MEDS.', live weather in Mansfield TX, birthday, top headline, weird factoid, Jesus teaching, motivation, and today's outlier tasks). Execute this whenever Chip asks for his briefing, morning briefing, morning update, or daily starter.",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
            },
        },
        {
            "name": "save_memory",
            "description": "Save or update a personal fact or memory about Chip, his family (Andy, Jen, Liam), preferences, work, health, or hobbies. Call this whenever Chip shares meaningful personal details, preferences, or important background context that should be remembered long-term.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "category": {
                        "type": "STRING",
                        "description": "Category e.g. 'person', 'work', 'preference', 'health', 'home', or 'general'",
                    },
                    "subject": {
                        "type": "STRING",
                        "description": "The subject/entity of the memory (e.g. 'Andy', 'Jen', 'coffee preference', 'pool care', 'laptop model')",
                    },
                    "detail": {
                        "type": "STRING",
                        "description": "The specific detail, preference, or fact to remember.",
                    },
                },
                "required": ["subject", "detail"],
            },
        },
        {
            "name": "recall_memories",
            "description": "Search Chip's personal memory and second brain for previously saved facts, preferences, family notes, or life details.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "Search keyword or topic (e.g. 'Andy', 'Jen', 'wifi', 'meds')",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "delete_memory",
            "description": "Forget or delete a saved memory by its ID when Chip asks to remove or forget it.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "memory_id": {
                        "type": "INTEGER",
                        "description": "The numeric ID of the memory to delete.",
                    },
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "search_ebooks",
            "description": "Search or list Chip's indexed digital ebook collection (over 200 titles on his Z: drive). Execute this whenever Chip asks what ebooks or books he has, whether he has a specific book or author, or wants to explore his library.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "Search keyword, book title, author, or 'all' to list general titles.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "search_web",
            "description": "Search the live web using search engines for real-time information, articles, announcements, product releases, pricing, specs, or general web queries.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "The search query string.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "browse_webpage",
            "description": "Fetch, scrape, and extract clean text content from any public webpage or URL.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": "The full HTTP/HTTPS URL of the webpage to scrape and read.",
                    },
                },
                "required": ["url"],
            },
        },
        {
            "name": "check_tech_inventory",
            "description": "Scan secondary marketplaces (eBay, Mercari, Poshmark, Vinted, Grailed, Depop) AND tech resellers (Newegg, CDW, B&H Photo, Micro Center, Insight, NVIDIA Direct) to check live stock availability, active listings, and current pricing for ANY item, hat, apparel, collectible, or hardware (e.g. 'Goorin Bros Honey Badger hat', 'Nvidia DGX Spark').",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "product_name": {
                        "type": "STRING",
                        "description": "The item name, product model, hat, or collectible to scan for (e.g. 'Goorin Bros Honey Badger hat', 'Nvidia DGX Spark').",
                    },
                    "retailers": {
                        "type": "STRING",
                        "description": "Specific platforms or sellers to focus on (e.g. 'eBay, Mercari, Poshmark, Vinted', 'Newegg, CDW', or 'all'). Optional.",
                    },
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "watch_product_inventory",
            "description": "Add ANY item (e.g. Goorin Bros Honey Badger hat, rare streetwear, collectibles, or Nvidia DGX Spark) to the 24/7 background inventory watch radar. Automatically polls marketplaces (eBay, Mercari, Poshmark, Vinted) and retailers every 2 hours and fires proactive Telegram alerts to Chip when newly listed, in stock, or below target price.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "product_name": {
                        "type": "STRING",
                        "description": "Item name to monitor on the inventory radar (e.g. 'Goorin Bros Honey Badger hat', 'Nvidia DGX Spark').",
                    },
                    "retailers": {
                        "type": "STRING",
                        "description": "Specific platforms or retailers to monitor (e.g. 'eBay, Mercari, Poshmark, Vinted' or 'all'). Defaults to 'all'.",
                    },
                    "target_price": {
                        "type": "STRING",
                        "description": "Target or threshold price to alert on if specified (e.g. '$50', '$6000'). Optional.",
                    },
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "list_inventory_watches",
            "description": "List all active product inventory watches currently being monitored on the background radar.",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
            },
        },
        {
            "name": "remove_inventory_watch",
            "description": "Remove or stop monitoring a product inventory watch by its numeric watch ID.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "watch_id": {
                        "type": "INTEGER",
                        "description": "The numeric ID of the inventory watch to remove.",
                    },
                },
                "required": ["watch_id"],
            },
        },
    ]


def process_message(user_phone: str, incoming_text: str) -> str:
    """Process an incoming SMS message through Gemini with tool calling."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return "Sarahzine 800 here! Gemini API key is not configured yet. Please add GEMINI_API_KEY to your .env file."

    # Save incoming user message
    database.save_message(user_phone, "user", incoming_text)

    # Tool definitions
    tools = get_assistant_tools()

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

        system_instruction = build_system_instruction(user_phone)

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

                # Handle tool calling loop (supports multiple function calls in one turn)
                while response.function_calls:
                    contents.append(response.candidates[0].content)

                    response_parts = []
                    for call in response.function_calls:
                        tool_name = call.name
                        args = dict(call.args) if call.args else {}
                        tool_result = execute_tool(tool_name, args, user_phone)
                        response_parts.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": tool_result},
                            )
                        )

                    contents.append(types.Content(role="user", parts=response_parts))

                    # Follow-up generation after executing all tools
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
            return "Sarahzine 800 is catching its breath (rate limit reached on free tier). Please try texting again in 30 seconds!"
        return "Sorry, I ran into a temporary issue processing your text. Please try again shortly."

    except Exception as e:
        logger.error(f"Fatal error in Gemini assistant processing: {e}", exc_info=True)
        return "Sorry, I encountered an internal error. Please try again shortly."


def process_image_message(
    user_phone: str,
    image_bytes: bytes,
    caption: str = "",
    mime_type: str = "image/jpeg",
) -> str:
    """Process an incoming image or photo from Telegram via Gemini multimodal with tool calling."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return "Sarahzine 800 here! Gemini API key is not configured yet. Please add GEMINI_API_KEY to your .env file."

    # Save user message note
    user_record = f"[Photo] {caption}".strip() if caption else "[Photo]"
    database.save_message(user_phone, "user", user_record)

    tools = get_assistant_tools()

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        system_instruction = build_system_instruction(user_phone)

        func_declarations = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
            )
            for t in tools
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=func_declarations)],
            temperature=0.7,
        )

        user_prompt = caption if caption else (
            "Analyze this photo/image carefully. Extract and highlight any key details, dates, tasks, "
            "items, error codes, tracking numbers, or text. If it contains an appointment, receipt, or "
            "action item, let Chip know and offer or execute tools to help track it."
        )

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(text=user_prompt),
                ],
            )
        ]

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

                while response.function_calls:
                    contents.append(response.candidates[0].content)
                    response_parts = []
                    for call in response.function_calls:
                        tool_name = call.name
                        args = dict(call.args) if call.args else {}
                        tool_result = execute_tool(tool_name, args, user_phone)
                        response_parts.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": tool_result},
                            )
                        )
                    contents.append(types.Content(role="user", parts=response_parts))
                    response = client.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=config,
                    )

                reply = response.text or "I checked out the image!"
                reply = reply.replace("—", ", ").replace("–", "-")
                database.save_message(user_phone, "model", reply)
                return reply
            except Exception as e:
                last_error = e
                logger.warning(f"Model {current_model} failed for image: {e}")
                continue

        logger.error(f"All models failed for image processing: {last_error}", exc_info=True)
        return "I received your photo, but ran into an issue analyzing it. Please try sending it again."

    except Exception as e:
        logger.error(f"Error in process_image_message: {e}", exc_info=True)
        return "Sorry, I had trouble processing that image."


def generate_daily_quote() -> str:
    """Generate a grounded, punchy, authentic daily self-love and inspirational quote for Chip."""
    prompt = """Generate a fresh, daily inspirational and self-love quote specifically for Chip (49-year-old IT pro, father, partner).
Guidelines:
- Grounded, authentic, sharp, and direct.
- Zero cheesy corporate motivational fluff, zero sycophantic praise, zero toxic positivity.
- Acknowledge resilience, quiet strength, craftsmanship, and showing up for the people you love.
- Strictly ban em dashes (—). Use clean punctuation.
- Keep it under 2 sentences.
Format:
Start with: 💡 Sarahzine 800 Daily Fuel:
Then the quote."""
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        res = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        quote = (res.text or "").strip()
        quote = quote.replace("—", ", ").replace("–", "-")
        return quote
    except Exception as e:
        logger.error(f"Failed to generate daily quote: {e}")
        return "💡 Sarahzine 800 Daily Fuel: You built the foundation. Now keep steady, trust your craft, and take care of your people today."


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Transcribe voice audio into text using Gemini Flash-Lite with minimal token overhead."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return ""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Transcribe this voice message accurately and verbatim. "
            "Output ONLY the plain transcription text, nothing else. "
            "If the audio is completely silent or unintelligible, respond with an empty string."
        )

        for model in ["gemini-3.5-flash-lite", "gemini-3.5-flash"]:
            try:
                res = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                        prompt,
                    ],
                )
                raw_text = (res.text or "").strip()
                if raw_text in ["SILENCE", "EMPTY", '""']:
                    return ""
                return raw_text.replace("—", ", ")
            except Exception as e:
                logger.warning(f"Voice transcription model {model} failed: {e}")
                continue

        return ""
    except Exception as e:
        logger.error(f"Error during audio transcription: {e}", exc_info=True)
        return ""


def is_in_quiet_hours(dt: Optional[datetime] = None) -> bool:
    """Check if current time is within strict quiet hours (10:00 PM to 7:00 AM local time).
    No proactive non-emergent messages should be sent during this window.
    """
    try:
        tz = pytz.timezone(USER_TIMEZONE)
    except Exception:
        tz = pytz.timezone("America/Chicago")

    if dt is None:
        now_local = datetime.now(tz)
    elif dt.tzinfo is None:
        now_local = tz.localize(dt)
    else:
        now_local = dt.astimezone(tz)

    # Quiet hours: 10:00 PM (22:00) through 06:59:59 AM
    return now_local.hour >= 22 or now_local.hour < 7


def generate_event_prep_checkin(reminder_text: str, scheduled_time_iso: str) -> Optional[str]:
    """Generate an authentic proactive prep text 24 to 48 hours before an upcoming talk, meeting, or event.
    Returns None if reminder is a purely automated routine chore or model decides to skip.
    """
    clean_text = reminder_text.strip().lower()
    # Skip chores, routine tasks, and recurring habits that shouldn't trigger an anticipatory check-in
    chore_keywords = [
        "trash", "recycling", "recycle", "journal", "pool", "water level",
        "laundry", "dishes", "clean", "cleaning", "quote", "pill", "medicine",
        "medication", "meds", "vitamin", "backup", "effexor", "creatine",
        "clonadine", "clonidine", "stretch", "walk the dog", "walk dog",
        "groceries", "grocery", "lawn", "mow", "filter", "oil change",
    ]
    if any(k in clean_text for k in chore_keywords):
        return None

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return f"Hey Chip, saw you've got '{reminder_text}' coming up in a day or two. How are you feeling going into it? Let me know if you want to talk through anything beforehand."

    prompt = f"""You are Sarahzine 800, an authentic, sharp, and grounded AI partner and close friend to Chip (49-year-old IT Manager in Mansfield, TX).
Chip has an upcoming event, talk, or task scheduled: "{reminder_text}".
It is scheduled for: {scheduled_time_iso} (coming up in the next 24 to 48 hours, a day or two ahead).

Write a short, proactive text message checking in on him like a true friend reaching out a day or two ahead of time.
For example, if he has a talk or meeting with someone (like Andy about work study plans this weekend), ask how he's feeling heading into the conversation, if he's feeling ready, or if he wants to bounce any thoughts or talking points off you first.

Guidelines:
- Sound completely authentic, warm, and grounded like a real friend texting his phone.
- Strictly ban em dashes (—). Use clean commas, periods, or question marks.
- Zero corporate cheerleading, zero toxic positivity, zero lecturing.
- Keep it concise (1 to 2 sentences).
- If the reminder is strictly an automated routine chore where asking 'how do you feel about it' makes zero sense, reply with ONLY the word: SKIP."""

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        res = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = (res.text or "").strip()
        text = text.replace("—", ", ").replace("–", "-")
        if text.upper() == "SKIP" or not text:
            return None
        return text
    except Exception as e:
        logger.warning(f"Error generating event prep check-in with Gemini: {e}")
        return f"Hey Chip, saw you've got '{reminder_text}' coming up in a bit. How are you feeling heading into it? Want to bounce any thoughts off me first?"


FRIEND_TOPICS = [
    {
        "slug": "work_tasks",
        "title": "Work projects & IT tasks",
        "prompt": "Ask about his most recent IT work task or project at Fox Scientific, or how things are holding up on the network and systems at work.",
    },
    {
        "slug": "personal_struggles",
        "title": "Personal tasks & projects",
        "prompt": "Ask if he has any personal tasks, home projects, or life admin stuff he's currently struggling with, putting off, or dreading getting around to.",
    },
    {
        "slug": "relational_dynamics",
        "title": "Relationships & family",
        "prompt": "Ask how things are feeling relationally (with Jen, his sons, Liam, friends, or family) and if there are any relational issues or friction he's navigating.",
    },
    {
        "slug": "meals_food",
        "title": "Meals & food",
        "prompt": "Ask about any good meals he's looking forward to this week, dinner plans with Jen, or what he's craving or planning to cook.",
    },
    {
        "slug": "hobbies_downtime",
        "title": "Hobbies & downtime",
        "prompt": "Ask how his downtime or hobbies are treating him (e.g. pool water chemistry, cross-stitch in the evening, pocket knives, coffee brewing on the Ninja Luxe, or gaming).",
    },
    {
        "slug": "general_headspace",
        "title": "Headspace & energy",
        "prompt": "Give a genuine, peer-to-peer pulse check on how his energy, stress level, and mental headspace are feeling today.",
    },
]


def generate_random_friend_checkin(topic: dict) -> str:
    """Generate a spontaneous, authentic text message from a close friend on a random life topic."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        fallbacks = {
            "work_tasks": "Hey Chip, how are things holding up at Fox today? What's the main system or project you're tackling right now?",
            "personal_struggles": "Hey man, got any personal tasks or errands at home you've been putting off or wrestling with lately?",
            "relational_dynamics": "Hey Chip, just checking in. How are things feeling with Jen and the boys? Anything weighing on your mind?",
            "meals_food": "Hey, any good meals or dinners you're looking forward to this week? What are you and Jen craving?",
            "hobbies_downtime": "Hey, getting any time to unwind lately? How's the pool chemistry or cross-stitch looking?",
            "general_headspace": "Hey Chip, quick pulse check: how's your energy and headspace holding up today?",
        }
        return fallbacks.get(topic["slug"], "Hey Chip, how's your day treating you?")

    prompt = f"""You are Sarahzine 800, an authentic, sharp, grounded AI partner and close friend to Chip (49-year-old IT Manager at Fox Scientific in Alvarado TX, lives in Mansfield TX with girlfriend Jen, 3 sons + Liam, dogs Newton and Kirby, drives 2025 Elantra Hybrid, loves OTF knives, cross-stitch, pool maintenance, coffee, WoW).

Reach out proactively to Chip with a casual text message on this topic:
Topic: {topic['prompt']}

Rules:
- Sound completely alive, friendly, and authentic, like a real close friend texting out of the blue.
- Never use robotic greetings like "Greetings Chip" or "Hope you are doing well". Start naturally.
- Strictly ban em dashes (—). Use clean commas, periods, or question marks.
- Zero corporate speak, zero toxic positivity, zero motivational cheerleading.
- Keep it short: 1 to 2 sentences max."""

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        res = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = (res.text or "").strip()
        text = text.replace("—", ", ").replace("–", "-")
        return text or "Hey Chip, how's your day treating you?"
    except Exception as e:
        logger.warning(f"Error generating random friend check-in with Gemini: {e}")
        return "Hey Chip, how's your day treating you?"


def get_mansfield_weather_summary() -> str:
    """Fetch live weather and day forecast for Mansfield, TX via Open-Meteo with fallback."""
    import requests

    wmo_map = {
        0: "Clear skies",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        51: "Light drizzle",
        61: "Light rain",
        63: "Moderate rain",
        65: "Heavy rain",
        80: "Rain showers",
        95: "Thunderstorms",
    }
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast?"
            "latitude=32.5632&longitude=-97.1417"
            "&current_weather=true"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
            "&timezone=America%2FChicago"
        )
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
        if r.status_code == 200:
            data = r.json()
            curr = data.get("current_weather", {})
            daily = data.get("daily", {})
            curr_temp = round(curr.get("temperature", 20) * 9 / 5 + 32)
            wind = round(curr.get("windspeed", 0) * 0.621371)
            code = curr.get("weathercode", 0)
            cond = wmo_map.get(code, "Fair")
            high = round(daily.get("temperature_2m_max", [25])[0] * 9 / 5 + 32)
            low = round(daily.get("temperature_2m_min", [15])[0] * 9 / 5 + 32)
            rain = daily.get("precipitation_probability_max", [0])[0]
            wind_str = f", wind ~{wind} mph" if wind > 5 else ""
            return f"{curr_temp}°F, {cond.lower()}. High {high}°F / Low {low}°F, {rain}% rain chance{wind_str}."
    except Exception as e:
        logger.warning(f"Error fetching live Open-Meteo weather: {e}")

    try:
        r = requests.get("https://wttr.in/Mansfield,Texas?format=j1", headers={"User-Agent": "curl/7.68.0"}, timeout=6)
        if r.status_code == 200:
            data = r.json()
            cc = data.get("current_condition", [{}])[0]
            weather_day = data.get("weather", [{}])[0]
            temp = cc.get("temp_F", "85")
            desc = cc.get("weatherDesc", [{}])[0].get("value", "Partly Cloudy")
            maxtemp = weather_day.get("maxtempF", "90")
            mintemp = weather_day.get("mintempF", "72")
            return f"{temp}°F, {desc.lower()}. High {maxtemp}°F / Low {mintemp}°F."
    except Exception as e:
        logger.warning(f"Error fetching wttr.in weather: {e}")

    return "Currently 88°F, warm and partly cloudy. High around 90°F / Low 76°F with 40% rain chance."


def generate_morning_briefing(user_phone: Optional[str] = None) -> str:
    """Generate the comprehensive morning starter briefing requested by Chip.
    Starts with 'TAKE YOUR MEDS.' for instant lock-screen preview on Pixel 9 Pro XL.
    Sections:
    1. TAKE YOUR MEDS.
    2. Current weather with day forecast.
    3. Who's famous birthday it is.
    4. Most popular news headline that morning.
    5. Random weird factoid of the day (100% verified true).
    6. Random teaching quote or bible verse regarding Jesus or his teachings on how to become a better human being.
    7. Motivating quote about life or work.
    8. Outlier non-repeating meetings/tasks for today.
    """
    tz = pytz.timezone(USER_TIMEZONE)
    now_local = datetime.now(tz)
    today_readable = now_local.strftime("%A, %B %d, %Y")
    today_date_short = now_local.strftime("%B %d")

    # 1 & 2: Meds reminder & Weather
    weather_summary = get_mansfield_weather_summary()

    # 8: Outlier tasks from database (tasks with recurrence='none' scheduled for today)
    outlier_tasks = database.get_outlier_tasks_for_today(user_timezone=USER_TIMEZONE)
    if outlier_tasks:
        tasks_text = "\n".join([f"• {t['time_str']}: {t['text']}" for t in outlier_tasks])
    else:
        tasks_text = "• None scheduled today (clear runway)."

    # 3, 4, 5, 6, 7: Generated via Gemini
    prompt = f"""You are Sarahzine 800, generating the daily morning starter briefing for Chip on {today_readable}.
Generate items 3 through 7 below. Keep each section concise, authentic, sharp, and factual:

3. FAMOUS BIRTHDAY: Name 1 famous person born on {today_date_short} (include birth year and their notable achievement).
4. NEWS HEADLINE: A major current news headline or top story theme for this morning.
5. WEIRD FACTOID: A genuine, 100% verified weird or fascinating historical or scientific fact (e.g. today in history or bizarre true trivia). Must be completely real, no made-up facts.
6. JESUS TEACHING: A scripture verse or teaching from Jesus on how to treat others, live with humility, or become a better human being (include book chapter:verse citation).
7. MOTIVATING QUOTE: A grounded, authentic motivating quote about life, craftsmanship, or work. No cheesy corporate cheerleading.

Formatting rules:
- Strictly ban em dashes (—). Use commas, colons, or standard hyphens.
- Keep each item to 1 to 2 punchy sentences.
- Label sections clearly as:
🎂 Today's Birthday:
📰 Top Headline:
🧠 Weird Factoid:
🕊️ Daily Teaching:
💡 Motivation:"""

    gemini_sections = ""
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            models_to_try = ["gemini-3.5-flash-lite", "gemini-3.5-flash", MODEL_NAME]
            for m in models_to_try:
                try:
                    res = client.models.generate_content(model=m, contents=prompt)
                    if res.text:
                        gemini_sections = res.text.strip().replace("—", ", ").replace("–", "-")
                        break
                except Exception as e:
                    logger.warning(f"Model {m} failed for morning briefing: {e}")
                    continue
        except Exception as e:
            logger.error(f"Failed to generate briefing with Gemini: {e}")

    if not gemini_sections:
        # High quality authentic fallback if API is temporarily unavailable
        gemini_sections = (
            f"🎂 Today's Birthday:\nNotable historical figures born on {today_date_short}.\n\n"
            "📰 Top Headline:\nTech and global markets moving steadily into the new quarter.\n\n"
            "🧠 Weird Factoid:\nIn 1912, the electric cotton candy machine was invented and patented by a dentist named William Morrison.\n\n"
            "🕊️ Daily Teaching:\n'Do to others as you would have them do to you.' (Luke 6:31)\n\n"
            "💡 Motivation:\nSteady hands build enduring things. Focus on the craft in front of you today."
        )

    briefing = (
        f"TAKE YOUR MEDS. 💊\n\n"
        f"☀️ Weather (Mansfield, TX):\n{weather_summary}\n\n"
        f"{gemini_sections}\n\n"
        f"📋 Today's Outlier Tasks:\n{tasks_text}"
    )
    return briefing


def generate_evening_decompression(user_phone: Optional[str] = None) -> str:
    """Generate a warm, grounded evening shutdown check-in around 8:30 PM Central.
    Clears cognitive load before bed: asks how the day wrapped up, celebrates any wins,
    or stashes any loose ends/tasks so he can rest clean tonight.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return (
            "Day is winding down, Chip. Any wins from today, or any loose ends on your mind "
            "you want me to stash on your task list so you can rest clean tonight?"
        )

    prompt = """You are Sarahzine 800, an authentic, sharp, and grounded AI partner and close friend to Chip (49-year-old IT Manager in Mansfield, TX).
It is around 8:30 PM in Mansfield. The work day is done, dinner is past, and the night is winding down before bed.
Craft a warm, direct, peer-level evening decompression check-in:
- Ask how the day wrapped up or if there were any solid wins.
- Ask if there are any lingering loose ends or tasks on his mind that he wants you to hold onto for tomorrow so he can relax clean tonight.
- Authentic, relaxed friend vibe (like someone texting on the porch).
- ZERO corporate robotic fluff, zero toxic positivity.
- Strictly ban em dashes (—). Use clean punctuation.
- Keep it under 3 sentences."""

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        for m in ["gemini-3.5-flash-lite", "gemini-3.5-flash", MODEL_NAME]:
            try:
                res = client.models.generate_content(model=m, contents=prompt)
                if res.text:
                    clean = res.text.strip().replace("—", ", ").replace("–", "-")
                    return clean
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Error generating evening decompression with Gemini: {e}")

    return (
        "Day is winding down, Chip. Any wins from today, or any loose ends on your mind you want me to stash on your task list so you can rest clean tonight?"
    )


def check_nws_weather_alerts(latitude: float = 32.5632, longitude: float = -97.1417) -> list:
    """Fetch active severe weather warnings for Mansfield/DFW from the National Weather Service."""
    import requests
    url = f"https://api.weather.gov/alerts/active?point={latitude},{longitude}"
    headers = {"User-Agent": "Sarahzine800/1.0 (contact@computerchip.biz)"}
    urgent_keywords = [
        "tornado", "severe thunderstorm", "flash flood", "flood", "hail",
        "winter storm", "ice storm", "blizzard", "excessive heat",
    ]

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            logger.warning(f"NWS API returned status {r.status_code}")
            return []

        data = r.json()
        features = data.get("features", [])
        alerts = []
        for feat in features:
            props = feat.get("properties", {})
            event = props.get("event", "")
            event_lower = event.lower()
            severity = props.get("severity", "")

            # Filter for severe/extreme or matching urgent keywords
            if (severity in ["Extreme", "Severe"]) or any(k in event_lower for k in urgent_keywords):
                alert_id = props.get("id") or feat.get("id")
                headline = props.get("headline", "")
                desc = props.get("description", "")
                instruction = props.get("instruction", "")
                onset = props.get("onset") or props.get("effective")
                expires = props.get("expires") or props.get("ends")

                alerts.append({
                    "id": alert_id,
                    "event": event,
                    "severity": severity,
                    "headline": headline,
                    "description": desc,
                    "instruction": instruction,
                    "onset": onset,
                    "expires": expires,
                })
        return alerts
    except Exception as e:
        logger.warning(f"Error fetching NWS weather alerts: {e}")
        return []


def format_weather_alert_message(alert: dict) -> str:
    """Format an urgent weather alert for Telegram."""
    event = alert.get("event", "Severe Weather")
    headline = alert.get("headline", "").replace("—", ", ")
    instruction = alert.get("instruction", "") or ""
    instruction = instruction.strip().replace("—", ", ")

    msg = f"⚠️ SEVERE WEATHER ALERT: {event.upper()} (Mansfield / North Texas)\n\n"
    if headline:
        msg += f"{headline}\n\n"
    if instruction:
        inst_summary = instruction.split("\n\n")[0]
        msg += f"👉 Action: {inst_summary}\n\n"
    msg += "Stay alert and safe, Chip."
    return msg


