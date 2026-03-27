# -*- coding: utf-8 -*-
"""
ATOM - Automated Talking Operating Machine
Version 1 — Full Feature Build
Features:
  - NVIDIA NIM AI (primary answering engine)
  - Layered fallback: NIM → Wikipedia → DuckDuckGo
  - Hindi + All 12 Indian languages (gTTS + googletrans)
  - Auto language detection
  - Translator Mode (live interpreter)
  - Arduino robot control (PySerial, COM6)
  - LED feedback (ON when listening, OFF when done)
  - PDF reading (PyPDF2)
  - Safe calculator (AST eval)
  - YouTube music (yt-dlp + pygame)
  - Weather (OpenWeatherMap)
"""

import os
import re
import ast
import glob
import time
import signal
import random
import tempfile
import operator
import datetime as dt

import pygame
import pyttsx3
import requests
import speech_recognition as sr

# ── Optional imports (graceful if missing) ──────────────────────────────────
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    print("[WARN] gTTS not installed. Multilingual TTS will be unavailable.")

try:
    from googletrans import Translator as GTranslator
    GTRANS_AVAILABLE = True
except ImportError:
    GTRANS_AVAILABLE = False
    print("[WARN] googletrans not installed. Translation features unavailable.")

try:
    import wikipedia
    WIKI_AVAILABLE = True
except ImportError:
    WIKI_AVAILABLE = False

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[WARN] pyserial not installed. Arduino features unavailable.")

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("[WARN] PyPDF2 not installed. PDF reading unavailable.")

try:
    from openai import OpenAI as NvidiaClient   # NVIDIA NIM uses OpenAI-compat API
    NIM_AVAILABLE = True
except ImportError:
    NIM_AVAILABLE = False
    print("[WARN] openai package not installed. NVIDIA NIM unavailable.")

# ==========================================
# CONFIGURATION
# ==========================================

VA_NAME         = "atom"
WEATHER_API_KEY = "ac8d888b5eebbe9e131e7daf96e3dfbc"
WEATHER_URL     = "http://api.openweathermap.org/data/2.5/weather"

# NVIDIA NIM
NIM_API_KEY  = os.getenv("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")
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODEL    = "meta/llama-3.1-70b-instruct"   # Change to any NIM model you prefer

SPEECH_RATE  = 150
VOICE_INDEX  = 1
MIC_INDEX    = None

ARDUINO_PORT = "COM6"
ARDUINO_BAUD = 9600
ARDUINO_COMMANDS = {
    "shake hand": b'9',
    "forward":    b'8',
    "back":       b'7',
    "left":       b'6',
    "right":      b'5',
    "led on":     b'0',
    "led off":    b'1',
}

TEMP_MUSIC_DIR = os.path.join(tempfile.gettempdir(), "atom_music")
os.makedirs(TEMP_MUSIC_DIR, exist_ok=True)

SEARCH_KEYWORDS = ("search for", "google", "who is", "what is", "tell me about")

# ── Language map ─────────────────────────────────────────────────────────────
# All 12 major Indian languages + English
LANGUAGE_MAP = {
    "english":   {"code": "en", "sr_code": "en-IN", "tts": "en"},
    "hindi":     {"code": "hi", "sr_code": "hi-IN", "tts": "hi"},
    "tamil":     {"code": "ta", "sr_code": "ta-IN", "tts": "ta"},
    "telugu":    {"code": "te", "sr_code": "te-IN", "tts": "te"},
    "bengali":   {"code": "bn", "sr_code": "bn-IN", "tts": "bn"},
    "marathi":   {"code": "mr", "sr_code": "mr-IN", "tts": "mr"},
    "gujarati":  {"code": "gu", "sr_code": "gu-IN", "tts": "gu"},
    "kannada":   {"code": "kn", "sr_code": "kn-IN", "tts": "kn"},
    "malayalam": {"code": "ml", "sr_code": "ml-IN", "tts": "ml"},
    "punjabi":   {"code": "pa", "sr_code": "pa-IN", "tts": "pa"},
    "odia":      {"code": "or", "sr_code": "or-IN", "tts": "or"},
    "urdu":      {"code": "ur", "sr_code": "ur-IN", "tts": "ur"},
    "assamese":  {"code": "as", "sr_code": "as-IN", "tts": "as"},
}

