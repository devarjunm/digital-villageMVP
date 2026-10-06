"""Backend language support (en / mr / hi).

Scope:
  * `resolve_language()` normalises an incoming Accept-Language header or the
    user's stored preference to a supported language.
  * Static, system-generated strings (validation hints, notification titles,
    safety disclaimers) are translated here. They are deliberately kept small:
    agricultural content itself is never machine-translated silently — documents
    carry their own language and the assistant answers in the requested
    language using retrieved content plus an explicit notice when the retrieved
    evidence is in another language.
"""

from __future__ import annotations

from typing import Final

SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = ("en", "mr", "hi")
DEFAULT_LANGUAGE: Final[str] = "en"

_LANGUAGE_ALIASES: Final[dict[str, str]] = {
    "en": "en",
    "en-in": "en",
    "en-us": "en",
    "en-gb": "en",
    "mr": "mr",
    "mr-in": "mr",
    "marathi": "mr",
    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
}

STRINGS: Final[dict[str, dict[str, str]]] = {
    "disclaimer.ai_result": {
        "en": "AI-assisted result — not a confirmed diagnosis.",
        "mr": "AI-आधारित निष्कर्ष — ही पुष्टी केलेली निदान नाही.",
        "hi": "AI-आधारित परिणाम — यह पुष्टि किया गया निदान नहीं है।",
    },
    "disclaimer.model_estimate": {
        "en": "Model estimate — not a guarantee.",
        "mr": "मॉडेल अंदाज — हमी नाही.",
        "hi": "मॉडल अनुमान — यह गारंटी नहीं है।",
    },
    "notice.demo_data": {
        "en": "Demo data from the local development provider — not live data.",
        "mr": "स्थानिक विकास प्रदात्याकडून डेमो डेटा — थेट डेटा नाही.",
        "hi": "स्थानीय विकास प्रदाता से डेमो डेटा — लाइव डेटा नहीं।",
    },
    "notice.insufficient_evidence": {
        "en": "There is not enough indexed evidence to answer this reliably.",
        "mr": "या प्रश्नाचे विश्वासार्ह उत्तर देण्यासाठी पुरावा अपुरा आहे.",
        "hi": "इस प्रश्न का विश्वसनीय उत्तर देने के लिए पर्याप्त प्रमाण नहीं है।",
    },
    "notice.consult_expert": {
        "en": "For a serious problem, please also consult your local agriculture officer or KVK.",
        "mr": "गंभीर समस्येसाठी कृपया स्थानिक कृषी अधिकारी किंवा KVK यांचा सल्ला घ्या.",
        "hi": "गंभीर समस्या के लिए कृपया स्थानीय कृषि अधिकारी या KVK से भी सलाह लें।",
    },
    "error.provider_unavailable": {
        "en": "This data source is temporarily unavailable. Please try again later.",
        "mr": "हा डेटा स्रोत तात्पुरता उपलब्ध नाही. कृपया नंतर प्रयत्न करा.",
        "hi": "यह डेटा स्रोत अस्थायी रूप से उपलब्ध नहीं है। कृपया बाद में प्रयास करें।",
    },
    "notification.reply": {
        "en": "{actor} replied to your post",
        "mr": "{actor} ने तुमच्या पोस्टला उत्तर दिले",
        "hi": "{actor} ने आपकी पोस्ट पर जवाब दिया",
    },
}


def resolve_language(*candidates: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the first supported language found among the candidates."""
    for candidate in candidates:
        if not candidate:
            continue
        tag = candidate.split(",")[0].strip().lower()
        if tag in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[tag]
        short = tag.split("-")[0]
        if short in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[short]
    return default


def t(key: str, language: str = DEFAULT_LANGUAGE, **kwargs: str) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    template = entry.get(resolve_language(language), entry[DEFAULT_LANGUAGE])
    return template.format(**kwargs) if kwargs else template
