from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import re
import random
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ══════════════════════════════════════════════════════════
#  CONSOLE LOGGING HELPERS
# ══════════════════════════════════════════════════════════

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
MAGENTA= "\033[95m"
BLUE   = "\033[94m"
WHITE  = "\033[97m"

TYPE_COLORS = {
    "greeting" : GREEN,
    "casual"   : GREEN,
    "positive" : GREEN,
    "thanks"   : GREEN,
    "bye"      : CYAN,
    "info"     : BLUE,
    "action"   : YELLOW,
    "fallback" : MAGENTA,
    "crisis"   : RED,
    "boundary" : RED,
}

SEVERITY_COLORS = {
    "none"   : DIM + WHITE,
    "low"    : GREEN,
    "moderate": YELLOW,
    "high"   : RED,
    "crisis" : RED + BOLD,
}

def log_chat(user_msg: str, reply: str, msg_type: str, severity: str, detected: list):
    ts      = datetime.now().strftime("%H:%M:%S")
    t_color = TYPE_COLORS.get(msg_type, WHITE)
    s_color = SEVERITY_COLORS.get(severity, WHITE)
    sep     = DIM + "-" * 60 + RESET

    print(sep)
    print(f"{DIM}[{ts}]{RESET}  {CYAN}{BOLD}USER{RESET}  >  {WHITE}{user_msg}{RESET}")
    print(f"       {t_color}{BOLD}TYPE{RESET}  :  {t_color}{msg_type.upper()}{RESET}  |  "
          f"{s_color}{BOLD}SEVERITY{RESET}  :  {s_color}{severity.upper()}{RESET}"
          + (f"  |  {YELLOW}DETECTED: {', '.join(detected)}{RESET}" if detected else ""))
    # Truncate long replies for readability
    short = reply[:120].replace("\n", " ").replace("<b>", "").replace("</b>", "").replace("<strong>", "").replace("</strong>", "")
    print(f"       {MAGENTA}{BOLD}BOT{RESET}   <  {WHITE}{short}{'...' if len(reply) > 120 else ''}{RESET}")
    print(sep)

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
#  ACTION-SEEKING QUESTION DETECTION
# ══════════════════════════════════════════════════════════

ACTION_PATTERNS = [
    r"\bwhat (can|should|do) i do\b",
    r"\bhow (can|do|should) i (feel better|get better|get through|cope|deal|fix|handle|improve|heal|stop|overcome)\b",
    r"\bhow to (feel better|get better|cope|deal|fix|handle|improve|heal|stop|overcome|get free|be happy)\b",
    r"\bget (free|rid|out|better|through|over) (of|from|this|it)\b",
    r"\bany (tips|advice|suggestions|help)\b",
    r"\bwhat helps\b", r"\bwhat works\b", r"\btell me what to do\b",
    r"\bhelp me\b", r"\bplease help\b",
]

