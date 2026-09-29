import os
import re
import logging
import asyncio
import edge_tts

logger = logging.getLogger("chipai.tts")

DEFAULT_VOICE = os.getenv("VOICE_NAME", "en-US-JennyNeural")


def clean_text_for_speech(text: str) -> str:
    """Strip out markdown formatting and special characters that sound awkward in TTS."""
    # Remove markdown bold/italics
    cleaned = re.sub(r"\*+", "", text)
    # Remove markdown links, keep text: [label](url) -> label
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Remove code backticks
    cleaned = cleaned.replace("`", "")
    # Replace em-dashes or en-dashes with clean commas or pauses
    cleaned = cleaned.replace("—", ", ").replace("–", "-")
    # Clean multiple spaces or empty lines
    cleaned = re.sub(r"\n+", ". ", cleaned).strip()
    return cleaned


async def _generate_audio_stream(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice=voice)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data


def text_to_speech(text: str, voice: str = DEFAULT_VOICE) -> bytes | None:
    """Synthesize text into natural neural speech audio bytes."""
    if not text or not text.strip():
        return None

    clean_text = clean_text_for_speech(text)
    if not clean_text:
        return None

    try:
        # If running inside an existing event loop, create a task; otherwise asyncio.run
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _generate_audio_stream(clean_text, voice)).result(timeout=20)
        else:
            return asyncio.run(_generate_audio_stream(clean_text, voice))
    except Exception as e:
        logger.error(f"TTS generation error for voice '{voice}': {e}", exc_info=True)
        return None
