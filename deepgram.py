#!/usr/bin/env python3
"""
Deepgram Voice Agent - Terminal Test Script
Requirements: uv pip install websockets pyaudio
"""

import asyncio
import json
import pyaudio
import websockets
import threading
import sys

# ===================== CONFIG =====================
DEEPGRAM_API_KEY = "eeeed57c4cabf09f8fb6d80b0cf7250e765b4032"  # <-- paste your key here
WS_URL = "wss://agent.deepgram.com/v1/agent/converse"

SETTINGS = {
    "type": "Settings",
    "audio": {
        "input": {
            "encoding": "linear16",
            "sample_rate": 48000
        },
        "output": {
            "encoding": "linear16",
            "sample_rate": 24000,
            "container": "none"
        }
    },
    "agent": {
        "language": "en",
        "speak": {
            "provider": {
                "type": "deepgram",
                "model": "aura-2-thalia-en"
            }
        },
        "listen": {
            "provider": {
                "type": "deepgram",
                "version": "v2",
                "model": "nova-2"
            }
        },
        "think": {
            "provider": {
                "type": "open_ai",
                "model": "gpt-4o-mini"
            },
            "prompt": "You are a helpful voice assistant. Keep responses concise."
        }
    }
}

# ===================== AUDIO CONFIG =====================
INPUT_SAMPLE_RATE  = 48000
OUTPUT_SAMPLE_RATE = 24000
CHUNK              = 1024
FORMAT             = pyaudio.paInt16
CHANNELS           = 1

audio_output_queue = asyncio.Queue()
stop_event = threading.Event()


def mic_stream(ws_loop, ws):
    """Read mic in a thread and send audio to websocket."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    print("[MIC] Listening... speak now. Press Ctrl+C to quit.\n")
    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            asyncio.run_coroutine_threadsafe(ws.send(data), ws_loop)
    except Exception as e:
        print(f"[MIC ERROR] {e}")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def speaker_thread(loop):
    """Pull audio from queue and play it."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_SAMPLE_RATE,
        output=True,
        frames_per_buffer=CHUNK
    )
    try:
        while not stop_event.is_set():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    asyncio.wait_for(audio_output_queue.get(), timeout=0.5),
                    loop
                )
                chunk = future.result(timeout=1)
                if chunk is None:
                    break
                stream.write(chunk)
            except Exception:
                continue
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


async def receive_loop(ws):
    """Handle incoming messages from Deepgram."""
    async for message in ws:
        if isinstance(message, bytes):
            await audio_output_queue.put(message)
        else:
            try:
                event = json.loads(message)
                etype = event.get("type", "unknown")

                if etype == "Welcome":
                    print(f"[SERVER] Connected - session: {event.get('session_id', '')}")
                elif etype == "SettingsApplied":
                    print("[SERVER] Settings applied. Agent is ready!\n")
                elif etype == "UserStartedSpeaking":
                    print("[USER]  🎤 Speaking...")
                elif etype == "AgentThinking":
                    print("[AGENT] 💭 Thinking...")
                elif etype == "AgentStartedSpeaking":
                    print("[AGENT] 🔊 Speaking...")
                elif etype == "AgentAudioDone":
                    print("[AGENT] Done speaking.\n")
                elif etype == "ConversationText":
                    role = event.get("role", "?")
                    text = event.get("content", "")
                    icon = "🧑" if role == "user" else "🤖"
                    print(f"  {icon} [{role.upper()}]: {text}")
                elif etype == "Error":
                    print(f"[ERROR] {event}")
                else:
                    print(f"[EVENT] {etype}: {event}")
            except json.JSONDecodeError:
                print(f"[RAW TEXT] {message}")


async def keepalive(ws):
    """Send periodic keepalive pings to prevent timeout."""
    while not stop_event.is_set():
        await asyncio.sleep(5)
        try:
            await ws.send(json.dumps({"type": "KeepAlive"}))
        except Exception:
            break


async def main():
    if DEEPGRAM_API_KEY == "YOUR_DEEPGRAM_API_KEY_HERE":
        print("ERROR: Please set your DEEPGRAM_API_KEY in the script.")
        sys.exit(1)

    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    print("Connecting to Deepgram Voice Agent...")
    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        await ws.send(json.dumps(SETTINGS))
        print("[CLIENT] Settings sent.")

        loop = asyncio.get_event_loop()

        mic_thread = threading.Thread(target=mic_stream, args=(loop, ws), daemon=True)
        mic_thread.start()

        spk_thread = threading.Thread(target=speaker_thread, args=(loop,), daemon=True)
        spk_thread.start()

        try:
            await asyncio.gather(
                receive_loop(ws),
                keepalive(ws)
            )
        except websockets.ConnectionClosedOK:
            print("\n[INFO] Connection closed.")
        except KeyboardInterrupt:
            print("\n[INFO] Interrupted by user.")
        finally:
            stop_event.set()
            await audio_output_queue.put(None)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")