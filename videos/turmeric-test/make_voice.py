"""Voice-over for The Turmeric Test, spoken by our own voice engine (Kokoro). Run inside the backend container."""
import base64, io, json, os, sys, wave
import httpx
from app.config import get_settings

LINES = [
    "In Indian kitchens, turmeric leaves stubborn stains that linger for days.",
    "But on Silverstone, the non-porous engineered stone, the paste sits on the surface, never sinking in.",
    "A single wipe with a damp cloth lifts the residue, revealing the stone's original white.",
    "No swelling, no staining, zero formaldehyde, just pure, safe stone that lasts.",
    "It also resists water, and termites find nothing to eat, giving families peace of mind for generations every single day.",
]
LEAD, GAP, LIMIT = 0.30, 0.38, 29.3          # seconds: start, pause between lines, latest end of speech
s = get_settings()
voice = os.environ.get("VOICE", s.kokoro_voice)
out = "/tmp/tt"; os.makedirs(out, exist_ok=True)


def say(text, speed):
    r = httpx.post(s.kokoro_url + "/dev/captioned_speech", timeout=300, json={
        "model": "kokoro", "voice": voice, "input": text, "response_format": "wav", "speed": speed,
        "stream": False, "return_timestamps": True})
    r.raise_for_status()
    d = r.json()
    w = wave.open(io.BytesIO(base64.b64decode(d["audio"])))
    return w.getframerate(), w.readframes(w.getnframes()), d["timestamps"]


def build(speed):
    parts = [say(t, speed) for t in LINES]
    rate = parts[0][0]
    pcm, at, lines = bytearray(b"\0\0" * int(LEAD * rate)), LEAD, []
    for i, (_, frames, stamps) in enumerate(parts):
        dur = len(frames) / 2 / rate
        lines.append({"text": LINES[i], "start": round(at, 3), "end": round(at + dur, 3),
                      "words": [{"w": x["word"], "s": round(at + max(0, x["start_time"]), 3),
                                 "e": round(at + x["end_time"], 3)} for x in stamps]})
        pcm += frames
        at += dur
        if i < len(parts) - 1:
            pcm += b"\0\0" * int(GAP * rate); at += GAP
    return rate, pcm, lines, at


speed = float(os.environ.get("SPEED", "1.0"))
rate, pcm, lines, end = build(speed)
if end > LIMIT:
    speed = round(min(1.15, speed * (end - LEAD - 4 * GAP) / (LIMIT - LEAD - 4 * GAP) + 0.005), 3)
    rate, pcm, lines, end = build(speed)
pcm += b"\0\0" * int(max(0.0, 30.0 - end) * rate)
with wave.open(out + "/narration.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(pcm))
json.dump({"voice": voice, "speed": speed, "speech_end": round(end, 3), "lines": lines},
          open(out + "/timings.json", "w"), indent=1)
print("voice", voice, "speed", speed, "speech ends", round(end, 2), "rate", rate)
for l in lines:
    print(l["start"], l["end"], l["text"][:50])
