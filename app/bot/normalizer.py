"""
Query normalizer: translates Banglish (Bengali written in English letters)
and Bangla script words into English product terms before catalog search.

This makes the fuzzy search work correctly for queries like:
  "peyaj koto taka?" -> "onion"
  "dimer dam?"       -> "egg"
  "chai er dam?"     -> "tea"
  "চিনির দাম?"      -> "sugar"
"""
from __future__ import annotations

import re
from typing import Dict

# ---------------------------------------------------------------------------
# TRANSLATION table: Banglish / Bangla token → English product name
# These override the noise-word list so product names are never stripped.
# ---------------------------------------------------------------------------
BANGLISH_TRANSLATION: Dict[str, str] = {
    # ── Vegetables ──────────────────────────────────────────────────────────
    "peyaj": "onion", "piyaj": "onion", "pneyaj": "onion", "peyaz": "onion",
    "aloo": "potato", "alu": "potato", "allu": "potato",
    "begun": "brinjal", "begoon": "eggplant",
    "tometo": "tomato", "tomatoe": "tomato",
    "gajar": "carrot",
    "shim": "bean", "seem": "bean", "sheem": "bean",
    "lau": "bottle gourd",
    "jhinga": "ridge gourd",
    "korola": "bitter gourd", "karela": "bitter gourd",
    "patal": "pointed gourd", "patol": "pointed gourd",
    "kakrol": "sponge gourd",
    "mooli": "radish", "mula": "radish",
    "shobji": "vegetable", "sabji": "vegetable", "sobji": "vegetable",
    "shak": "spinach", "shaak": "spinach",
    "dhone": "coriander", "dhonepata": "coriander",
    "fulkopi": "cauliflower", "bandhakopi": "cabbage",
    "kumra": "pumpkin", "komra": "pumpkin",

    # ── Fruits ──────────────────────────────────────────────────────────────
    "aam": "mango",
    "kola": "banana",
    "komola": "orange", "kamla": "orange", "komla": "orange",
    "lichu": "lychee",
    "peyara": "guava", "piara": "guava",
    "boroi": "jujube",
    "khejur": "dates", "khajur": "dates",
    "anar": "pomegranate", "dalim": "pomegranate",
    "narikol": "coconut", "narikel": "coconut", "narkel": "coconut",

    # ── Rice & grains ────────────────────────────────────────────────────────
    "chal": "rice", "chaal": "rice", "chaul": "rice",
    "aata": "flour", "atta": "flour",
    "maida": "flour",
    "suji": "semolina", "shoji": "semolina", "shuji": "semolina",
    "cheera": "flattened rice", "chira": "flattened rice", "chire": "flattened rice",
    "muri": "puffed rice",
    "shemai": "vermicelli", "sheamoi": "vermicelli",

    # ── Protein ─────────────────────────────────────────────────────────────
    "dim": "egg", "deem": "egg", "dimer": "egg",
    "murgi": "chicken", "murgir": "chicken",
    "mangsho": "meat", "mangso": "meat", "mangsas": "meat",
    "gorur": "beef", "goru": "beef",
    "khasi": "mutton", "khasir": "mutton",
    "maach": "fish", "mach": "fish", "macher": "fish",
    "ilish": "hilsha fish", "elish": "hilsha fish",      # catalog: "Hilsha Fish/Ilish"
    "rui": "rui fish",                                    # catalog: "Rui Fish"
    "katla": "katla fish",                                # catalog: "Katla Fish"
    "chingri": "chingri", "chingre": "chingri",          # catalog: "Bagda Chingri", "Golda Chingri"
    "bagda": "bagda chingri",                             # catalog: "Bagda Chingri/Shrimp"
    "golda": "golda chingri",                             # catalog: "Golda Chingri"
    "pangash": "pangas fish", "pangas": "pangas fish",   # catalog: "Pangas Fish"
    "pangasius": "pangas fish",
    "rupchanda": "rupchanda fish", "roopchanda": "rupchanda fish",  # catalog: "Rupchanda Fish"
    # ── More Dhaka fish ─────────────────────────────────────────────────────
    "tengra": "tengra fish", "tengraa": "tengra fish",
    "shing": "shing fish", "sing": "shing fish",
    "magur": "magur fish",
    "pabda": "pabda fish", "pabodha": "pabda fish",
    "bhetki": "bhetki fish", "vetki": "bhetki fish",
    "boal": "boal fish",
    "loitta": "bombay duck", "loittya": "bombay duck",
    "shutki": "dried fish",
    "kachki": "kachki fish",
    "tilapia": "tilapia fish",
    "taki": "taki fish",
    "koi": "koi fish",
    "ayre": "ayre fish", "air": "ayre fish",
    "parshe": "parshe fish",
    "baim": "baim fish",

    # ── Dairy ───────────────────────────────────────────────────────────────
    "dudh": "milk", "doodh": "milk", "duudh": "milk",
    "doi": "yogurt", "dahi": "yogurt",
    "makhon": "butter", "makhan": "butter",
    "ghee": "ghee",

    # ── Spices & condiments ─────────────────────────────────────────────────
    "halud": "turmeric",
    "morich": "chili", "mirchi": "chili",
    "ada": "ginger", "adar": "ginger",
    "rosun": "garlic", "roshun": "garlic", "rasun": "garlic",
    "jeera": "cumin", "jira": "cumin",
    "elachi": "cardamom",
    "darchini": "cinnamon",
    "tejpata": "bay leaf",
    "shorshe": "mustard", "sorshe": "mustard",
    "methi": "fenugreek",
    "masala": "spice",

    # ── Lentils ─────────────────────────────────────────────────────────────
    "dal": "lentil", "daal": "lentil", "daler": "lentil",
    "moshur": "red lentil", "masur": "red lentil",
    "moog": "mung lentil", "mug": "mung", "moong": "mung",
    "chola": "chickpea",
    "motor": "peas",

    # ── Sugar / salt / oil ──────────────────────────────────────────────────
    "chini": "sugar", "chinir": "sugar",
    "laban": "salt", "nun": "salt",
    "tel": "oil", "teler": "oil",
    "soyabin": "soyabean oil", "soybean": "soyabean oil",

    # ── Drinks ──────────────────────────────────────────────────────────────
    # NOTE: "chai"/"cha" means TEA — kept here separately from noise words
    "chai": "tea", "cha": "tea", "chaa": "tea",
    "kafi": "coffee", "kafee": "coffee",
    "pani": "water", "jol": "water",
    "sharbat": "juice",

    # ── Household / personal care ────────────────────────────────────────────
    "sabun": "soap", "sabon": "soap", "shaban": "soap",

    # ── Misc food ───────────────────────────────────────────────────────────
    "mishti": "sweet",
    "cheera": "flattened rice",

    # ── Category names (Banglish → English) ─────────────────────────────────
    "shobji": "vegetables", "sabji": "vegetables", "sobji": "vegetables",
    "fol": "fruits", "phal": "fruits",
    "moshla": "spices", "moshola": "spices",
    "peyoj": "drinks", "paanio": "drinks",
    "snacks": "snacks", "chips": "chips",
    "biscuit": "biscuits", "biskut": "biscuits",
    "noodles": "noodles", "pasta": "pasta",
    "baby": "baby", "baccha": "baby",
    "cleaning": "cleaning", "safai": "cleaning",
}