# Reverse lookup: detected lang code → language name
LANG_CODE_TO_NAME = {v["code"]: k for k, v in LANGUAGE_MAP.items()}


# ==========================================
# SAFE CALCULATOR  (AST-based, no eval())
# ==========================================

_ALLOWED_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.USub: operator.neg,
}

def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.Num):          # Python < 3.8 compat
        return node.n
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError("Unsupported operator")
        return _ALLOWED_OPS[op_type](_safe_eval(node.left), _safe_eval(node.right))
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    else:
        raise ValueError("Unsupported expression type")

def calculate(expression: str) -> str:
    try:
        clean = re.sub(r'[^0-9+\-*/().\s^]', '', expression).strip()
        clean = clean.replace('^', '**')
        if not clean:
            return "Please give me a valid math expression."
        tree   = ast.parse(clean, mode='eval')
        result = _safe_eval(tree.body)
        # pretty-print: avoid ugly floats like 4.000000000000
        result_str = str(int(result)) if isinstance(result, float) and result.is_integer() else str(result)
        return f"The answer is {result_str}."
    except Exception:
        return "Sorry, I couldn't calculate that."


# ==========================================
# ASSISTANT CLASS
# ==========================================

class VoiceAssistant:
    def __init__(self):
        self.listener                        = sr.Recognizer()
        self.listener.energy_threshold       = 100
        self.listener.dynamic_energy_threshold = True
        self.running          = True
        self.music_playing    = False
        self.current_temp_file = None
        self.current_language = "english"
        self._gtrans          = None   # lazy-loaded

        # ── NVIDIA NIM client ─────────────────────────────────────────────
        self.nim_client = None
        if NIM_AVAILABLE:
            try:
                self.nim_client = NvidiaClient(api_key=NIM_API_KEY, base_url=NIM_BASE_URL)
                print("[INFO] NVIDIA NIM client ready.")
            except Exception as e:
                print(f"[WARN] NIM init failed: {e}")

        # ── Arduino ───────────────────────────────────────────────────────
        self.arduino = None
        if SERIAL_AVAILABLE:
            try:
                self.arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
                time.sleep(2)
                print(f"[INFO] Arduino connected on {ARDUINO_PORT}.")
            except Exception as e:
                print(f"[WARN] Arduino not found on {ARDUINO_PORT}: {e}")

        # ── Mic calibration ───────────────────────────────────────────────
        print("[INFO] Calibrating microphone...")
        try:
            with self._get_microphone() as source:
                self.listener.adjust_for_ambient_noise(source, duration=2)
            print("[INFO] Mic ready.")
        except Exception as e:
            print(f"[WARN] Mic calibration failed: {e}")

        # ── Graceful Ctrl+C shutdown ──────────────────────────────────────
        signal.signal(signal.SIGINT, self._signal_handler)

    # =========================================================================
    # INTERNALS
    # =========================================================================

    def _signal_handler(self, sig, frame):
        print("\n[INFO] Shutting down ATOM...")
        self.running = False
        self.shutdown()
        raise SystemExit(0)

    def _get_microphone(self):
        return sr.Microphone(device_index=MIC_INDEX) if MIC_INDEX is not None else sr.Microphone()

    def _get_translator(self):
        if self._gtrans is None and GTRANS_AVAILABLE:
            self._gtrans = GTranslator()
        return self._gtrans

    def _truncate(self, text: str, word_limit: int = 60) -> str:
        words = text.split()
        return " ".join(words[:word_limit]) + ("..." if len(words) > word_limit else "")

    # =========================================================================
    # LED HELPERS
    # =========================================================================

    def _led_on(self):
        self._send_arduino_raw(b'0')

    def _led_off(self):
        self._send_arduino_raw(b'1')

    # =========================================================================
    # TEXT-TO-SPEECH
    # =========================================================================

    def speak(self, text: str, lang: str = None):
        lang = lang or self.current_language
        print(f"[{VA_NAME.upper()}] {text}")

        # Multilingual TTS via gTTS
        if lang != "english" and GTTS_AVAILABLE:
            tts_code = LANGUAGE_MAP.get(lang, {}).get("tts", "en")
            try:
                tmp = os.path.join(TEMP_MUSIC_DIR, f"tts_{random.randint(1000, 9999)}.mp3")
                gTTS(text=text, lang=tts_code).save(tmp)
                pygame.mixer.init()
                pygame.mixer.music.load(tmp)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                pygame.mixer.music.stop()
                pygame.mixer.quit()
                os.remove(tmp)
                return
            except Exception as e:
                print(f"[WARN] gTTS failed ({e}), falling back to pyttsx3.")

        # Offline English TTS fallback
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", SPEECH_RATE)
            voices = engine.getProperty("voices")
            if VOICE_INDEX < len(voices):
                engine.setProperty("voice", voices[VOICE_INDEX].id)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"[ERR] pyttsx3 failed: {e}")

    # =========================================================================
    # SPEECH RECOGNITION
    # =========================================================================

    def listen(self, lang: str = None) -> str:
        lang     = lang or self.current_language
        sr_code  = LANGUAGE_MAP.get(lang, {}).get("sr_code", "en-IN")
        try:
            self._led_on()
            with self._get_microphone() as source:
                print("[...] Listening...")
                voice = self.listener.listen(source, timeout=8, phrase_time_limit=15)
            self._led_off()
            cmd = self.listener.recognize_google(voice, language=sr_code).lower()
            print(f"[USER] {cmd}")
            return cmd
        except sr.WaitTimeoutError:
            self._led_off()
            return ""
        except sr.UnknownValueError:
            self._led_off()
            return ""
        except Exception as e:
            self._led_off()
            print(f"[WARN] Listen error: {e}")
            return ""

    # =========================================================================
    # AUTO LANGUAGE DETECTION
    # =========================================================================

    def detect_and_set_language(self, raw_text: str):
        """Automatically switch language based on what was spoken."""
        if not GTRANS_AVAILABLE or not raw_text:
            return
        try:
            detected  = self._get_translator().detect(raw_text).lang
            lang_name = LANG_CODE_TO_NAME.get(detected)
            if lang_name and lang_name != self.current_language:
                print(f"[INFO] Auto-detected language: {lang_name}")
                self.current_language = lang_name
        except Exception:
            pass

    # =========================================================================
    # TRANSLATION HELPERS
    # =========================================================================

    def translate_to_english(self, text: str) -> str:
        if not GTRANS_AVAILABLE:
            return text
        try:
            return self._get_translator().translate(text, dest="en").text
        except Exception:
            return text

    def translate_from_english(self, text: str, lang: str) -> str:
        if not GTRANS_AVAILABLE or lang == "english":
            return text
        try:
            code = LANGUAGE_MAP.get(lang, {}).get("code", "en")
            return self._get_translator().translate(text, dest=code).text
        except Exception:
            return text

    # =========================================================================
    # NVIDIA NIM AI  (primary answering engine)
    # =========================================================================

    def ask_nim(self, query: str) -> str:
        if not self.nim_client:
            return None
        try:
            lang_note = (
                f"Reply in {self.current_language}."
                if self.current_language != "english" else ""
            )
            system_prompt = (
                "You are ATOM, a helpful voice assistant. "
                "Give a concise, spoken-English answer in 2-3 short sentences. "
                f"{lang_note}"
            )
            response = self.nim_client.chat.completions.create(
                model=NIM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": query}
                ],
                max_tokens=200,
                temperature=0.5
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[WARN] NIM request failed: {e}")
            return None

    # =========================================================================
    # FALLBACK SEARCH CHAIN
    # =========================================================================

    def _search_wikipedia(self, query: str) -> str:
        if not WIKI_AVAILABLE:
            return None
        try:
            return wikipedia.summary(query, sentences=3)
        except Exception:
            return None

    def _search_duckduckgo(self, query: str) -> str:
        if not DDGS_AVAILABLE:
            return None
        try:
            clean = query
            for kw in SEARCH_KEYWORDS:
                clean = clean.replace(kw, "").strip()
            with DDGS() as ddgs:
                results = list(ddgs.text(clean, max_results=5))
                if results:
                    best = max(results, key=lambda x: len(x.get('body', '')))
                    return self._truncate(best['body'], word_limit=60)
        except Exception:
            pass
        return None

    def smart_answer(self, query: str) -> str:
        """Layered fallback architecture: NIM → Wikipedia → DuckDuckGo."""
        # 1st — NVIDIA NIM
        answer = self.ask_nim(query)
        if answer:
            return answer

        # 2nd — Wikipedia
        print("[INFO] NIM unavailable, trying Wikipedia...")
        answer = self._search_wikipedia(query)
        if answer:
            return self._truncate(answer, 60)

        # 3rd — DuckDuckGo
        print("[INFO] Wikipedia failed, trying DuckDuckGo...")
        answer = self._search_duckduckgo(query)
        if answer:
            return answer

        return "I'm sorry, I couldn't find an answer to that question."

    # =========================================================================
    # WEATHER
    # =========================================================================

    def get_weather(self, city: str) -> str:
        try:
            params = {"q": city, "appid": WEATHER_API_KEY, "units": "metric"}
            data   = requests.get(WEATHER_URL, params=params, timeout=5).json()
            if data.get("cod") == 200:
                desc  = data['weather'][0]['description']
                temp  = data['main']['temp']
                feels = data['main']['feels_like']
                return (f"In {city}, it's {desc} at {temp}°C, "
                        f"feels like {feels}°C.")
            return "Could not find that city. Please try again."
        except Exception:
            return "Weather service is currently unavailable."

    # =========================================================================
    # YOUTUBE MUSIC
    # =========================================================================

    def search_and_play_from_youtube(self, query: str):
        try:
            import yt_dlp
        except ImportError:
            self.speak("yt-dlp is not installed. Cannot play music from YouTube.")
            return

        self.speak(f"Searching YouTube for {query}.")
        self._cleanup_temp_music()

        base = os.path.join(TEMP_MUSIC_DIR, f"song_{random.randint(1000, 9999)}")

        # ── Phase 1: fast download without FFmpeg ────────────────────────
        opts_fast = {
            'format':     'bestaudio[ext=m4a]/bestaudio',
            'outtmpl':    base + '.%(ext)s',
            'quiet':      True,
            'noplaylist': True,
        }
        try:
            with yt_dlp.YoutubeDL(opts_fast) as ydl:
                ydl.extract_info(f"ytsearch1:{query}", download=True)
            files = glob.glob(base + ".*")
            if files:
                self.current_temp_file = files[0]
                pygame.mixer.init()
                pygame.mixer.music.load(self.current_temp_file)
                pygame.mixer.music.play()
                self.music_playing = True
                self.speak("Playing now.")
                return
        except Exception as e:
            print(f"[WARN] Fast download failed: {e}")

        # ── Phase 2: FFmpeg conversion fallback → mp3 ────────────────────
        opts_ffmpeg = {
            'format':         'bestaudio/best',
            'outtmpl':        base + '.%(ext)s',
            'postprocessors': [{
                'key':              'FFmpegExtractAudio',
                'preferredcodec':   'mp3',
                'preferredquality': '192'
            }],
            'quiet':      True,
            'noplaylist': True,
        }
        try:
            with yt_dlp.YoutubeDL(opts_ffmpeg) as ydl:
                ydl.download([f"ytsearch1:{query}"])
            self.current_temp_file = base + ".mp3"
            pygame.mixer.init()
            pygame.mixer.music.load(self.current_temp_file)
            pygame.mixer.music.play()
            self.music_playing = True
            self.speak("Playing now.")
        except Exception as e:
            self.speak("Sorry, YouTube download failed.")
            print(f"[ERR] yt-dlp FFmpeg phase: {e}")

    def stop_music(self):
        try:
            pygame.mixer.music.stop()
            self.music_playing = False
            self.speak("Music stopped.")
        except Exception:
            pass

    def _cleanup_temp_music(self):
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        if self.current_temp_file and os.path.exists(self.current_temp_file):
            try:
                os.remove(self.current_temp_file)
            except Exception:
                pass
        self.current_temp_file = None
        self.music_playing     = False

    # =========================================================================
    # PDF READING
    # =========================================================================

    def read_pdf(self, path: str):
        if not PDF_AVAILABLE:
            self.speak("PyPDF2 is not installed. Cannot read PDF files.")
            return
        path = path.strip().strip('"').strip("'")
        if not os.path.exists(path):
            self.speak(f"I cannot find a file at that path.")
            return
        try:
            with open(path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                total  = len(reader.pages)
                self.speak(f"This PDF has {total} pages. Reading the first page.")
                text = reader.pages[0].extract_text() or ""
                if text.strip():
                    self.speak(self._truncate(text, word_limit=80))
                else:
                    self.speak("The first page appears to be empty or image-only and cannot be read.")
        except Exception as e:
            self.speak("I failed to read that PDF file.")
            print(f"[ERR] PDF read: {e}")

    # =========================================================================
    # ARDUINO CONTROL
    # =========================================================================

    def _send_arduino_raw(self, byte_cmd: bytes):
        if self.arduino and self.arduino.is_open:
            try:
                self.arduino.write(byte_cmd)
            except Exception as e:
                print(f"[WARN] Arduino write failed: {e}")
        else:
            print(f"[WARN] Arduino not connected. Skipping cmd: {byte_cmd}")

    def handle_arduino_command(self, cmd: str) -> bool:
        """Check if cmd matches an Arduino command. Returns True if handled."""
        for phrase, byte_val in ARDUINO_COMMANDS.items():
            if phrase in cmd:
                self.speak(f"Executing {phrase}.")
                self._send_arduino_raw(byte_val)
                return True
        return False

    # =========================================================================
    # TRANSLATOR MODE  (live back-and-forth interpreter)
    # =========================================================================

    def run_translator_mode(self):
        self.speak("Translator mode activated. Say stop translator at any time to exit.")

        self.speak("Person A, which language are you speaking?")
        raw_a = self.listen()
        lang_a = next((n for n in LANGUAGE_MAP if n in raw_a), "english")

        self.speak(f"Got it, {lang_a}. Person B, which language are you speaking?")
        raw_b = self.listen()
        lang_b = next((n for n in LANGUAGE_MAP if n in raw_b), "hindi")

        self.speak(f"Translating between {lang_a} and {lang_b}. Let's begin.")

        turn = "A"
        while self.running:
            cur_lang = lang_a if turn == "A" else lang_b
            tgt_lang = lang_b if turn == "A" else lang_a

            self.speak(f"Person {turn}, speak now.", lang=cur_lang)
            raw = self.listen(lang=cur_lang)
            if not raw:
                continue
            if "stop translator" in raw.lower():
                self.speak("Translator mode ended.")
                return

            english_text = self.translate_to_english(raw)
            translated   = self.translate_from_english(english_text, tgt_lang)
            self.speak(translated, lang=tgt_lang)

            turn = "B" if turn == "A" else "A"

    # =========================================================================
    # LANGUAGE SWITCH HANDLER
    # =========================================================================

    def handle_language_switch(self, cmd: str) -> bool:
        for lang_name in LANGUAGE_MAP:
            if f"switch to {lang_name}" in cmd or f"speak {lang_name}" in cmd:
                self.current_language = lang_name
                self.speak(f"Switched to {lang_name}.", lang=lang_name)
                return True
        return False

    # =========================================================================
    # MAIN COMMAND HANDLER
    # =========================================================================

    def handle_command(self, cmd: str):
        if not cmd:
            return

        # Translate to English for internal logic
        eng = self.translate_to_english(cmd) if self.current_language != "english" else cmd
        eng = eng.lower().strip()

        # ── 1. Arduino (highest priority to avoid word conflicts) ─────────
        if self.handle_arduino_command(eng):
            return

        # ── 2. Stop / exit ────────────────────────────────────────────────
        if any(x in eng for x in ["stop music", "pause music"]):
            self.stop_music()
            return

        if any(x in eng for x in ["goodbye", "exit", "shut down", "shutdown", "stop atom"]):
            self.speak("Goodbye! Have a great day.")
            self.running = False
            return

        # ── 3. Language switch ────────────────────────────────────────────
        if self.handle_language_switch(eng):
            return

        # ── 4. Translator mode ────────────────────────────────────────────
        if "translator mode" in eng or "start translator" in eng:
            self.run_translator_mode()
            return

        # ── 5. Weather ────────────────────────────────────────────────────
        if "weather in" in eng:
            city   = eng.split("weather in")[-1].strip()
            answer = self.get_weather(city)
            self.speak(self.translate_from_english(answer, self.current_language))
            return

        if "weather" in eng:
            # "what's the weather" without city
            self.speak("Which city would you like the weather for?")
            city_raw = self.listen()
            if city_raw:
                answer = self.get_weather(city_raw.strip())
                self.speak(self.translate_from_english(answer, self.current_language))
            return

        # ── 6. Music ──────────────────────────────────────────────────────
        if re.match(r'^play\b', eng):
            song = re.sub(r'^play\s*', '', eng).strip()
            if song:
                self.search_and_play_from_youtube(song)
            else:
                self.speak("What would you like me to play?")
            return

        # ── 7. Time ───────────────────────────────────────────────────────
        if "time" in eng and any(w in eng for w in ["what", "current", "tell"]):
            answer = f"It is {dt.datetime.now().strftime('%I:%M %p')}."
            self.speak(self.translate_from_english(answer, self.current_language))
            return

        # ── 8. Date ───────────────────────────────────────────────────────
        if any(w in eng for w in ["what's today", "today's date", "what date", "current date"]):
            answer = f"Today is {dt.datetime.now().strftime('%A, %d %B %Y')}."
            self.speak(self.translate_from_english(answer, self.current_language))
            return

        # ── 9. Calculator ─────────────────────────────────────────────────
        if re.search(r'[\d]', eng) and any(op in eng for op in ['+', '-', '*', '/', 'plus', 'minus', 'times', 'divided']):
            # normalise spoken math words
            expr = eng
            for word, sym in [("plus","+"),("minus","-"),("times","*"),("divided by","/"),("multiplied by","*")]:
                expr = expr.replace(word, sym)
            expr = re.sub(r'(calculate|what is|how much is|equals?)', '', expr)
            answer = calculate(expr)
            self.speak(self.translate_from_english(answer, self.current_language))
            return

        # ── 10. PDF reading ───────────────────────────────────────────────
        if "read pdf" in eng or "open pdf" in eng:
            m = re.search(r'(read|open)\s+pdf\s+(.+)', eng)
            if m:
                self.read_pdf(m.group(2).strip())
            else:
                self.speak("Please say: read PDF followed by the full file path.")
            return

        # ── 11. Smart search / general knowledge ─────────────────────────
        is_question = (
            any(kw in eng for kw in SEARCH_KEYWORDS) or
            eng.startswith(("how to", "how do", "tell me", "explain",
                             "why ", "when ", "where ", "who ")) or
            len(eng.split()) > 3
        )
        if is_question:
            self.speak("Let me find that for you.")
            answer = self.smart_answer(eng)
            self.speak(self.translate_from_english(answer, self.current_language))
            return

        self.speak("I'm not sure how to help with that. Try asking a question or giving a command.")

    # =========================================================================
    # SHUTDOWN
    # =========================================================================

    def shutdown(self):
        self._cleanup_temp_music()
        if self.arduino and SERIAL_AVAILABLE:
            try:
                self.arduino.close()
                print("[INFO] Arduino connection closed.")
            except Exception:
                pass

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self):
        self.speak(f"Hello, I am {VA_NAME}. How can I help you today?")
        while self.running:
            command = self.listen()
            if command:
                self.detect_and_set_language(command)   # auto language detection
            self.handle_command(command)
        self.shutdown()


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    assistant = VoiceAssistant()
    assistant.run()
