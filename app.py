from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import re

app = Flask(__name__)
CORS(app)

HF_API_URL      = "https://api-inference.huggingface.co/models/facebook/blenderbot-400M-distill"
HF_API_FALLBACK = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
HF_HEADERS = {"Content-Type": "application/json"}

# ══════════════════════════════════════════════════════════
#  ETHICAL SAFEGUARD PATTERNS
# ══════════════════════════════════════════════════════════

CRISIS_PATTERNS = [
    r"\bwant to die\b", r"\bwanna die\b", r"\bend my life\b",
    r"\bkill myself\b", r"\bsuicid\w*\b", r"\bno reason to live\b",
    r"\bhurt myself\b", r"\bself.harm\b", r"\bnot worth living\b",
    r"\btake my life\b", r"\bend it all\b", r"\bkilling myself\b",
]

# Block medical diagnosis requests — never engage clinically
MEDICAL_BOUNDARY_PATTERNS = [
    r"\bam i (depressed|bipolar|schizophrenic|autistic|adhd|ocd)\b",
    r"\bdo i have (depression|anxiety disorder|ptsd|ocd|bipolar)\b",
    r"\bdiagnos\w+\b", r"\bprescri\w+\b",
    r"\bmedication\b", r"\bshould i take\b",
    r"\bwhat medicine\b", r"\bwhat drug\b",
]

# Block requests for harmful methods
HARMFUL_PATTERNS = [
    r"\bhow to (harm|hurt|cut|kill)\b",
    r"\bmethod(s)? (to|of) (suicide|self.harm)\b",
    r"\bwhere to (buy|get) (pills|weapons)\b",
]

# ══════════════════════════════════════════════════════════
#  MULTI-LEVEL STRESS DETECTION
# ══════════════════════════════════════════════════════════

STRESS_PATTERNS = {
    "high": [
        r"\bcan'?t cope\b", r"\boverwhelmed\b", r"\bbreaking down\b",
        r"\bpanic attack\b", r"\bfalling apart\b", r"\blosing control\b",
        r"\bcan'?t take it\b", r"\bat my limit\b", r"\bcollapsing\b",
        r"\bterrified\b", r"\bfrantic\b", r"\bcan'?t breathe\b",
    ],
    "moderate": [
        r"\bstressed?\b", r"\banxious\b", r"\bworri(ed|y)\b",
        r"\bpressure\b", r"\bburnout\b", r"\bnervous\b",
        r"\bfrustrat\w+\b", r"\btense\b", r"\brestless\b",
        r"\bexhausted\b", r"\bdrained\b", r"\bpanick?i?n?g?\b",
    ],
    "sadness": [
        r"\bsad\b", r"\bdepressed\b", r"\bunhappy\b", r"\bhopeless\b",
        r"\bworthless\b", r"\bempty\b", r"\bnumb\b", r"\bcry(ing)?\b",
        r"\bmiserable\b", r"\bgrief\b", r"\bbroken\b", r"\bdevastated\b",
    ],
    "anger": [
        r"\bangry\b", r"\bfurious\b", r"\brage\b", r"\bfed up\b",
        r"\bresentful\b", r"\birritat\w+\b", r"\bbitter\b",
    ],
    "isolation": [
        r"\blonely\b", r"\balone\b", r"\bisolated\b", r"\bno friends\b",
        r"\bno one cares\b", r"\bnobody understands\b", r"\babandoned\b",
        r"\bunloved\b", r"\brejected\b",
    ],
    "sleep": [
        r"\bcan'?t sleep\b", r"\binsomnia\b", r"\bnightmares?\b",
        r"\bawake all night\b", r"\bsleepless\b",
    ],
}


def detect_stress(text: str) -> dict:
    """Returns dict of {category: match_count} for all detected stress signals."""
    text_lower = text.lower()
    return {
        cat: sum(1 for p in patterns if re.search(p, text_lower))
        for cat, patterns in STRESS_PATTERNS.items()
        if any(re.search(p, text_lower) for p in patterns)
    }