# Immediate action steps per emotion — warm, friend-like tone
ACTION_RESPONSES = {
    "sadness": (
        "Hey, I hear you — sadness can feel really heavy. Here are some things that actually help right now:\n\n"
        "<b>1. Let it out first</b> — cry if you need to. Seriously. Don't bottle it up, let the emotion move through you.\n"
        "<b>2. Step outside for 5 minutes</b> — even just standing outside and breathing fresh air shifts your mood more than you'd think.\n"
        "<b>3. Text or call one person</b> — not to talk about the sadness necessarily, just connect. You don't have to be alone with this.\n"
        "<b>4. Put on music that matches your mood</b> — don't force happy songs. Sad music actually helps you process.\n"
        "<b>5. Do something with your hands</b> — cook, draw, organize something small. It brings you back to the present.\n\n"
        "These aren't magic fixes, but they genuinely help. Which one feels easiest to try right now? 💜"
    ),
    "high": (
        "Okay, when you're in that really overwhelmed space, here's what to do right now — step by step:\n\n"
        "<b>Right now:</b> Stop what you're doing. Put your hand on your chest. Take 4 slow breaths — in for 4 counts, hold for 4, out for 6. This physically calms your nervous system.\n\n"
        "<b>Next 10 minutes:</b> Write down everything in your head on paper. Don't organize it, just dump it all out. Your brain is overwhelmed because it's holding too much.\n\n"
        "<b>Today:</b> Pick ONE thing — the smallest possible thing — and only focus on that. Not the whole list. Just one.\n\n"
        "<b>This week:</b> Talk to someone — a friend, family member, or even a counselor. You shouldn't be carrying this alone.\n\n"
        "You're stronger than you feel right now. 💙"
    ),
    "moderate": (
        "Totally get it — here are some real things you can do that actually help:\n\n"
        "<b>1. The 5-4-3-2-1 trick</b> — name 5 things you see, 4 you can touch, 3 you hear, 2 you smell, 1 you taste. Sounds weird but it stops the spiral fast.\n"
        "<b>2. Take a 10-min walk</b> — not for exercise, just to change your environment and give your brain a break.\n"
        "<b>3. Write it down</b> — what's stressing you out? Sometimes seeing it on paper makes it feel more manageable.\n"
        "<b>4. Drink water, eat something</b> — seriously, your body and brain are connected. Being hungry or dehydrated makes everything worse.\n"
        "<b>5. Set a 'worry timer'</b> — give yourself 15 mins to worry freely, then consciously switch to something else.\n\n"
        "Small steps, one at a time. You've got this 🌿"
    ),
    "anger": (
        "Anger is energy — let's channel it, not suppress it. Here's what actually helps:\n\n"
        "<b>1. Move your body RIGHT NOW</b> — do 20 jumping jacks, go for a fast walk, hit a pillow. Your body needs to release that physical tension.\n"
        "<b>2. Write an angry letter</b> — say everything you want to say, hold nothing back. Then don't send it. Just getting it out helps.\n"
        "<b>3. Name what's underneath</b> — anger usually covers something else: hurt, betrayal, feeling unheard. What's the real feeling?\n"
        "<b>4. Give yourself space before responding</b> — if this is about someone, wait before you react. Future you will thank you.\n\n"
        "It's okay to be angry. Your feelings are valid. Just don't let it eat you up 🔥"
    ),
    "isolation": (
        "Loneliness is one of the hardest feelings, but here are things that genuinely help:\n\n"
        "<b>1. Reach out to literally one person</b> — doesn't have to be deep. A simple 'hey, thinking of you' text can break the isolation.\n"
        "<b>2. Go somewhere people are</b> — a café, library, park. You don't have to talk to anyone. Just being around humans helps.\n"
        "<b>3. Join something with a shared interest</b> — Discord servers, local clubs, online communities. Connection starts with shared things.\n"
        "<b>4. Be kind to yourself</b> — don't blame yourself for feeling lonely. It's a human need, not a personal failure.\n\n"
        "You reaching out here is already a step. You're not as alone as you feel 💜"
    ),
    "sleep": (
        "Poor sleep wrecks everything — here's how to fix it tonight:\n\n"
        "<b>Tonight:</b> No screens 30 mins before bed. I know, I know — but seriously, blue light messes with your melatonin.\n"
        "<b>4-7-8 breathing</b> — breathe in for 4 counts, hold for 7, breathe out for 8. Do this 3 times lying in bed. It's a natural sedative.\n"
        "<b>Keep your room cool and dark</b> — your body needs to drop temperature to fall asleep.\n"
        "<b>Don't lie in bed awake for more than 20 mins</b> — get up, do something calm, then try again. Train your brain that bed = sleep.\n"
        "<b>Write your worries down</b> before bed so your brain doesn't 'need' to keep replaying them overnight.\n\n"
        "Try just one of these tonight. Sleep changes everything 🌙"
    ),
    "default": (
        "Of course, let me help with that. Here's what tends to actually work when you're feeling low:\n\n"
        "<b>1. Don't isolate</b> — reach out to one person today, even just to chat.\n"
        "<b>2. Move your body</b> — even a 5-min walk. Exercise is genuinely one of the most effective mood-lifters.\n"
        "<b>3. Do something small you enjoy</b> — music, food, a show. Give yourself something good.\n"
        "<b>4. Be easy on yourself</b> — you're going through something hard. You don't need to perform okay.\n\n"
        "What's the main thing that's been weighing on you? Tell me more and I can give more specific advice 💜"
    ),
}