# Words that carry no product meaning — stripped from the query.
# IMPORTANT: do NOT include "chai"/"cha" here — they mean TEA.
NOISE_WORDS = {
    # Price-query words
    "dam", "daam", "koto", "kemon", "taka", "takar",
    # Order-intent words (stripped so only product name remains)
    "nibo", "nib", "nimu", "nite", "nitesi", "niteci", "nichi",
    "lagbe", "kinbo", "debo", "dibo", "chai_order",
    "dite", "den", "din", "dao", "diyo", "pathao", "send",
    # Bangla grammatical suffixes / connectors
    "er", "ar", "r", "ta", "te", "ke", "gulo", "gula",
    # Category browse noise
    "ki", "ache", "acche", "show", "dekhao", "dekhaw",
    "category", "list", "available", "all",
}

# Bangla Unicode script → English
BANGLA_TO_ENGLISH: Dict[str, str] = {
    "পেঁয়াজ": "onion", "পেয়াজ": "onion",
    "আলু": "potato",
    "ডিম": "egg",
    "মুরগি": "chicken", "মুরগির": "chicken",
    "মাংস": "meat",
    "গরুর": "beef", "গরু": "beef",
    "খাসির": "mutton", "খাসি": "mutton",
    "মাছ": "fish", "মাছের": "fish",
    "ইলিশ": "hilsha fish",
    "রুই": "rui fish",
    "কাতলা": "katla fish",
    "চিংড়ি": "chingri",
    "বাগদা": "bagda chingri",
    "গলদা": "golda chingri",
    "পাঙ্গাশ": "pangas fish",
    "রুপচাঁদা": "rupchanda fish",
    "টেংরা": "tengra fish",
    "শিং": "shing fish",
    "মাগুর": "magur fish",
    "পাবদা": "pabda fish",
    "ভেটকি": "bhetki fish",
    "বোয়াল": "boal fish",
    "লইট্যা": "bombay duck",
    "শুটকি": "dried fish",
    "কাচকি": "kachki fish",
    "তেলাপিয়া": "tilapia fish",
    "তাকি": "taki fish",
    "কই": "koi fish",
    "আইড়": "ayre fish",
    "পার্শে": "parshe fish",
    "চাল": "rice", "চালের": "rice",
    "ডাল": "lentil", "ডালের": "lentil",
    "মসুর": "red lentil",
    "চিনি": "sugar", "চিনির": "sugar",
    "লবণ": "salt",
    "তেল": "oil",
    "দুধ": "milk",
    "দই": "yogurt",
    "মাখন": "butter",
    "ঘি": "ghee",
    "চা": "tea", "চায়ের": "tea",
    "কফি": "coffee",
    "পানি": "water",
    "আটা": "flour",
    "ময়দা": "flour",
    "সুজি": "semolina",
    "হলুদ": "turmeric",
    "মরিচ": "chili",
    "আদা": "ginger",
    "রসুন": "garlic",
    "জিরা": "cumin",
    "সরিষা": "mustard",
    "বেগুন": "brinjal",
    "টমেটো": "tomato",
    "গাজর": "carrot",
    "শিম": "bean",
    "আম": "mango",
    "কলা": "banana",
    "কমলা": "orange",
    "সাবান": "soap",
    "শ্যাম্পু": "shampoo",
    "ছোলা": "chickpea",
    "বিস্কুট": "biscuit",
    "চিড়া": "flattened rice",
    "মুড়ি": "puffed rice",
    "সেমাই": "vermicelli",
    "নারকেল": "coconut",
    "খেজুর": "dates",
    "ডালিম": "pomegranate",
    "পেয়ারা": "guava",
    "লিচু": "lychee",
    # price / noise words to strip
    "দাম": "", "কত": "", "কতটুকু": "", "কেমন": "",
    "এর": "", "র": "", "টার": "", "টাকা": "",
    # order-intent words to strip
    "চাই": "", "লাগবে": "", "দিন": "", "দাও": "", "পাঠাও": "",
    "নিব": "", "নিবো": "", "কিনব": "", "কিনবো": "",
    # category browse words to strip
    "আছে": "", "দেখাও": "", "কি": "", "সব": "",
    # category names
    "সবজি": "vegetables", "ফল": "fruits",
    "মশলা": "spices", "মাংস": "meat",
    "মাছ": "fish",
}


def normalize_query(text: str) -> str:
    """Translate Banglish and Bangla words to English for catalog search.

    1. Replace Bangla Unicode words → English.
    2. Tokenize and replace Banglish words → English using TRANSLATION table.
    3. Strip known noise words (price-query/order words).
    4. Return a clean English search query.
    """
    if not text:
        return text

    result = text.strip()

    # Step 1: Unicode Bangla → English
    for bangla, english in BANGLA_TO_ENGLISH.items():
        result = result.replace(bangla, f" {english} " if english else " ")

    # Step 2: Tokenize and translate Banglish
    tokens = re.split(r"[\s\?!\.,\u2013\u2014]+", result.lower())
    out_tokens = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token in BANGLISH_TRANSLATION:
            english = BANGLISH_TRANSLATION[token]
            if english:
                out_tokens.append(english)
            # else: empty mapping → skip token
        elif token in NOISE_WORDS:
            pass  # strip noise
        else:
            out_tokens.append(token)

    normalized = " ".join(out_tokens).strip()
    # Clean stray punctuation and extra spaces
    normalized = re.sub(r"[^\w\s\u0980-\u09FF]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized if normalized else text  # fallback to original