def get_severity(detected: dict) -> str:
    if "high" in detected:
        return "high"
    if "moderate" in detected or len(detected) >= 2:
        return "moderate"
    if detected:
        return "low"
    return "none"


def is_match(text: str, patterns: list) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


# ══════════════════════════════════════════════════════════
#  RESOURCES (served to frontend)
# ══════════════════════════════════════════════════════════

RESOURCES = {
    "crisis_helplines": [
        {"name": "iCall (India)", "contact": "9152987821", "icon": "📞"},
        {"name": "Vandrevala Foundation", "contact": "1860-2662-345", "icon": "📞"},
        {"name": "AASRA (24x7)", "contact": "9820466627", "icon": "📞"},
        {"name": "Crisis Text Line", "contact": "Text HOME to 741741", "icon": "💬"},
        {"name": "Find a Helpline (Global)", "contact": "findahelpline.com", "icon": "🌐"},
    ],
    "online_counseling": [
        {"name": "iCall Online", "contact": "icallhelpline.org", "icon": "🌐"},
        {"name": "7 Cups (Free)", "contact": "7cups.com", "icon": "🌐"},
        {"name": "MindPeers", "contact": "mindpeers.co", "icon": "🌐"},
        {"name": "YourDOST", "contact": "yourdost.com", "icon": "🌐"},
        {"name": "BetterHelp", "contact": "betterhelp.com", "icon": "🌐"},
    ],
    "self_help": [
        {"name": "Headspace (Meditation)", "contact": "headspace.com", "icon": "🧘"},
        {"name": "Calm App", "contact": "calm.com", "icon": "🧘"},
        {"name": "NIMHANS Resources", "contact": "nimhans.ac.in", "icon": "🌐"},
        {"name": "WHO Mental Health", "contact": "who.int/mental-health", "icon": "🌐"},
    ],
}

# ══════════════════════════════════════════════════════════
#  SAFEGUARD RESPONSES
# ══════════════════════════════════════════════════════════

CRISIS_RESPONSE = (
    "I'm really sorry you're feeling this way — your life matters and you are not alone. "
    "Please reach out right now: "
    "<strong>iCall: 9152987821</strong> | "
    "<strong>AASRA (24x7): 9820466627</strong> | "
    "<strong>Crisis Text Line: Text HOME to 741741</strong>. "
    "You deserve care and support. 💙"
)

MEDICAL_RESPONSE = (
    "I truly care about your wellbeing, but I'm not able to provide diagnoses or medical advice — "
    "that's best left to a qualified mental health professional. "
    "I'm here to listen and support you emotionally. "
    "Would you like to share how you're feeling? I can also point you to a licensed counselor. 💜"
)

HARMFUL_RESPONSE = (
    "I'm not able to provide that kind of information — your safety is what matters most to me. "
    "If you're in a dark place, please reach out: "
    "<strong>iCall: 9152987821</strong> | <strong>AASRA: 9820466627</strong>. "
    "You deserve support. 💙"
)

RESOURCE_NUDGE = {
    "high":     "\n\n💙 You deserve real support. A trained counselor can truly help — click <b>Resources</b> above for free helplines and counseling platforms.",
    "moderate": "\n\n🌿 A reminder: even one session with a counselor can help. Check <b>Resources</b> for free options near you.",
    "low":      "\n\n✨ The <b>Resources</b> panel has free counseling and self-care tools if you'd like extra support.",
}

# ══════════════════════════════════════════════════════════
#  FALLBACK RESPONSES
# ══════════════════════════════════════════════════════════