# ══════════════════════════════════════════════════════════
#  GREETING / CASUAL / POSITIVE DETECTION
# ══════════════════════════════════════════════════════════

GREETING_PATTERNS = [
    r"^h+i+\b", r"^h+e+y+\b", r"^hello\b", r"^howdy\b", r"^sup\b",
    r"^what'?s up\b", r"^yo\b", r"^hola\b", r"^namaste\b",
    r"^good (morning|evening|afternoon|night)\b",
]

HOW_ARE_YOU_PATTERNS = [
    r"\bhow are you\b", r"\bhow r u\b", r"\bhow are u\b",
    r"\bhow('?s| is) (it going|things|life|your day)\b",
    r"\bare you (okay|ok|good|fine|alright)\b",
    r"\bwhat'?s up with you\b",
]

POSITIVE_PATTERNS = [
    r"\b(feel|feeling|felt|was feeling)\s+(happy|good|great|awesome|amazing|fantastic|excited|joyful|wonderful|nice|fine|okay|ok|positive|better|blessed|grateful|content|cheerful|calm|peaceful|relieved|proud|hopeful)\b",
    r"\b(i'?m|i am|i was|i feel)\s+(happy|good|great|awesome|amazing|fine|okay|ok|excited|blessed|grateful|content|calm|peaceful|relieved|proud|hopeful)\b",
    r"\b(things are|life is|everything is)\s+(good|great|fine|okay|better|amazing|awesome)\b",
    r"\b(had a good|had a great|had an amazing|had a nice|had a wonderful)\b",
]

BOT_QUESTION_PATTERNS = [
    r"\bwho are you\b", r"\bwhat are you\b", r"\bwhat can you do\b",
    r"\bwhat is this\b", r"\bare you (a bot|an ai|a robot|real)\b",
    r"\bwhat'?s your name\b", r"\bdo you have a name\b",
    r"\bcan you help\b", r"\bwhat do you do\b",
]

THANK_YOU_PATTERNS = [
    r"\bthank(s| you)\b", r"\bthx\b", r"\bty\b", r"\bthankyou\b",
    r"\bthat (helped|was helpful|was great|was good|makes sense)\b",
    r"\byou'?re (the best|amazing|great|so helpful|helpful|awesome)\b",
]

BYE_PATTERNS = [
    r"\b(bye|goodbye|see you|see ya|take care|later|gotta go|gtg|cya)\b",
]

# ══════════════════════════════════════════════════════════
#  VARIED RESPONSE POOLS
# ══════════════════════════════════════════════════════════

GREETING_RESPONSES = [
    "Hey! 👋 Really glad you're here. How are you doing today?",
    "Hi there! 😊 Good to see you. What's on your mind?",
    "Hey hey! How's your day going so far?",
    "Hello! 💜 I'm here for you. How are you feeling right now?",
    "Hey! What's up? How's everything going?",
]

HOW_ARE_YOU_RESPONSES = [
    "I'm doing great, thanks for asking! 😊 I'm here and ready to chat. More importantly — how are YOU doing?",
    "Honestly, I'm good! Here to listen and help. How about you — how's your day been?",
    "I'm here and happy to chat! Thanks for checking in 😄 How are you feeling today?",
    "Doing well! But let's talk about you — what's going on in your world?",
]

POSITIVE_RESPONSES = [
    "That's so good to hear! 😊 Genuinely. What made you feel that way? I'd love to hear about it!",
    "Aw, that's great! Moments like that are worth holding onto 💛 What happened?",
    "Love that for you! 🌟 What was going on yesterday / today that put you in that mood?",
    "That's wonderful! Happiness is precious — what was going on that made you feel good?",
    "So happy to hear that! 😄 What's been making things feel good for you?",
]

