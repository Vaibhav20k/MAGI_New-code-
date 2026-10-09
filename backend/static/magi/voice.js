// Talking to MAGI: the conversation, her voice, and the always-open microphone.
// Lifted out of the home page as it was; the page hands in what it needs (go, pulse, onMood).
const $ = id => document.getElementById(id);

// Speech-to-text may write the wake phrase several ways.
const WAKE = /\b(?:wake[\s-]*up[\s,.!-]*(?:time|magi|maggie|maggi|magic|mai|my|may)|(?:hey|hi|okay|ok)[\s,]+(?:magi|maggie|maggi|maggy|magee))\b[\s,.!?]*/i;
const SLEEP = /\b(?:sleep|good ?night|that'?s all for now|stop listening|stand down)\b/i;
const IDLE_SLEEP_MS = 180000;      // after 3 quiet minutes MAGI goes back to sleep
// Plain "open …" requests are done at once, without waiting for the thinking step.
const NAV = [[/\b(?:approval|approve)/i, "approvals", "the approvals"], [/\bidea/i, "ideas", "the ideas"], [/\b(?:content|blog|creative|video)/i, "content", "the content"],
             [/\bcrawler/i, "crawler", "the crawler"], [/\bmarketing\b.*\b(?:map|agents|built|works)|\b(?:map|agents)\b.*\bmarketing/i, "marketing_map", "how marketing is built"],
             [/\bmarketing/i, "marketing", "marketing"], [/\b(?:home|magi|brain|main screen)\b/i, "home", "the home screen"]];
const NAV_VERB = /^(?:please\s+)?(?:open|go to|take me to|launch|bring up|switch to|close|go back)\b/i;
const MOODS = {off: "MIC OFF", asleep: 'RESTING · SAY "WAKE UP TIME"', listening: "LISTENING", hearing: "HEARING YOU", thinking: "THINKING", speaking: "SPEAKING"};

export function createVoice({go, pulse = () => {}, onMood = () => {}}) {
  const log = $("log"), heard = $("heard"), sayBox = $("say");
  const session = "magi-" + Math.random().toString(36).slice(2, 10);
  let mood = "off", lvl = 1;
  let micOn = false, awake = false, speakOn = true, chatAbort = null, turn = 0, idleTimer = null;

  function setState(s) { mood = s; $("mood").textContent = MOODS[s]; onMood(s); }
  function rest() {
    setState(!micOn ? "off" : awake ? "listening" : "asleep");
    $("mic").textContent = micOn ? "MIC OFF" : "MIC ON"; $("mic").classList.toggle("on", micOn);
    $("mic").setAttribute("aria-pressed", micOn);
  }
  function line(who, body, cls) {
    const d = document.createElement("div"), w = document.createElement("b");
    d.className = "m " + cls; w.textContent = who; d.append(w, document.createTextNode(body));
    log.append(d); log.scrollTop = log.scrollHeight;
    while (log.children.length > 40) log.firstChild.remove();
  }
  function beep(freq, ms = 110) {
    try {
      const o = actx.createOscillator(), g = actx.createGain();
      o.frequency.value = freq; g.gain.value = 0.05; o.connect(g); g.connect(actx.destination);
      o.start(); o.stop(actx.currentTime + ms / 1000);
    } catch (_) {}
  }
  function touch() {
    clearTimeout(idleTimer);
    if (awake) idleTimer = setTimeout(() => { if (awake && !speaking && !chatAbort) goSleep(); else touch(); }, IDLE_SLEEP_MS);
  }
  function wake() { if (awake) return; awake = true; pulse(1); beep(660); setTimeout(() => beep(990), 120); rest(); touch(); }
  function goSleep() { awake = false; turn++; if (chatAbort) { chatAbort.abort(); chatAbort = null; } stopSpeaking(); beep(520); setTimeout(() => beep(390), 120); heard.textContent = ""; rest(); }

  // voice out
  let speaking = false, audioEl = null, ttsDownUntil = 0;
  function chunks(t) {
    const parts = t.replace(/[*_#`>]/g, "").replace(/https?:\/\/\S+/g, "a link").match(/[^.!?\n]+[.!?]*\s*/g) || [t];
    const out = []; let cur = "";
    // the first sentence goes alone so MAGI starts speaking sooner; later ones are grouped
    for (const p of parts) { if (cur && (!out.length || (cur + p).length > 180)) { out.push(cur.trim()); cur = p; } else cur += p; }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  async function fetchVoice(t) {
    if (Date.now() < ttsDownUntil) return null;
    try {
      const r = await fetch("/api/mai/tts", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text: t})});
      if (!r.ok) { ttsDownUntil = Date.now() + 15000; return null; }     // try her own voice again soon; the browser's voice fills in
      return URL.createObjectURL(await r.blob());
    } catch (_) { ttsDownUntil = Date.now() + 8000; return null; }
  }
  function browserSay(t, done) {
    if (!("speechSynthesis" in window)) return done();
    const u = new SpeechSynthesisUtterance(t), vs = speechSynthesis.getVoices();
    u.voice = vs.find(v => v.name === "Google UK English Female") || vs.find(v => /^(Samantha|Karen|Moira|Tessa|Veena)$/.test(v.name)) ||
              vs.find(v => /female/i.test(v.name) && /^en/i.test(v.lang)) || vs.find(v => /^en/i.test(v.lang)) || null;
    u.rate = 1.02; u.pitch = 1.05; u.onend = u.onerror = done;
    speechSynthesis.speak(u);
  }
  async function speak(t, myTurn) {
    t = String(t || "").trim();
    if (!speakOn || !t) return rest();
    const parts = chunks(t);
    speaking = true; echo = 0; setState("speaking");
    let next = fetchVoice(parts[0]);
    for (let i = 0; i < parts.length; i++) {
      const url = await next;
      if (myTurn !== turn || !speaking) return;
      next = i + 1 < parts.length ? fetchVoice(parts[i + 1]) : null;
      await new Promise(done => {
        if (url) {
          audioEl = new Audio(url);
          audioEl.onended = audioEl.onerror = () => { URL.revokeObjectURL(url); done(); };
          audioEl.onpause = done;
          audioEl.play().catch(e => {
            if (e && e.name === "NotAllowedError") {          // Chrome wants one click on the page before it lets sound play
              $("talk").classList.remove("mini"); $("michint").textContent = "Chrome is blocking sound on this page. Click anywhere once, then ask again.";
            }
            done();
          });
        } else browserSay(parts[i], done);
      });
      if (myTurn !== turn || !speaking) return;
    }
    speaking = false; audioEl = null; deafUntil = performance.now() + 400; rest(); touch();
  }
  function stopSpeaking() {
    if (speaking) deafUntil = performance.now() + 250;
    speaking = false;
    if (audioEl) { audioEl.pause(); audioEl = null; }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  }

  // thinking
  async function ask(msg) {
    msg = msg.trim();
    if (!msg) return;
    const myTurn = ++turn;                    // a newer request replaces whatever was in progress
    if (chatAbort) chatAbort.abort();
    stopSpeaking();
    sayBox.value = ""; heard.textContent = "";
    line("YOU", msg, "you");
    touch();
    if (NAV_VERB.test(msg) && msg.split(/\s+/).length <= 8) {
      const hit = /^(?:please\s+)?(?:close|go back)\b/i.test(msg) ? NAV[NAV.length - 1] : NAV.find(n => n[0].test(msg));
      if (hit) { chatAbort = null; go(hit[1]); const reply = `Opening ${hit[2]}.`; line("MAGI", reply, "magi"); return speak(reply, myTurn); }
    }
    chatAbort = new AbortController();
    setState("thinking");
    try {
      const r = await fetch("/api/mai/chat", {method: "POST", signal: chatAbort.signal,
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({message: msg, session})});
      const data = await r.json();
      if (myTurn !== turn) return;
      if (!r.ok) throw new Error(data.detail || "MAGI could not answer.");
      chatAbort = null;
      line("MAGI", data.reply, "magi");
      (data.actions || []).slice(-1).forEach(go);
      speak(data.reply, myTurn);
    } catch (e) {
      if (e.name === "AbortError" || myTurn !== turn) return;
      chatAbort = null;
      line("PROBLEM", String(e.message).slice(0, 240) + " Try again in a moment.", "err");
      rest();
    }
  }

  // voice in: always-open microphone
  let actx = null, analyser = null, stream = null, recorder = null, recChunks = [], ticker = null;
  let noise = 0.01, loud = 0, quiet = 0, inSpeech = false, speechMs = 0, segStart = 0, keep = false;
  let echo = 0, deafUntil = 0;       // how loud MAGI's own voice reaches the microphone; and a short pause after she stops
  const STEP = 40, buf = new Float32Array(1024);
  function newSegment() {
    recChunks = []; keep = false; inSpeech = false; loud = quiet = speechMs = 0; segStart = performance.now();
    const rec = recorder = new MediaRecorder(stream);
    rec.ondataavailable = e => { if (e.data.size) recChunks.push(e.data); };
    rec.onstop = () => {
      const wanted = keep, ms = speechMs, blob = new Blob(recChunks, {type: rec.mimeType});
      if (micOn) newSegment();
      if (wanted) heardSpeech(blob, ms);
    };
    rec.start();
  }
  function endSegment(wanted) { keep = wanted; if (recorder && recorder.state !== "inactive") recorder.stop(); }
  function listen() {
    if (!micOn || !recorder || recorder.state !== "recording") return;
    analyser.getFloatTimeDomainData(buf);
    let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    // While MAGI is talking, her own voice comes back through the speakers (and other people may be talking near
    // the microphone). She yields only to a voice clearly louder than that, held for more than half a second.
    const sounding = speaking && audioEl && !audioEl.paused;
    if (sounding) echo = echo ? echo * .93 + rms * .07 : rms;
    const thr = speaking ? Math.max(0.075, noise * 6, echo * 2.6) : Math.max(0.018, noise * 3.2);
    lvl = 1 + Math.min(rms * 4, 0.16);
    if (performance.now() < deafUntil && !inSpeech) { loud = 0; return; }     // the tail of her own voice is not you
    if (rms > thr) {
      loud++; quiet = 0;
      if (!inSpeech && loud >= (speaking ? 15 : 3)) {
        inSpeech = true;
        if (speaking) { stopSpeaking(); turn++; }          // you interrupted: MAGI stops talking at once
        if (awake) setState("hearing");
      }
      if (inSpeech) speechMs += STEP;
    } else {
      if (!inSpeech) { noise = noise * 0.96 + rms * 0.04; loud = 0; }
      else if (++quiet * STEP >= 680) return endSegment(speechMs >= 320);   // you stopped talking
    }
    if (inSpeech && speechMs > 25000) return endSegment(true);
    // nothing said: start a fresh clip every 2 s so each clip begins just before the speech
    if (!inSpeech && performance.now() - segStart > 2000) endSegment(false);
  }
  let sttBusy = 0;
  async function heardSpeech(blob, ms) {
    if (!awake && (ms > 6000 || sttBusy > 0)) return;        // asleep: only short phrases can be the wake words
    sttBusy++;
    if (awake) heard.textContent = "…";
    try {
      const r = await fetch("/api/mai/stt", {method: "POST", headers: {"Content-Type": blob.type || "audio/webm"}, body: blob});
      const said = r.ok ? ((await r.json()).text || "").trim() : "";
      heard.textContent = "";
      if (!said) { if (awake && !speaking && !chatAbort) rest(); return; }
      const w = said.match(WAKE);
      if (!awake) {
        if (!w) return;
        wake();
        const after = said.slice(w.index + w[0].length).trim();
        if (after.split(/\s+/).filter(Boolean).length >= 2) ask(after);
        return;
      }
      if (SLEEP.test(said) && said.split(/\s+/).length <= 6) { line("YOU", said, "you"); return goSleep(); }
      const cmd = w ? said.slice(w.index + w[0].length).trim() : said;
      if (cmd) ask(cmd); else rest();
    } catch (_) { if (awake) rest(); }
    finally { sttBusy--; }
  }
  function remember(on) { try { localStorage.setItem("magi-mic", on ? "1" : "0"); } catch (_) {} }
  async function micStart() {
    if (micOn) return true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
    } catch (e) {
      $("talk").classList.remove("mini");
      $("michint").textContent = e.name === "NotAllowedError"
        ? "Microphone is blocked. In Chrome: click the icon at the left of the address bar → Microphone → Allow, then reload. On the Mac: System Settings → Privacy & Security → Microphone → turn on Google Chrome."
        : "No microphone found (" + e.name + "). Check that one is connected and not in use by another app.";
      return false;
    }
    $("michint").textContent = "";
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    await actx.resume();
    analyser = actx.createAnalyser(); analyser.fftSize = 1024;
    actx.createMediaStreamSource(stream).connect(analyser);
    micOn = true; newSegment();
    ticker = setInterval(listen, STEP);
    remember(true); rest();
    return true;
  }
  function micStop() {
    if (!micOn) return;
    micOn = false; awake = false; turn++; clearInterval(ticker); stopSpeaking();
    try { if (recorder && recorder.state !== "inactive") recorder.stop(); } catch (_) {}
    stream.getTracks().forEach(t => t.stop());
    lvl = 1; remember(false); rest();
  }
  const micToggle = () => micOn ? micStop() : micStart();
  async function brainClick() { if (!micOn) { if (await micStart()) wake(); return; } awake ? goSleep() : wake(); }

  $("mic").addEventListener("click", micToggle);
  $("askf").addEventListener("submit", e => { e.preventDefault(); ask(sayBox.value); });
  $("voice").addEventListener("click", e => {
    speakOn = !speakOn; e.target.classList.toggle("on", speakOn);
    e.target.textContent = speakOn ? "VOICE ON" : "VOICE OFF"; e.target.setAttribute("aria-pressed", speakOn);
    if (!speakOn) { stopSpeaking(); rest(); } else speak("My voice is on.", turn);        // a quick way to hear that sound works
  });
  // The browser only lets a page open the microphone after a click, so a remembered "mic on" resumes on the first click or key press.
  let wantMic = false;
  try { wantMic = localStorage.getItem("magi-mic") === "1"; } catch (_) {}
  if (wantMic) {
    const resume = e => {
      removeEventListener("pointerdown", resume); removeEventListener("keydown", resume);
      if (!micOn && e.target.id !== "mic") micStart();
    };
    addEventListener("pointerdown", resume); addEventListener("keydown", resume);
  }
  if ("speechSynthesis" in window) speechSynthesis.getVoices();
  rest();
  line("MAGI", 'Hi, I am MAGI, the second brain of Magppie Kitchens. You can ask me anything about us. I am always here for you. Press the space bar or click the brain to switch my microphone on, then say "wake up time".', "magi");

  return {ask, micToggle, brainClick, get mood() { return mood; }, get level() { return lvl; }, get micOn() { return micOn; }};
}