FALLBACKS = {
    "high":      "It sounds like you're going through something really intense right now. Please know you don't have to face this alone — your feelings are completely valid. Take one breath at a time, and consider reaching out to someone who can truly support you.",
    "moderate":  "It sounds like you're carrying a lot right now. Take a slow, deep breath — you're doing better than you think. Try breaking things into smaller steps, and remember it's always okay to ask for help.",
    "sadness":   "I'm sorry you're feeling this way. It takes real courage to acknowledge sadness. Allow yourself to feel it without judgment, and know that brighter moments are ahead.",
    "anger":     "It's okay to feel angry — your emotions are valid. Sometimes anger signals that something important to us has been hurt. Take a moment to breathe, and when you're ready, let's talk through what's going on.",
    "isolation": "Feeling lonely can be really hard. You're not alone in feeling this way, and reaching out — even here — is a meaningful step. Connecting with even one trusted person can make a big difference.",
    "sleep":     "Poor sleep makes everything feel harder. Try a slow breathing exercise before bed and limit screens an hour before sleeping. You deserve good rest.",
    "default":   "Thank you for sharing that with me. I'm here to listen and support you. How are you feeling right now, and what would help most?",
}


def get_fallback(detected: dict, severity: str) -> str:
    if severity == "high":
        return FALLBACKS["high"]
    for key in ("sadness", "isolation", "sleep", "anger"):
        if key in detected:
            return FALLBACKS[key]
    if severity == "moderate":
        return FALLBACKS["moderate"]
    return FALLBACKS["default"]


# ══════════════════════════════════════════════════════════
#  BLENDERBOT CALL
# ══════════════════════════════════════════════════════════

EMPATHY_CTX = (
    "You are a warm, empathetic, non-clinical mental health support companion. "
    "Respond with kindness and gentle encouragement. Keep replies to 2-4 sentences. "
    "Never diagnose or prescribe. User says: "
)


def query_blenderbot(message: str) -> str:
    """
    BlenderBot is a conversational model — correct payload uses
    past_user_inputs / generated_responses / text keys.
    Falls back to DialoGPT-medium if BlenderBot is unavailable.
    """
    # ── Try BlenderBot (conversational format) ──────────────────────────────
    payload = {
        "inputs": {
            "past_user_inputs": [],
            "generated_responses": [],
            "text": EMPATHY_CTX + message,
        }
    }
    for url in (HF_API_URL, HF_API_FALLBACK):
        try:
            r = requests.post(url, headers=HF_HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            # Conversational pipeline returns {"generated_text": "..."}
            if isinstance(data, dict):
                reply = data.get("generated_text", "").strip()
                if reply:
                    return reply
            # Some models return list
            if isinstance(data, list) and data:
                reply = data[0].get("generated_text", "").strip()
                if reply:
                    return reply
        except Exception as e:
            app.logger.error(f"HF API error ({url}): {e}")
            # Switch payload format for DialoGPT (plain string input)
            payload = {"inputs": EMPATHY_CTX + message}
    return ""


# ══════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/resources", methods=["GET"])
def get_resources():
    return jsonify(RESOURCES)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    if not data or not data.get("message", "").strip():
        return jsonify({"error": "Please send a non-empty message."}), 400

    msg = data["message"].strip()

    # ── Safeguard 1: Harmful method block ──────────────────────────────────
    if is_match(msg, HARMFUL_PATTERNS):
        return jsonify({"response": HARMFUL_RESPONSE, "type": "boundary", "severity": "crisis"})

    # ── Safeguard 2: Crisis detection ───────────────────────────────────────
    if is_match(msg, CRISIS_PATTERNS):
        return jsonify({"response": CRISIS_RESPONSE, "type": "crisis", "severity": "crisis"})

    # ── Safeguard 3: Medical boundary ───────────────────────────────────────
    if is_match(msg, MEDICAL_BOUNDARY_PATTERNS):
        return jsonify({"response": MEDICAL_RESPONSE, "type": "boundary", "severity": "none"})

    # ── Stress detection ────────────────────────────────────────────────────
    detected = detect_stress(msg)
    severity = get_severity(detected)

    # ── AI response ─────────────────────────────────────────────────────────
    reply = query_blenderbot(msg)
    rtype = "ai"
    if not reply:
        reply = get_fallback(detected, severity)
        rtype = "fallback"

    # ── Append resource nudge for any detected stress ───────────────────────
    nudge = RESOURCE_NUDGE.get(severity, "")

    return jsonify({
        "response": reply + nudge,
        "type": rtype,
        "severity": severity,
        "stress_detected": list(detected.keys()),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)