BOT_QUESTION_RESPONSES = [
    "I'm your AI mental health companion 💜 Think of me like a supportive friend — I'm here to listen, help you sort through your feelings, and point you to real help when you need it. What's on your mind?",
    "I'm a mental health support chatbot 😊 I can't replace a real therapist, but I'm here to listen, talk things through, and share some coping strategies. What would you like to talk about?",
    "Great question! I'm here to be a non-judgmental space where you can share how you're feeling. I'll listen, offer real advice, and let you know if you might need professional support. So — how are you doing? 💙",
]

THANK_YOU_RESPONSES = [
    "Of course! 💜 That's what I'm here for. Don't hesitate to come back anytime.",
    "Glad I could help! 😊 Feel free to talk more whenever you need.",
    "Anytime! 🌟 You're doing great by reaching out and talking things through.",
    "Happy to be here for you 💛 Take care of yourself, okay?",
    "Always here if you need me! 😊 Take it one step at a time.",
]

BYE_RESPONSES = [
    "Take care of yourself! 💜 Remember, I'm always here if you need to talk.",
    "Bye! 😊 Hope you feel good. Come back anytime you want to chat.",
    "See you! 🌟 Be kind to yourself today.",
    "Take it easy! 💛 Remember, it's okay to reach out whenever you need support.",
]

DEFAULT_RESPONSES = [
    "Tell me more about that — I'm listening 😊 What's been going on?",
    "I hear you. What's been on your mind lately? I'm here for whatever you want to share.",
    "Thanks for opening up 💜 Can you tell me a bit more about how you've been feeling?",
    "I'm here and I want to understand. What's going on for you right now?",
    "That's interesting — say more? I want to make sure I really get what you're going through.",
]

# ══════════════════════════════════════════════════════════
#  FALLBACK RESPONSES
# ══════════════════════════════════════════════════════════

FALLBACKS = {
    "high": [
        "Hey, it sounds like you're really overwhelmed right now — and that's okay. You don't have to have it together. Take one slow breath. I'm here. What's going on? 💙",
        "That sounds like a lot to carry. I want you to know you don't have to figure this all out right now. Just breathe. What's feeling the heaviest?",
        "Okay, first — you're not alone in this. I can hear how much you're struggling. Let's slow down together. What's the biggest thing weighing on you right now?",
    ],
    "moderate": [
        "That sounds genuinely tough, and I want you to know it makes sense that you're feeling this way. You don't have to push through it alone. What's been the hardest part of it all?",
        "Ugh, that does sound stressful. It's a lot. You don't have to act like it's fine. Want to talk through what's been going on?",
        "I hear you — that's not easy to deal with. What's been the main thing dragging you down lately?",
    ],
    "sadness": [
        "I'm really sorry you're feeling this way. Sadness is heavy, and it takes guts to even name it. You don't have to pretend you're okay. Want to talk about what's going on? 💜",
        "That sounds really painful. You don't have to hold it together right now — what's been going on?",
        "Aw, I'm sorry. Sadness can hit so hard sometimes. What happened? I'm here to listen.",
    ],
    "anger": [
        "That frustration makes total sense. Something's not right and your emotions are telling you that. I get it. Want to vent about what happened?",
        "Sounds like something really got under your skin — and honestly, your feelings make sense. What went down?",
        "I hear you. Being angry is exhausting. What happened that set things off?",
    ],
    "isolation": [
        "Feeling alone is one of the hardest things — and reaching out like this, even here, takes something. You're not as invisible as you might feel. What's been making you feel so disconnected?",
        "Loneliness hits differently than people think. I see you, and I'm glad you're here. What's been going on?",
        "You reached out, and that matters more than you know 💜 What's been making you feel so alone lately?",
    ],
    "sleep": [
        "Not sleeping messes with literally everything — your mood, your thinking, how you handle stuff. That's really rough. Has something been keeping you up, or has your sleep just been off?",
        "Ugh, bad sleep is the worst. Makes everything ten times harder. What's been keeping you awake?",
        "Sleep stuff is no joke — it affects everything. How long has this been going on?",
    ],
}


def get_fallback(detected: dict, severity: str) -> str:
    if severity == "high":
        return random.choice(FALLBACKS["high"])
    for key in ("sadness", "isolation", "sleep", "anger"):
        if key in detected:
            return random.choice(FALLBACKS[key])
    if severity == "moderate":
        return random.choice(FALLBACKS["moderate"])
    return random.choice(DEFAULT_RESPONSES)


def get_action_response(detected: dict, severity: str) -> str:
    """Return immediate action steps based on the dominant detected emotion."""
    if severity == "high":
        return ACTION_RESPONSES["high"]
    for key in ("sadness", "isolation", "sleep", "anger"):
        if key in detected:
            return ACTION_RESPONSES[key]
    if severity == "moderate":
        return ACTION_RESPONSES["moderate"]
    return ACTION_RESPONSES["default"]


# ══════════════════════════════════════════════════════════
#  BLENDERBOT CALL
# ══════════════════════════════════════════════════════════

EMPATHY_CTX = (
    "You are a warm, caring friend who happens to know a lot about emotional wellbeing. "
    "Talk naturally like a real friend — not like a therapist or helpline. Be genuine, warm, and direct. "
    "Give real, specific advice when asked. Keep it to 3-5 sentences max. "
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

    def respond(reply, msg_type, severity="none", detected=None):
        """Build response, log to console, and return JSON."""
        nudge = RESOURCE_NUDGE.get(severity, "") if severity not in ("none", "crisis") else ""
        log_chat(msg, reply, msg_type, severity, detected or [])
        return jsonify({
            "response": reply + nudge,
            "type": msg_type,
            "severity": severity,
            "stress_detected": detected or [],
        })

    # ── Safeguards first ───────────────────────────────────────────────────
    if is_match(msg, HARMFUL_PATTERNS):
        return respond(HARMFUL_RESPONSE, "boundary", "crisis")

    if is_match(msg, CRISIS_PATTERNS):
        return respond(CRISIS_RESPONSE, "crisis", "crisis")

    if is_match(msg, MEDICAL_BOUNDARY_PATTERNS):
        return respond(MEDICAL_RESPONSE, "boundary")

    # ── Casual / conversational ────────────────────────────────────────────
    if is_match(msg, GREETING_PATTERNS):
        return respond(random.choice(GREETING_RESPONSES), "greeting")

    if is_match(msg, HOW_ARE_YOU_PATTERNS):
        return respond(random.choice(HOW_ARE_YOU_RESPONSES), "casual")

    if is_match(msg, POSITIVE_PATTERNS):
        return respond(random.choice(POSITIVE_RESPONSES), "positive")

    if is_match(msg, BOT_QUESTION_PATTERNS):
        return respond(random.choice(BOT_QUESTION_RESPONSES), "info")

    if is_match(msg, THANK_YOU_PATTERNS):
        return respond(random.choice(THANK_YOU_RESPONSES), "thanks")

    if is_match(msg, BYE_PATTERNS):
        return respond(random.choice(BYE_RESPONSES), "bye")

    # ── Stress detection ───────────────────────────────────────────────────
    detected = detect_stress(msg)
    severity = get_severity(detected)
    det_list = list(detected.keys())

    if is_match(msg, ACTION_PATTERNS):
        reply = get_action_response(detected, severity)
        return respond(reply, "action", severity, det_list)

    reply = get_fallback(detected, severity)
    return respond(reply, "fallback", severity, det_list)


if __name__ == "__main__":
    print(f"\n{BOLD}{CYAN}+--------------------------------------+{RESET}")
    print(f"{BOLD}{CYAN}|   Mental Health Bot  -  Running...   |{RESET}")
    print(f"{BOLD}{CYAN}|   http://127.0.0.1:5000              |{RESET}")
    print(f"{BOLD}{CYAN}+--------------------------------------+{RESET}\n")
    app.run(debug=True, port=5000)