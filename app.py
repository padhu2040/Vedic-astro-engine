import streamlit as st
import swisseph as swe
from datetime import datetime, timedelta
import plotly.graph_objects as go
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
import pytz
import google.generativeai as genai

# Securely fetch API key from Streamlit Cloud Secrets, or fallback to local config
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    try:
        from api_config import GEMINI_API_KEY
    except ImportError:
        GEMINI_API_KEY = ""

# Import databases
from database import (
    DASHA_YEARS, DASHA_ORDER, RASI_RULERS, ZODIAC, TAMIL_NAMES, BINDU_RULES, 
    identity_db, house_labels, house_leverage_guide, house_effort_guide, lifestyle_guidance
)
from tamil_lang import TAMIL_IDENTITY_DB, TAMIL_LEVERAGE_GUIDE, TAMIL_EFFORT_GUIDE, TAMIL_LIFESTYLE

t_p = {"Sun": "சூரியன்", "Moon": "சந்திரன்", "Mars": "செவ்வாய்", "Mercury": "புதன்", "Jupiter": "குரு", "Venus": "சுக்கிரன்", "Saturn": "சனி", "Rahu": "ராகு", "Ketu": "கேது"}
ZODIAC_TA = {1: "மேஷம்", 2: "ரிஷபம்", 3: "மிதுனம்", 4: "கடகம்", 5: "சிம்மம்", 6: "கன்னி", 7: "துலாம்", 8: "விருச்சிகம்", 9: "தனுசு", 10: "மகரம்", 11: "கும்பம்", 12: "மீனம்"}

# ==========================================
# 1. SETUP & LOCATION ENGINE
# ==========================================
st.set_page_config(page_title="Vedic Astro AI Engine", layout="wide")

def get_location_search(query):
    try:
        if query.strip().isdigit() and len(query.strip()) == 6: query = f"{query}, India"
        return Nominatim(user_agent="vedic_astro_ai").geocode(query, exactly_one=False, limit=10)
    except: return []

def format_address(address_str):
    parts = [p.strip() for p in address_str.split(',')]
    if len(parts) > 4: return f"{parts[0]}, {parts[-3]}, {parts[-1]}"
    return address_str

def get_utc_offset(tz_str, date_obj):
    try:
        tz = pytz.timezone(tz_str)
        if not isinstance(date_obj, datetime): date_obj = datetime.combine(date_obj, datetime(2000, 1, 1, 12, 0).time())
        dt_aware = tz.localize(date_obj) if date_obj.tzinfo is None else date_obj.astimezone(tz)
        return dt_aware.utcoffset().total_seconds() / 3600
    except: return 5.5 

# ==========================================
# 2. CORE ASTRONOMY MATH
# ==========================================
def get_nakshatra_details(lon):
    nak_names = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
    lords = ["Ketu", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury", "Venus"]
    nak_idx = int(lon / 13.333333333)
    return nak_names[nak_idx], lords[nak_idx % 9]

def get_navamsa_chart(lon):
    rasi_num, pada = int(lon / 30) + 1, int((lon % 30) / 3.333333333) + 1
    if rasi_num in [1, 5, 9]: start = 1
    elif rasi_num in [2, 6, 10]: start = 10
    elif rasi_num in [3, 7, 11]: start = 7
    else: start = 4
    return (start + pada - 2) % 12 + 1

def get_dasamsa_chart(lon):
    rasi_num, part = int(lon / 30) + 1, int((lon % 30) / 3.0) + 1
    start = rasi_num if rasi_num % 2 != 0 else (rasi_num + 8) % 12 or 12
    return (start + part - 2) % 12 + 1

def get_dignity(p, r):
    own = {"Sun": [5], "Moon": [4], "Mars": [1,8], "Mercury": [3,6], "Jupiter": [9,12], "Venus": [2,7], "Saturn": [10,11]}
    exalted = {"Sun": 1, "Moon": 2, "Mars": 10, "Mercury": 6, "Jupiter": 4, "Venus": 12, "Saturn": 7, "Rahu": 2, "Ketu": 8}
    neecha = {"Sun": 7, "Moon": 8, "Mars": 4, "Mercury": 12, "Jupiter": 10, "Venus": 6, "Saturn": 1, "Rahu": 8, "Ketu": 2}
    if r in own.get(p, []): return "Own"
    if exalted.get(p) == r: return "Exalted"
    if neecha.get(p) == r: return "Neecha"
    return "Neutral"

def calculate_sav_score(p_pos, lagna):
    scores = [0] * 12
    curr = p_pos.copy(); curr['Lagna'] = lagna
    for p, rules in BINDU_RULES.items():
        if p not in curr: continue
        for ref, offsets in rules.items():
            if ref not in curr: continue
            for off in offsets: scores[(curr[ref] - 1 + off - 1) % 12] += 1
    return scores

def get_bhava_chalit(jd, lat, lon):
    return swe.houses_ex(jd, lat, lon, b'P', swe.FLG_SIDEREAL)[0]

def determine_house(planet_lon, cusps):
    p_lon = planet_lon % 360
    for i in range(12):
        lower, upper = cusps[i], cusps[(i+1)%12]
        if lower < upper:
            if lower <= p_lon < upper: return i + 1
        else:
            if p_lon >= lower or p_lon < upper: return i + 1
    return 1

# ==========================================
# 3. DEEP ANALYSIS ENGINES (100% BILINGUAL)
# ==========================================
def scan_yogas(p_pos, lagna_rasi, lang="English"):
    yogas = []
    p_houses = {p: ((r - lagna_rasi + 1) if (r - lagna_rasi + 1) > 0 else (r - lagna_rasi + 1) + 12) for p, r in p_pos.items() if p != "Lagna"}
    
    if p_pos.get("Sun") == p_pos.get("Mercury"):
        if lang == "Tamil":
            yogas.append({"Name": "புதாதித்ய யோகம் (Budhaditya Yoga)", "Type": "அறிவு மற்றும் வணிகம்", "Description": f"சூரியனும் புதனும் உங்கள் {p_houses.get('Sun')}-ஆம் வீட்டில் இணைந்து இந்த யோகத்தை உருவாக்குகின்றன. இது மிகச்சிறந்த பகுப்பாய்வு திறனையும், கூர்மையான வணிக அறிவையும் தருகிறது. எழுத்து, தொழில்நுட்பம், மற்றும் ஆலோசனைத் துறைகளில் பெரும் வெற்றியைத் தரும்."})
        else:
            yogas.append({"Name": "Budhaditya Yoga", "Type": "Intellect & Commerce", "Description": f"The Sun and Mercury are structurally conjunct in your {p_houses.get('Sun')}th House. This forms a highly analytical and brilliant business mind. You combine the executive authority of the Sun with the tactical communication of Mercury, indicating strong wealth potential through advisory, technology, trade, or writing."})
    
    if "Jupiter" in p_pos and "Moon" in p_pos:
        jup_from_moon = (p_pos["Jupiter"] - p_pos["Moon"] + 1) if (p_pos["Jupiter"] - p_pos["Moon"] + 1) > 0 else (p_pos["Jupiter"] - p_pos["Moon"] + 1) + 12
        if jup_from_moon in [1, 4, 7, 10]:
            if lang == "Tamil":
                yogas.append({"Name": "கஜகேசரி யோகம் (Gajakesari Yoga)", "Type": "புகழ் மற்றும் தெய்வீக பாதுகாப்பு", "Description": "குரு உங்கள் சந்திரனுக்கு கேந்திரத்தில் இருப்பதால் இந்த மாபெரும் யோகம் உருவாகிறது. இது சமுதாயத்தில் பெரும் மதிப்பையும், தெய்வீக பாதுகாப்பையும், எதிரிகளை வெல்லும் சாதுரியத்தையும் தரும்."})
            else:
                yogas.append({"Name": "Gajakesari Yoga", "Type": "Fame & Institutional Protection", "Description": "Jupiter is placed in a foundational angle from your Natal Moon. This is an elite combination for earning widespread respect and divine protection. It grants a noble reputation, social comfort, and the unique ability to defeat competitors through wisdom and diplomacy rather than brute force."})
    
    pm_planets = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa", "Venus": "Malavya", "Saturn": "Sasa"}
    for p, y_name in pm_planets.items():
        if p in p_houses and p_houses[p] in [1, 4, 7, 10] and get_dignity(p, p_pos[p]) in ["Own", "Exalted"]:
            if lang == "Tamil":
                yogas.append({"Name": f"{y_name} மகாபுருஷ யோகம்", "Type": "தனித்துவமான ஆளுமை", "Description": f"{t_p[p]} உங்கள் {p_houses[p]}-ஆம் வீட்டில் மிகவும் வலுவாக அமைந்திருப்பதால் இந்த யோகம் அமைகிறது. இது உங்களை ஒரு மாபெரும் தலைவராகவும் உங்கள் துறையில் அசைக்க முடியாத சக்தியாகவும் உயர்த்தும்."})
            else:
                yogas.append({"Name": f"{y_name} Mahapurusha Yoga", "Type": "Exceptional Domain Authority", "Description": f"{p} is exceptionally strong in a foundational angle ({p_houses[p]}th House). You are mathematically destined to be a recognized authority in the domain ruled by {p}. This grants immense psychological resilience and elevates your status significantly."})
    
    lord_9 = RASI_RULERS[(lagna_rasi + 8) % 12 or 12]
    lord_10 = RASI_RULERS[(lagna_rasi + 9) % 12 or 12]
    if p_pos.get(lord_9) == p_pos.get(lord_10) and lord_9 != lord_10:
        if lang == "Tamil":
            yogas.append({"Name": "தர்ம கர்மாதிபதி யோகம்", "Type": "உயர்ந்த தொழில் அந்தஸ்து", "Description": "உங்களின் 9-ஆம் அதிபதியும் 10-ஆம் அதிபதியும் இணைந்திருப்பதால் இந்த யோகம் அமைகிறது. இது தொழில் ரீதியான மிக உயர்ந்த ராஜ யோகமாகும். நீங்கள் தொட்டதெல்லாம் துலங்கும்."})
        else:
            yogas.append({"Name": "Dharma Karmadhipati Yoga", "Type": "Ultimate Career Destiny", "Description": f"The rulers of your 9th House of Luck and 10th House of Career are united. This represents the highest form of professional Raja Yoga. Your internal life purpose and your external profession are seamlessly aligned."})
    
    if not yogas:
        if lang == "Tamil":
            yogas.append({"Name": "சுயமுயற்சி யோகம் (Independent Karma)", "Type": "சுயம்புவான வெற்றி", "Description": "உங்கள் ஜாதகம் எந்த ஒரு பாரம்பரிய யோகத்தையும் சார்ந்து இல்லை. உங்கள் வெற்றி முற்றிலும் உங்கள் சுயமுயற்சியாலும், விடாமுயற்சியாலும், புத்திக்கூர்மையாலும் மட்டுமே அமையும்."})
        else:
            yogas.append({"Name": "Independent Karma Yoga", "Type": "Self-Made Destiny", "Description": "Your chart does not rely on passive, inherited yogas. Instead, your success is generated purely through active free-will and executing the specific strategies highlighted in your House Scorecard."})
    
    return yogas

def analyze_education(p_pos, lagna_rasi, lang="English"):
    analysis = []
    lord_5 = RASI_RULERS[(lagna_rasi + 4) % 12 or 12]
    mercury_dig = get_dignity("Mercury", p_pos["Mercury"])
    
    if lang == "Tamil":
        analysis.append("#### கல்வி மற்றும் கற்றல் திறன்")
        analysis.append(f"உங்கள் கல்வி மற்றும் அறிவாற்றலை 5-ஆம் அதிபதியான {t_p[lord_5]} தீர்மானிக்கிறார். நீங்கள் எதையும் மேலோட்டமாக படிக்காமல், ஆழமாகப் புரிந்து கொள்ளும் குணம் கொண்டவர்.")
        if mercury_dig in ["Exalted", "Own"]: analysis.append("புதன் மிகவும் வலுவாக இருப்பதால், சிக்கலான தரவுகளைப் பகுப்பாய்வு செய்யும் அபார திறன் உங்களுக்கு உண்டு. கணக்கீடு, தொழில்நுட்பம் சார்ந்த துறைகளில் எளிதாக வெல்வீர்கள்.")
        elif mercury_dig == "Neecha": analysis.append("புதன் பலவீனமாக இருப்பதால், வெறும் மனப்பாடம் செய்வதை விட, உள்ளுணர்வு மற்றும் கற்பனைத்திறன் மூலம் நீங்கள் அதிகம் கற்கிறீர்கள். செயல்முறை கல்வியே உங்களுக்கு ஏற்றது.")
        else: analysis.append("உங்களின் தர்க்க அறிவும், கற்கும் திறனும் சீராக உள்ளது. தொடர்ச்சியான பயிற்சியின் மூலம் எந்த ஒரு துறையிலும் நீங்கள் சிறந்து விளங்க முடியும்.")
        
        analysis.append("#### உத்தி மற்றும் வளர்ச்சி வாய்ப்புகள்")
        if lord_5 == "Mars": analysis.append("கற்றதை உடனடியாக செயல்படுத்துவதன் மூலம் நீங்கள் வெற்றி பெறலாம். உங்கள் பொறுமையின்மையைக் குறைத்துக் கொள்ள வேண்டும்.")
        elif lord_5 == "Venus": analysis.append("கலை, அழகு மற்றும் அமைப்பு ரீதியான துறைகளில் நீங்கள் சிறந்து விளங்குவீர்கள். கடினமான விஷயங்களை ஒதுக்கும் பழக்கத்தை மாற்ற வேண்டும்.")
        elif lord_5 == "Mercury": analysis.append("கற்பித்தல், எழுதுதல் மற்றும் கணக்கீட்டுத் துறைகள் உங்களுக்கு ஏற்றவை. ஒரே நேரத்தில் பல வேலைகளைச் செய்வதைத் தவிர்க்கவும்.")
        elif lord_5 == "Jupiter": analysis.append("ஆலோசனை, வழிகாட்டுதல் மற்றும் கொள்கை உருவாக்கும் பொறுப்புகளில் பிரகாசிப்பீர்கள். மற்றவர்களின் கருத்துக்களையும் கேட்கப் பழக வேண்டும்.")
        elif lord_5 == "Saturn": analysis.append("நீண்டகால திட்டங்களை உருவாக்குவதில் வல்லவர். முடிவுகளை விரைவாக எடுக்கப் பழக வேண்டும்.")
        elif lord_5 == "Sun": analysis.append("தலைமைப் பொறுப்புகள் உங்களுக்கு மிகவும் இயல்பாக வரும். மற்றவர்களை நம்பி வேலைகளை ஒப்படைக்கப் பழக வேண்டும்.")
        elif lord_5 == "Moon": analysis.append("மனித வள மேலாண்மை மற்றும் உணர்வுப்பூர்வமான துறைகளில் சிறப்பீர்கள். உணர்ச்சிகளையும் தொழில்முறை முடிவுகளையும் பிரிக்கப் பழக வேண்டும்.")
    else:
        analysis.append("#### Academic Profile & Learning Style")
        analysis.append(f"Your primary intellect and academic capacity are governed by the 5th House lord, {lord_5}. This indicates that you learn best when the subject matter naturally aligns with {lord_5}'s energy. You do not just memorize; you need the material to resonate with your core drive.")
        if mercury_dig in ["Exalted", "Own"]: analysis.append(f"Because Mercury (the planet of logic) is highly dignified, your capacity to process complex data is elite. You excel in technical, analytical, or heavily communicative fields. You can out-study your peers easily.")
        elif mercury_dig == "Neecha": analysis.append("Your Mercury is mathematically debilitated, which actually means you possess highly intuitive, abstract intelligence rather than strict rote-memorization skills. Traditional classroom testing may frustrate you, but you excel in creative or big-picture problem-solving.")
        else: analysis.append("Your logical processing is balanced. You can apply yourself to a wide variety of subjects successfully, provided you maintain academic discipline and structured study routines.")
        
        analysis.append("#### Strategic Application & Growth Opportunities")
        if lord_5 == "Mars": analysis.append("Apply your knowledge through immediate, hands-on execution. Your primary improvement opportunity is patience; do not skip foundational theories in a rush to see results.")
        elif lord_5 == "Venus": analysis.append("Apply your knowledge by making systems more harmonious or aesthetically pleasing. Your primary gap to close is avoiding difficult or 'ugly' subjects; lean into discomfort to grow.")
        elif lord_5 == "Mercury": analysis.append("Apply your learnings by teaching, writing, or building analytical frameworks. Your gap is distraction; consciously focus on mastering one subject before jumping to the next.")
        elif lord_5 == "Jupiter": analysis.append("Apply your wisdom in advisory, mentorship, or policy-making roles. Your gap to close is dogma; remain open to new, unconventional data that challenges your existing beliefs.")
        elif lord_5 == "Saturn": analysis.append("Apply your knowledge to build long-lasting, highly structured systems. Your gap to close is speed; learn to make quicker decisions even when you don't have 100% of the data.")
        elif lord_5 == "Sun": analysis.append("Apply your intellect to take on absolute leadership and public authority roles. Your primary gap to close is delegating; trust others to handle the details so you can focus on the vision.")
        elif lord_5 == "Moon": analysis.append("Apply your learnings to emotionally intelligent leadership, HR, or healing. Your primary gap is objective detachment; learn to separate your personal feelings from professional data.")
    return analysis

def analyze_health(p_pos, lagna_rasi, lang="English"):
    analysis = []
    lagna_lord = RASI_RULERS[lagna_rasi]
    ll_dig = get_dignity(lagna_lord, p_pos[lagna_lord])
    lord_6 = RASI_RULERS[(lagna_rasi + 5) % 12 or 12]
    
    if lang == "Tamil":
        analysis.append("#### அடிப்படை உடல் வலிமை")
        if ll_dig in ["Exalted", "Own"]: analysis.append(f"லக்னாதிபதி ({t_p[lagna_lord]}) மிகவும் வலுவாக உள்ளார். இது உங்களுக்கு இரும்பு போன்ற உடல் வலிமையையும், வியக்கத்தக்க நோய் எதிர்ப்பு சக்தியையும் அளிக்கிறது. சோர்விலிருந்து மிக விரைவாக மீண்டு வருவீர்கள்.")
        elif ll_dig == "Neecha": analysis.append(f"லக்னாதிபதி ({t_p[lagna_lord]}) பலவீனமாக உள்ளார். உங்கள் உடல் சக்தியை நீங்கள் மிகவும் கவனமாக கையாள வேண்டும். முறையான உணவு மற்றும் உறக்கமே உங்களுக்கு சிறந்த மருந்து.")
        else: analysis.append(f"லக்னாதிபதி ({t_p[lagna_lord]}) சமநிலையில் உள்ளார். உங்களின் வாழ்க்கை முறை மற்றும் பழக்கவழக்கங்களே உங்கள் ஆரோக்கியத்தை தீர்மானிக்கும். நல்ல பழக்கங்கள் அதிக ஆற்றலைத் தரும்.")
        
        analysis.append("#### கவனிக்க வேண்டிய ஆரோக்கிய குறிப்புகள்")
        analysis.append(f"ஆரோக்கியத்தை குறிக்கும் 6-ஆம் அதிபதி {t_p[lord_6]} ஆவார். இதைப் பொறுத்து நீங்கள் பின்வரும் விஷயங்களில் கவனம் செலுத்த வேண்டும்:")
        if lord_6 == "Mars": analysis.append("உடல் உஷ்ணம், ரத்த அழுத்தம் மற்றும் சிறு விபத்துகள் குறித்து கவனமாக இருக்க வேண்டும். கோபத்தைக் குறைப்பது அவசியம்.")
        elif lord_6 == "Venus": analysis.append("சர்க்கரை அளவு, சிறுநீரகம் மற்றும் ஹார்மோன் ஏற்றத்தாழ்வுகள் குறித்து கவனம் தேவை. முறையான உணவுப் பழக்கம் அவசியம்.")
        elif lord_6 == "Mercury": analysis.append("நரம்பு தளர்ச்சி, மன அழுத்தம் மற்றும் செரிமானக் கோளாறுகள் வர வாய்ப்புள்ளது. தியானம் மற்றும் மன அமைதி அவசியம்.")
        elif lord_6 == "Jupiter": analysis.append("கல்லீரல் செயல்பாடுகள், உடல் பருமன் மற்றும் கொலஸ்ட்ரால் குறித்து எச்சரிக்கையாக இருக்க வேண்டும். உடற்பயிற்சி கட்டாயம்.")
        elif lord_6 == "Saturn": analysis.append("எலும்பு தேய்மானம், மூட்டு வலி மற்றும் நாள்பட்ட வலிகள் வரலாம். யோகா மற்றும் கால்சியம் உணவுகள் மிகவும் அவசியம்.")
        elif lord_6 == "Sun": analysis.append("இதய ஆரோக்கியம், கண் பார்வை மற்றும் முதுகுத் தண்டுவடம் சார்ந்த பிரச்சினைகளை முன்கூட்டியே கண்காணிக்க வேண்டும்.")
        elif lord_6 == "Moon": analysis.append("நீர் சளி, நெஞ்சு சளி மற்றும் மன அழுத்தம் சார்ந்த உடல் உபாதைகள் வரலாம். மன அமைதியே உங்களுக்கு சிறந்த மருந்து.")
    else:
        analysis.append("#### Core Physical Resilience")
        if ll_dig in ["Exalted", "Own"]: analysis.append(f"Your Ascendant Lord ({lagna_lord}) is exceptionally strong. This grants you a highly robust physical constitution and excellent natural immunity. You recover from illness and physical exhaustion much faster than average.")
        elif ll_dig == "Neecha": analysis.append(f"Your Ascendant Lord ({lagna_lord}) is weak by sign placement. Your physical energy is finite and must be carefully managed. You cannot rely on 'natural' vitality; you must strictly enforce dietary and sleep discipline to avoid chronic fatigue.")
        else: analysis.append(f"Your Ascendant Lord ({lagna_lord}) is in a neutral state. Your physical resilience is average. It will directly reflect your lifestyle choices—good routines yield high energy, while poor habits will immediately show physical consequences.")
        
        analysis.append("#### Vulnerabilities & Preventative Care")
        analysis.append(f"The 6th House of acute health is ruled by {lord_6}. This points to the specific physiological systems you must proactively monitor and protect throughout your life.")
        if lord_6 == "Mars": analysis.append("Watch for inflammation, heat-related issues, blood pressure spikes, and physical accidents. You must find a healthy outlet for stress to avoid migraines or physical burnout.")
        elif lord_6 == "Venus": analysis.append("Watch for issues related to sugar intake, kidneys, and hormonal imbalances. Maintaining a very clean, structured diet is your primary preventative medicine.")
        elif lord_6 == "Mercury": analysis.append("Watch for nervous system exhaustion, anxiety, and digestive/gut issues. High stress immediately impacts your stomach. Meditation and unplugging from screens are mandatory.")
        elif lord_6 == "Jupiter": analysis.append("Watch for issues related to liver function, weight gain, and cholesterol. You have a tendency to over-indulge in rich foods or sedentary behavior. Regular cardio is essential.")
        elif lord_6 == "Saturn": analysis.append("Watch for bone density issues, joint stiffness, arthritis, and chronic, slow-moving ailments. Daily stretching, yoga, and calcium management are critical as you age.")
        elif lord_6 == "Sun": analysis.append("Watch for heart health, eyesight deterioration, and upper back/spine issues. Ensure you get adequate sunlight and monitor your cardiovascular system regularly.")
        elif lord_6 == "Moon": analysis.append("Watch for water retention, chest/lung congestion, and heavily psychosomatic illnesses (where mental stress creates physical symptoms). Emotional peace is your best medicine.")
    return analysis

def analyze_love_marriage(d1_lagna, d9_lagna, p_d9, p_d1, lang="English"):
    analysis = []
    lord_5 = RASI_RULERS[(d1_lagna + 4) % 12 or 12]
    d9_7th_lord = RASI_RULERS[(d9_lagna + 6) % 12 or 12]
    
    if lang == "Tamil":
        analysis.append("#### காதல் மற்றும் திருமண வாழ்க்கை")
        analysis.append(f"உங்கள் காதல் உணர்வுகள் 5-ஆம் அதிபதியான {t_p[lord_5]} ஆல் ஆளப்படுகிறது. எனவே தொடக்கத்தில் உற்சாகமான மற்றும் உங்கள் எதிர்பார்ப்புகளுக்கு ஏற்ற உறவுகளை நாடுவீர்கள்.")
        analysis.append(f"ஆனால், உங்கள் நிரந்தர திருமண வாழ்க்கை நவாம்சத்தின் 7-ஆம் அதிபதியான {t_p[d9_7th_lord]} இன் குணங்களைச் சார்ந்திருக்கும். இந்த குணங்களைக் கொண்ட துணையே உங்களுக்கு நீண்டகால மகிழ்ச்சியைத் தருவார்.")
        
        if d9_7th_lord == "Saturn": analysis.append("கடமை, சகிப்புத்தன்மை மற்றும் நீண்டகால விசுவாசத்தின் அடிப்படையில் உங்கள் திருமணம் அமையும். காலப்போக்கில் இது உடைக்க முடியாத கோட்டையாக மாறும்.")
        elif d9_7th_lord in ["Venus", "Moon"]: analysis.append("உங்கள் திருமண வாழ்க்கை ஆழமான உணர்வுப்பூர்வமான தொடர்பு மற்றும் பரஸ்பர அக்கறையை அடிப்படையாகக் கொண்டது.")
        elif d9_7th_lord in ["Sun", "Mars"]: analysis.append("உங்கள் திருமணம் மிகவும் சுறுசுறுப்பானதாக இருக்கும். தீவிரமான இலக்குகளை நோக்கி இருவரும் பயணிப்பீர்கள், ஆனால் ஈகோ மோதல்களைத் தவிர்க்க வேண்டும்.")
        elif d9_7th_lord in ["Mercury", "Jupiter"]: analysis.append("உங்கள் திருமணம் அடிப்படையில் ஒரு அறிவுப்பூர்வமான மற்றும் ஆன்மீக நட்பாகும். தெளிவான தகவல் தொடர்பு உங்களை இணைக்கும் பலமான கயிறு.")

        analysis.append("#### சுக்கிரனின் பலம் (காதலிக்கும் திறன்)")
        venus_dig = get_dignity("Venus", p_d9['Venus'])
        if venus_dig in ["Exalted", "Own"] or p_d1['Venus'] == p_d9['Venus']: analysis.append("சுக்கிரன் மிகவும் வலுவாக உள்ளார். உங்கள் துணையிடம் ஆழமான அன்பைக் காட்டும் திறன் உங்களுக்கு இயல்பாகவே உள்ளது. திருமணத்திற்குப் பிறகு அதிர்ஷ்டம் கூடும்.")
        elif venus_dig == "Neecha": analysis.append("சுக்கிரன் பலவீனமாக இருப்பதால், உறவுகளில் அதிக எதிர்பார்ப்புகளைத் தவிர்க்க வேண்டும். துணையின் குறைகளை ஏற்றுக்கொள்ளப் பழக வேண்டும்.")
        else: analysis.append("சுக்கிரன் சமநிலையில் உள்ளார். உங்கள் திருமண வாழ்க்கை சீராக இருக்க பரஸ்பர புரிதலும், விட்டுக்கொடுக்கும் மனப்பான்மையும் அவசியம்.")
            
        vargottama = [t_p[p] for p in p_d1.keys() if p != "Lagna" and p in p_d9 and p_d1[p] == p_d9[p]]
        if vargottama:
            v_str = ", ".join(vargottama)
            analysis.append(f"#### வர்கோத்தம பலம்\nஉங்கள் ஜாதகத்தில் {v_str} வர்கோத்தம பலம் பெற்றுள்ளன. இவை உங்கள் வாழ்க்கையின் அசைக்க முடியாத தூண்களாகச் செயல்பட்டு நிலையான வெற்றியைத் தரும்.")
    else:
        analysis.append("#### The Dating Phase vs. The Marriage Phase")
        analysis.append(f"Your approach to early romance (5th House) is governed by {lord_5}, meaning you initially seek partners who are exciting, creative, and align with {lord_5}'s specific energy. However, what you *want* in dating is entirely different from what you *need* for a lifelong marriage.")
        analysis.append(f"The 7th House of your Navamsa (D9) reveals your ultimate spousal archetype. It is ruled by {d9_7th_lord}. To achieve a permanently successful marriage, your partner must fundamentally embody {d9_7th_lord}'s mature traits.")
        if d9_7th_lord == "Saturn": analysis.append("Expect a marriage built entirely on duty, endurance, and long-term loyalty. It may lack intense early romance, but it grows into an incredibly unbreakable and secure fortress over time.")
        elif d9_7th_lord in ["Venus", "Moon"]: analysis.append("Your long-term partnerships absolutely thrive on deep emotional connection, mutual aesthetics, and physical comfort. Relentless harmony and active daily care are non-negotiable for success.")
        elif d9_7th_lord in ["Sun", "Mars"]: analysis.append("Expect a highly dynamic, high-energy marriage. There will be intense passion and mutual pushing towards ambitious goals, but you must consciously and actively manage ego clashes.")
        elif d9_7th_lord in ["Mercury", "Jupiter"]: analysis.append("Your marriage is fundamentally an intellectual or spiritual friendship. Crystal clear communication, shared life philosophies, and continuous mutual learning are what truly bind you together.")
        
        analysis.append("#### Venus Strength (The Capacity to Love)")
        venus_dig = get_dignity("Venus", p_d9['Venus'])
        if venus_dig in ["Exalted", "Own"] or p_d1['Venus'] == p_d9['Venus']: analysis.append("Venus Strength: Exceptional. Your capacity to give and receive love matures beautifully over time. Post-marriage, your financial luck, social status, and general life fortune will see a marked, structural increase.")
        elif venus_dig == "Neecha": analysis.append("Venus Strength: Requires active effort. You must consciously work on not being overly critical or demanding in intimate relationships. Learning to accept the inherent human imperfections in your partner is your major relationship lesson.")
        else: analysis.append("Venus Strength: Balanced. Your relationships require standard daily maintenance, mutual respect, and active, engaged listening to thrive. Love is a choice you make daily.")
            
        vargottama = [p for p in p_d1.keys() if p != "Lagna" and p in p_d9 and p_d1[p] == p_d9[p]]
        if vargottama:
            v_str = ", ".join(vargottama)
            analysis.append(f"#### Hidden Strengths (Vargottama Planets)\nPlanets in the exact same sign in D1 and D9 are tremendously powerful. You have {v_str} as Vargottama. These planets act as unshakeable structural pillars in your life, providing highly consistent positive results regardless of external chaos.")
        else: analysis.append("Your planetary energies are highly adaptable. You evolve and dynamically change your approach to challenges as you grow older.")
    return analysis

def analyze_career_professional(p_pos, d10_lagna, lagna_rasi, sav_scores, bhava_placements, lang="English"):
    analysis = []
    sun_rasi_h = (p_pos['Sun'] - lagna_rasi + 1) if (p_pos['Sun'] - lagna_rasi + 1) > 0 else (p_pos['Sun'] - lagna_rasi + 1) + 12
    sun_bhava_h = bhava_placements['Sun'] 
    
    if lang == "Tamil":
        analysis.append("#### பாவ சலித் பகுப்பாய்வு (சூட்சுமம்)")
        if sun_rasi_h != sun_bhava_h:
            analysis.append(f"முக்கிய மாற்றம்: உங்கள் சூரியன் {sun_rasi_h}-ஆம் ராசியில் இருந்தாலும், அது {sun_bhava_h}-ஆம் பாவத்திலேயே முழுமையாகச் செயல்படுகிறது. உங்கள் உழைப்பிற்கான பலன் இந்த பாவத்தின் வழியே கிடைக்கும்.")
            if sun_bhava_h == 10: analysis.append("இது மிகவும் சக்திவாய்ந்த அமைப்பாகும். சூரியன் நேரடியாக உங்கள் தொழில் அதிகாரத்தை (10-ஆம் பாவம்) இயக்குகிறார்.")
            elif sun_bhava_h == 9: analysis.append("உங்கள் தலைமைத்துவம் நேரடியாக 'அதிகாரம்' (10-ஆம் பாவம்) செலுத்துவதை விட, 'வழிகாட்டுதல்' (9-ஆம் பாவம்) மூலமாகவே அதிகம் வெளிப்படும்.")
            elif sun_bhava_h == 11: analysis.append("உங்கள் தொழில் நோக்கம் வெறும் அந்தஸ்தை (10) விட, லாபத்தையும் நெட்வொர்க்கையும் (11) பெருக்குவதிலேயே இருக்கும்.")
        else: 
            analysis.append(f"நேரடி பலன்: உங்கள் சூரியன் {sun_rasi_h}-ஆம் ராசியிலும் பாவத்திலும் சரியாகப் பொருந்தி செயல்படுகிறார். உங்கள் எண்ணங்களும் செயல்களும் நேரடியாக வெற்றியைத் தரும்.")

        analysis.append("#### நடுத்தர வயது வியூகம் (48+ வயது)")
        if sav_scores[9] > 28: analysis.append("உங்கள் தொழில் ஸ்தானம் மிகவும் வலுவாக உள்ளது. நீங்கள் தற்போது இருக்கும் துறையிலேயே முழு கவனத்தையும் செலுத்தி ஒரு மாபெரும் சாம்ராஜ்யத்தை உருவாக்கலாம். துறை மாற வேண்டாம்.")
        else: analysis.append("தொழில் ஸ்தானம் சற்று பலவீனமாக உள்ளதால், நீங்கள் நேரடியாக உழைப்பதை விட, மற்றவர்களுக்கு ஆலோசனை வழங்குதல் மற்றும் வழிகாட்டுதல் மூலமாகவே அதிக வெற்றியைப் பெறுவீர்கள். 11-ஆம் வீட்டின் (நெட்வொர்க்) உதவியைப் பயன்படுத்துங்கள்.")

        d10_lord = RASI_RULERS[(d10_lagna + 9) % 12 or 12]
        role, traits = "பொது மேலாண்மை", "தலைமைத்துவம்"
        if d10_lord == "Mars": role, traits = "பொறியியல், செயல்பாடு, ரியல் எஸ்டேட்", "தீர்க்கமான முடிவுகள்"
        elif d10_lord == "Mercury": role, traits = "தரவு பகுப்பாய்வு, நிதி, வணிகம்", "கூர்மையான பகுப்பாய்வு"
        elif d10_lord == "Jupiter": role, traits = "ஆலோசனை, வழிகாட்டுதல், கல்வி", "ஞானம் மற்றும் விவேகம்"
        elif d10_lord == "Venus": role, traits = "கலை, வடிவமைப்பு, விருந்தோம்பல்", "இராஜதந்திரம்"
        elif d10_lord == "Saturn": role, traits = "கட்டமைப்பு, தளவாடங்கள், பொது நிர்வாகம்", "கடும் ஒழுக்கம்"
        elif d10_lord == "Sun": role, traits = "அரசாங்கம், உயர் நிர்வாகம், கொள்கை உருவாக்கம்", "அதிகாரம்"
        
        analysis.append("#### தசாம்ச D10 (தொழில் வெற்றி ரகசியம்)")
        analysis.append(f"உங்கள் தசாம்ச (D10) அதிபதி {t_p[d10_lord]}. உங்களுக்குப் பொருத்தமான தொழில் முறை: **{role}**. உங்களின் மிகப்பெரிய பலம் '**{traits}**' ஆகும். நெருக்கடியான நேரங்களில் இதை முழுமையாகப் பயன்படுத்துங்கள்.")
    else:
        analysis.append("#### Bhava Chalit Analysis (The Nuance)")
        if sun_rasi_h != sun_bhava_h:
            analysis.append(f"Crucial Shift: Your Sun is in the {sun_rasi_h}th Sign (Psychology), but effectively works in the {sun_bhava_h}th House (Result).")
            if sun_bhava_h == 10: analysis.append("This is mathematically powerful: Even if the sign itself seems weak, the Sun is functionally delivering Career Authority (10th Bhava).")
            elif sun_bhava_h == 9: analysis.append("Your ultimate leadership style is less about direct 'Command' (10th) and much more about 'Mentorship & Vision' (9th).")
            elif sun_bhava_h == 11: analysis.append("Your career focus definitively shifts from pure 'Status' (10th) to maximizing 'Liquid Gains & Networking' (11th).")
        else: analysis.append(f"Direct Impact: Your Sun aligns perfectly in Sign and House ({sun_rasi_h}th). Your internal intent perfectly matches your external career results.")

        analysis.append("#### Mid-Life Strategy (Age 48+)")
        if sav_scores[9] > 28: analysis.append("Legacy Building: Your Career House is structurally strong. The next decade is purely about cementing your reputation. Do not switch fields; double down entirely on your established expertise.")
        else: analysis.append("Strategic Pivot: Your Career House requires support. Rely heavily on the 11th House (Network) or 9th House (Advisory) to maintain your status. Shift your role from 'Doing' to 'Guiding'.")

        analysis.append("#### The CEO Engine (Dasamsa D10)")
        d10_lord = RASI_RULERS[(d10_lagna + 9) % 12 or 12]
        role, traits = "General Management", "Leadership"
        if d10_lord == "Mars": role, traits = "Engineering, Operations, Real Estate", "Decisiveness"
        elif d10_lord == "Mercury": role, traits = "Data Science, Finance, Commerce", "Analysis"
        elif d10_lord == "Jupiter": role, traits = "Consulting, Advisory, Education", "Wisdom"
        elif d10_lord == "Venus": role, traits = "Creative Direction, Brand, Hospitality", "Diplomacy"
        elif d10_lord == "Saturn": role, traits = "Infrastructure, Logistics, Public Admin", "Discipline"
        elif d10_lord == "Sun": role, traits = "Government, CEO, Public Policy", "Governance"
        
        analysis.append(f"Archetype: {role}. Workplace Application: Your Dasamsa (D10) Lord is {d10_lord}. In meetings and decisions, rely on {traits}. This is your unique competitive advantage.")
    return analysis

# --- MODULE: FORECASTING & TRANSITS ---
def get_transit_positions(f_year):
    jd = swe.julday(f_year, 1, 1, 12.0)
    return {"Saturn": int(swe.calc_ut(jd, swe.SATURN, swe.FLG_SIDEREAL)[0][0] / 30) + 1, "Jupiter": int(swe.calc_ut(jd, swe.JUPITER, swe.FLG_SIDEREAL)[0][0] / 30) + 1, "Rahu": int(swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SIDEREAL)[0][0] / 30) + 1}

def generate_annual_forecast(moon_rasi, sav_scores, f_year, age, lang="English"):
    transits = get_transit_positions(f_year)
    sat_dist = (transits["Saturn"] - moon_rasi + 1) if (transits["Saturn"] - moon_rasi + 1) > 0 else (transits["Saturn"] - moon_rasi + 1) + 12
    jup_dist = (transits["Jupiter"] - moon_rasi + 1) if (transits["Jupiter"] - moon_rasi + 1) > 0 else (transits["Jupiter"] - moon_rasi + 1) + 12
    career_score = sav_scores[9]
    wealth_score = sav_scores[1]
    fc = {}
    
    if lang == "Tamil":
        if sat_dist in [3, 6, 11] and career_score > 28: fc['தொழில் (Career)'] = ("மிகப்பெரிய வளர்ச்சி நிலை. சனி பகவான் சாதகமான வீட்டில் உள்ளார், உங்கள் தொழில் ஸ்தானமும் மிகவும் வலுவாக உள்ளது. மிகப்பெரிய பதவி உயர்வும், எதிரிகளை வீழ்த்தும் வெற்றியும் தேடி வரும்.", "சனிக்கிழமைகளில் நல்லெண்ணெய் தீபம் ஏற்றவும்.")
        elif sat_dist in [3, 6, 11]: fc['தொழில் (Career)'] = ("நேர்மறையான வளர்ச்சி. உங்கள் கடின உழைப்பிற்கு ஏற்ற நல்ல பலன்கள் கிடைக்கும். உங்கள் வெற்றிகளை முறையாக ஆவணப்படுத்துங்கள்.", "சனிக்கிழமைகளில் நல்லெண்ணெய் தீபம் ஏற்றவும்.")
        elif sat_dist in [1, 2, 12]: fc['தொழில் (Career)'] = ("ஏழரைச் சனி காலம் (கவனம் தேவை). பணியிடத்தில் உங்களுக்கு உரிய அங்கீகாரம் கிடைக்காதது போல் தோன்றலாம். வேலையை அவசரமாக விட வேண்டாம். திறன்களை வளர்த்துக் கொள்ள இது சரியான நேரம்.", "தினமும் ஹனுமான் சாலிசா படிக்கவும்.")
        else: fc['தொழில் (Career)'] = ("சீரான நிலை. பெரிய ஏற்ற இறக்கங்கள் இருக்காது. நிலுவையில் உள்ள பணிகளை முடிக்கவும், உங்கள் வேலைகளை ஒழுங்கமைக்கவும் இது ஒரு சிறந்த ஆண்டு.", "பணியிடத்தை எப்போதும் சுத்தமாக வைத்திருக்கவும்.")

        if jup_dist in [2, 11] and wealth_score > 30: fc['பொருளாதாரம் (Wealth)'] = ("பிரமாண்டமான பணவரவு. குரு பகவான் உங்கள் தன ஸ்தானத்தை பார்ப்பதாலும், உங்கள் செல்வ ஸ்தானம் வலுவாக இருப்பதாலும், செய்யும் முதலீடுகள் மாபெரும் லாபத்தைத் தரும்.", "வியாழக்கிழமைகளில் மஞ்சள் நிற உணவுகளை (வாழைப்பழம்/பருப்பு) தானம் செய்யவும்.")
        elif jup_dist in [2, 11]: fc['பொருளாதாரம் (Wealth)'] = ("சிறந்த பணவரவு. தங்கம் அல்லது நிலம் வாங்க மிகவும் உகந்த காலம். பணப்புழக்கம் சரளமாக இருக்கும்.", "வியாழக்கிழமைகளில் மஞ்சள் நிற உணவுகளை தானம் செய்யவும்.")
        else: fc['பொருளாதாரம் (Wealth)'] = ("நிலையான வருமானம். அதிக ரிஸ்க் உள்ள முதலீடுகளைத் தவிர்க்கவும். செலவுகள் வருமானத்தை மீறாமல் பார்த்துக்கொள்ள சேமிப்பில் கவனம் செலுத்தவும்.", "பணப்பையில் ஒரு சிறிய விரலி மஞ்சள் துண்டை வைத்திருக்கவும்.")

        if sat_dist in [1, 7]: fc['உறவுகள் (Relationships)'] = ("சோதனைக் காலம். சனி பகவானால் கணவன்-மனைவி இடையே சிறு சிறு கருத்து வேறுபாடுகள் வரலாம். பொறுமையும் விட்டுக்கொடுத்தலும், தெளிவான பேச்சும் மிகவும் அவசியம்.", "வெள்ளிக்கிழமைகளில் ஓடும் நீரில் வெள்ளை மலர்களை விடவும்.")
        else: fc['உறவுகள் (Relationships)'] = ("மகிழ்ச்சியான சூழல். குடும்பத்தில் அமைதியும் குதூகலமும் நிலவும். குடும்பத்துடன் சுற்றுலா செல்லவும், உறவுகளை பலப்படுத்தவும் சிறந்த நேரம்.", "உங்கள் துணைக்கு இனிப்புகளைப் பரிசளிக்கவும்.")
        
        if age < 25: fc['இந்த ஆண்டின் முக்கிய நோக்கம்'] = ("கல்வி மற்றும் திறன் மேம்பாடு. புதிய கலைகளை கற்பதிலும், பட்டங்கள் பெறுவதிலும் முழு கவனத்தையும் செலுத்துங்கள்.", "சரஸ்வதி தேவியை வழிபடவும்.")
        elif 25 <= age < 55: fc['இந்த ஆண்டின் முக்கிய நோக்கம்'] = ("குடும்பம் மற்றும் சொத்து சேர்க்கை. சேமிப்பை உயர்த்துவதிலும், சொந்த வீடு வாங்குவதிலும் கவனம் தேவை.", "விநாயகப் பெருமானை வழிபடவும்.")
        else: fc['இந்த ஆண்டின் முக்கிய நோக்கம்'] = ("ஆரோக்கியம் மற்றும் ஆன்மீகம். உடல் நலனைப் பேணுவதிலும், ஆன்மீகப் பயணங்களிலும் முழு கவனம் செலுத்துங்கள்.", "சிவ பெருமானை வழிபடவும்.")
    else:
        if sat_dist in [3, 6, 11] and career_score > 28: fc['Career'] = ("EXCELLENT GROWTH PHASE (High Impact). Saturn is in a growth house AND your career chart strength is mathematically high. Expect a major promotion, structural elevation, or a breakthrough victory over competitors.", "Light a lamp with sesame oil on Saturdays.")
        elif sat_dist in [3, 6, 11]: fc['Career'] = ("POSITIVE GROWTH. You will see solid progress, but it requires more direct effort than usual because your base career strength is moderate. Keep pushing, and meticulously document your wins.", "Light a lamp with sesame oil.")
        elif sat_dist in [1, 2, 12]: fc['Career'] = ("SADE SATI PHASE (Caution). You may feel professionally undervalued or stuck. This is a crucial time to consolidate internal skills, not to job-hop recklessly. Avoid ego-clashes.", "Chant Hanuman Chalisa daily.")
        else: fc['Career'] = ("STEADY PROGRESS. There are no major highs or lows indicated. This is a highly productive year to clear pending projects and rigorously organize your workflow.", "Keep your workspace completely decluttered.")

        if jup_dist in [2, 11] and wealth_score > 30: fc['Wealth'] = ("WEALTH EXPLOSION. Jupiter blesses your income house AND your wealth score is exceptionally high. Investments made during this window will generate massive, structural returns in the long run.", "Donate yellow food (bananas/dal) on Thursdays.")
        elif jup_dist in [2, 11]: fc['Wealth'] = ("HIGH FINANCIAL INFLOW. Jupiter heavily blesses your income house. This is a highly favorable time to buy gold or secure land. Your general cash flow will be noticeably smooth.", "Donate yellow food on Thursdays.")
        else: fc['Wealth'] = ("STABLE INCOME. Strictly avoid high-risk speculation this year. Focus purely on savings rather than spending. Expenses may easily match income if you are not careful.", "Keep a small turmeric stick in your wallet.")

        if sat_dist in [1, 7]: fc['Rel'] = ("TESTING TIME. Saturn may bring coldness or structural distance in marriage. You must communicate with absolute clarity to avoid misunderstandings. Deep patience is required.", "Offer white flowers to flowing water on Fridays.")
        else: fc['Rel'] = ("HARMONIOUS. You have excellent structural support from family. This is a peaceful year for personal life, ideal for family vacations or deepening existing bonds.", "Gift something sweet to your partner.")
        
        if age < 25: fc['Focus'] = ("EDUCATION & SKILLS. Focus entirely on acquiring degrees and certifications. Your mind is highly receptive.", "Worship Saraswati.")
        elif 25 <= age < 55: fc['Focus'] = ("FAMILY & ASSETS. Focus your energy on building home equity, financial stability, and providing for dependents.", "Worship Ganesha.")
        else: fc['Focus'] = ("HEALTH & SPIRIT. Focus entirely on preventative physical health and deep spiritual retreats.", "Worship Shiva.")
    return fc

def get_next_transit_date(planet_id, current_rasi, start_date):
    search_date = start_date
    for _ in range(1200):
        search_date += timedelta(days=2)
        jd = swe.julday(search_date.year, search_date.month, search_date.day, 12.0)
        new_rasi = int(swe.calc_ut(jd, planet_id, swe.FLG_SIDEREAL)[0][0] / 30) + 1
        if new_rasi != current_rasi: return search_date.strftime("%d %b %Y"), new_rasi
    return "Long Term", current_rasi

def get_transit_data_advanced(f_year):
    jd = swe.julday(f_year, 1, 1, 12.0)
    current_date = datetime(f_year, 1, 1)
    data = {}
    for p_name, p_id in [("Saturn", swe.SATURN), ("Jupiter", swe.JUPITER), ("Rahu", swe.MEAN_NODE)]:
        curr_rasi = int(swe.calc_ut(jd, p_id, swe.FLG_SIDEREAL)[0][0] / 30) + 1
        next_date, next_sign_idx = get_next_transit_date(p_id, curr_rasi, current_date)
        data[p_name] = {"Rasi": curr_rasi, "NextDate": next_date, "NextSignIdx": next_sign_idx}
    return data

def get_micro_transits(f_year, p_lon_absolute, lang="English"):
    jd_start = swe.julday(f_year, 1, 1, 12.0)
    events = []
    tr_planets = {"Saturn": swe.SATURN, "Jupiter": swe.JUPITER, "Rahu": swe.MEAN_NODE}
    nat_planets = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Lagna"]
    active_conjunctions = {}

    for step in range(0, 365, 5): 
        jd = jd_start + step
        dt = swe.revjul(jd, swe.GREG_CAL)
        current_date = datetime(dt[0], dt[1], dt[2])
        for trp, tid in tr_planets.items():
            tr_lon = swe.calc_ut(jd, tid, swe.FLG_SIDEREAL)[0][0]
            for np in nat_planets:
                n_lon = p_lon_absolute.get(np, 0)
                diff = abs(tr_lon - n_lon)
                if diff > 180: diff = 360 - diff
                if diff <= 2.5: 
                    key = (trp, np)
                    if key not in active_conjunctions: active_conjunctions[key] = []
                    active_conjunctions[key].append(current_date)

    for (trp, np), dates in active_conjunctions.items():
        if not dates: continue
        start_d = min(dates).strftime("%d %b")
        end_d = max(dates).strftime("%d %b")
        date_txt = f"{start_d} to {end_d}" if start_d != end_d else f"Around {start_d}"
        
        meaning = ""
        if lang == "Tamil":
            t_trp, t_np = t_p.get(trp, trp), t_p.get(np, "லக்னம்")
            trigger_txt = f"கோச்சார {t_trp}, ஜனன {t_np} மீது இணைகிறது"
            if trp == "Saturn":
                if np == "Sun": meaning = "தொழில் மற்றும் அதிகாரத்தில் மன அழுத்தம் கூடும். மேலதிகாரிகளை அனுசரித்துச் செல்லவும்."
                elif np == "Moon": meaning = "ஏழரைச் சனியின் உச்சம். உணர்ச்சிகளைக் கட்டுப்படுத்தி, மன அமைதியை பேணுவது அவசியம்."
                elif np == "Mars": meaning = "வேகம் விவேகமல்ல. பயணங்களில் மிகவும் கவனம் தேவை. கோபத்தை தவிர்க்கவும்."
                elif np == "Mercury": meaning = "சிந்தனை ஒருமுகப்படும். கடினமான வேலைகளை முடிக்க சிறந்த நேரம்."
                elif np == "Jupiter": meaning = "வளர்ச்சிக்கும் கட்டுப்பாட்டிற்கும் இடையிலான போராட்டம். நிதியை கவனமாகக் கையாளவும்."
                elif np == "Venus": meaning = "உறவுகளில் உண்மை நிலை புரியும். ஆடம்பர செலவுகளைத் தவிர்க்கவும்."
                elif np == "Saturn": meaning = "சனி ஆவர்த்தனம். வாழ்க்கை முறையில் ஒரு மாபெரும் கட்டமைப்பு மாற்றம் நிகழும்."
                elif np == "Lagna": meaning = "உடல் சோர்வு ஏற்படும். உங்கள் பொறுப்புகள் பலமடங்கு அதிகரிக்கும்."
            elif trp == "Jupiter":
                if np == "Sun": meaning = "பதவி உயர்வு மற்றும் சமூகத்தில் மாபெரும் அந்தஸ்து கிடைக்கும்."
                elif np == "Moon": meaning = "மனதில் அமைதி நிலவும். குடும்பத்தில் சுபகாரியங்கள் நடைபெறும்."
                elif np == "Mars": meaning = "தைரியம் கூடும். புதிய முயற்சிகளைத் தொடங்க மிகச் சிறந்த தருணம்."
                elif np == "Mercury": meaning = "அறிவாற்றல் பெருகும். வியாபாரம் மற்றும் கல்வியில் மாபெரும் வெற்றி."
                elif np == "Jupiter": meaning = "குரு ஆவர்த்தனம். 12 வருடங்களுக்கு ஒருமுறை வரும் பொன்னான அதிர்ஷ்ட காலம்."
                elif np == "Venus": meaning = "பொருளாதார ஏற்றம் மற்றும் குடும்பத்தில் மகிழ்ச்சி பொங்கும் நேரம்."
                elif np == "Saturn": meaning = "நீண்டகாலமாக இருந்த தடைகள் நீங்கி, உங்கள் உழைப்பிற்கு ஏற்ற பலன் கிடைக்கும்."
                elif np == "Lagna": meaning = "தெய்வீக அருள் உங்களை பாதுகாக்கும். முகத்தில் தேஜஸ் அதிகரிக்கும்."
            elif trp == "Rahu":
                if np == "Sun": meaning = "அதிகாரம் மீதான ஆசை அதிகரிக்கும். மாயைகளில் சிக்க வேண்டாம்."
                elif np == "Moon": meaning = "மனதில் குழப்பங்கள் வரலாம். தியானம் செய்வது மிகவும் அவசியம்."
                elif np == "Mars": meaning = "கட்டுக்கடங்காத ஆற்றல் உருவாகும். விபத்துகள் குறித்து எச்சரிக்கை தேவை."
                elif np == "Mercury": meaning = "தொழில்நுட்ப அறிவில் ஈடுபாடு கூடும். ஏமாற்று வேலைகளில் கவனமாக இருக்கவும்."
                elif np == "Jupiter": meaning = "பாரம்பரிய விதிகளை மீறி வெற்றி பெற நினைப்பீர்கள். திடீர் பணவரவு உண்டு."
                elif np == "Venus": meaning = "ஆடம்பரம் மற்றும் சிற்றின்ப ஆசைகள் அதிகரிக்கும். கட்டுப்பாட்டுடன் இருக்கவும்."
                elif np == "Saturn": meaning = "வாழ்க்கை வேகமாக மாறும். சற்று மன அழுத்தம் இருந்தாலும் வெற்றி நிச்சயம்."
                elif np == "Lagna": meaning = "வாழ்க்கைப் பாதையை முற்றிலும் மாற்றிக்கொள்ளும் எண்ணம் மேலோங்கும்."
        else:
            trigger_txt = f"Transiting {trp} crosses Natal {np}"
            if trp == "Saturn":
                if np == "Sun": meaning = "Heavy pressure on career and ego. Yield to authority or carry heavy professional burdens."
                elif np == "Moon": meaning = "Peak Sade Sati energy. Emotional weight, reality checks, and forced maturity."
                elif np == "Mars": meaning = "Extreme frustration or blocked energy. Avoid physical risks or aggressive confrontations."
                elif np == "Mercury": meaning = "Serious mental focus. Great for heavy analytical work, but restrictive for lighthearted communication."
                elif np == "Jupiter": meaning = "A clash between growth and restriction. Financial structures must be solidified and secured."
                elif np == "Venus": meaning = "Relationships face a reality check. Frivolous spending is punished; commitment is strictly tested."
                elif np == "Saturn": meaning = "Saturn Return. A major milestone of completely rebuilding your life structure from the ground up."
                elif np == "Lagna": meaning = "Massive personal restructuring. High physical fatigue. You are stepping into a higher level of maturity."
            elif trp == "Jupiter":
                if np == "Sun": meaning = "Massive visibility and career grace. Promotions, favor from bosses, and leadership opportunities arise."
                elif np == "Moon": meaning = "Deep emotional healing. Auspicious events at home, property gains, or family expansion."
                elif np == "Mars": meaning = "A surge of confident energy. Excellent time to launch bold initiatives or legal actions."
                elif np == "Mercury": meaning = "Intellectual breakthroughs. High success in trade, writing, deals, and networking."
                elif np == "Jupiter": meaning = "Jupiter Return. A 12-year peak of luck, spiritual alignment, and financial opportunity."
                elif np == "Venus": meaning = "High romantic and financial luck. A period of luxury, celebrations, and ease in relationships."
                elif np == "Saturn": meaning = "Relief from long-standing burdens. Your hard work finally gets recognized and rewarded."
                elif np == "Lagna": meaning = "Physical and spiritual protection. A highly optimistic period where your personal aura shines."
            elif trp == "Rahu":
                if np == "Sun": meaning = "Sudden, almost obsessive desire for power. Beware of ego-traps or clashes with male authority."
                elif np == "Moon": meaning = "High emotional turbulence or anxiety. Unconventional desires. Guard your mental peace carefully."
                elif np == "Mars": meaning = "Explosive, unpredictable energy. Massive drive, but high risk of accidents or impulsive anger."
                elif np == "Mercury": meaning = "Obsessive thinking. Good for tech/coding, but beware of deceptive communications or scams."
                elif np == "Jupiter": meaning = "Breaking traditional rules for success. Financial windfalls through unorthodox means."
                elif np == "Venus": meaning = "Intense romantic or financial desires. Sudden infatuations or luxurious spending binges."
                elif np == "Saturn": meaning = "Karmic acceleration. Breaking old rules to build new structures. Stressful but highly productive."
                elif np == "Lagna": meaning = "A sudden urge to completely reinvent your physical appearance or life path. Restless energy."
        
        if meaning: events.append({"Trigger": trigger_txt, "Dates": date_txt, "Impact": meaning})
    return events

# --- MODULE: TIMING & DASHAS ---
def generate_mahadasha_table(moon_lon, birth_date, lang="English"):
    nak_idx = int(moon_lon / 13.333333333)
    bal = 1 - ((moon_lon % 13.333333333) / 13.333333333)
    curr_date = birth_date
    first_lord = DASHA_ORDER[nak_idx % 9]
    first_end = curr_date + timedelta(days=DASHA_YEARS[first_lord] * bal * 365.25)
    
    if lang == "Tamil":
        preds = {
            "Ketu": "பற்றுதலின்மை, சுயபரிசோதனை மற்றும் ஆன்மீக வளர்ச்சியின் காலம். மேலோட்டமான ஆசைகளில் இருந்து விலகி இருப்பீர்கள். உங்களை சரியான பாதையில் திருப்புவதற்காக சில திடீர் மாற்றங்கள் நிகழலாம்.",
            "Venus": "பொருளாதார வசதிகள், ஆடம்பரம் மற்றும் உறவுகளில் அதிக கவனம் செலுத்தும் காலம். கலை, வாகனங்கள் மற்றும் சொத்துகள் வாங்கும் யோகம் உண்டு. திருமண வாழ்க்கை சிறப்பாக இருக்கும்.",
            "Sun": "ஆளுமைத் திறன் மற்றும் அதிகார உச்சத்தின் காலம். சமுதாயத்தில் மிகப்பெரிய மதிப்பும், தலைமைப் பொறுப்பும் தேடி வரும். உங்களின் சுயமரியாதை ஓங்கி நிற்கும்.",
            "Moon": "உணர்ச்சிப்பூர்வமான பயணங்கள் மற்றும் மக்கள் தொடர்புகள் அதிகரிக்கும் காலம். குடும்பம் மற்றும் தாயார் மீது அதீத பாசம் ஏற்படும். நீர் சார்ந்த தொழில்கள் கை கொடுக்கும்.",
            "Mars": "கட்டுக்கடங்காத ஆற்றலும், துணிச்சலும் நிறைந்த காலம். எதிரிகளை வீழ்த்துவீர்கள். நிலம் வாங்குவதற்கும், தொழில்நுட்பத் துறையில் சாதிப்பதற்கும் மிகவும் உகந்த நேரம்.",
            "Rahu": "எப்படியாவது வெற்றி பெற வேண்டும் என்ற தீராத லட்சியம் தோன்றும் காலம். எதிர்பாராத திடீர் உயர்வுகள் ஏற்படும். வெளிநாட்டு பயணங்கள் மற்றும் தொடர்புகளால் பெரும் லாபம் உண்டு.",
            "Jupiter": "ஆழ்ந்த ஞானம், தெய்வீக அருள் மற்றும் பொருளாதார வளர்ச்சியின் காலம். சமூகத்தில் நல்ல மதிப்பும் மரியாதையும் கூடும். குடும்பம் செழிக்கும், செல்வம் பெருகும்.",
            "Saturn": "கடும் உழைப்பு, யதார்த்தமான சிந்தனை மற்றும் ஆழமான பாடங்களைக் கற்கும் காலம். மெதுவாக இருந்தாலும் உங்கள் வளர்ச்சி மிகவும் உறுதியானதாக இருக்கும்.",
            "Mercury": "கூர்மையான புத்திசாலித்தனம், வணிகம் மற்றும் வேகமான தகவல் தொடர்பின் காலம். வியாபாரம் தழைக்கும். புதிய விஷயங்களை மிக விரைவாகக் கற்றுக்கொண்டு சாதிப்பீர்கள்."
        }
    else:
        preds = {
            "Ketu": "A period of detachment, introspection, and spiritual growth. You may feel cut off from superficial material ambitions. Sudden breaks in career or relationships are highly possible, engineered specifically to redirect you towards your true path.",
            "Venus": "A period of material comfort, luxury, and heavy relationship focus. You will actively seek harmony and aesthetic pleasure. Significant career growth comes through networking, arts, or female figures.",
            "Sun": "A period of absolute authority, power, and identity formation. You actively seek recognition and leadership roles. Relations with the father or government entities become highly significant.",
            "Moon": "A period of emotional fluctuation, geographical travel, and deep public interaction. Your internal focus shifts to the home and mother figures. You gain significantly through public service or liquid industries.",
            "Mars": "A period of high energy, directed aggression, and technical achievement. You will aggressively conquer rivals and obstacles. This is an excellent period for engineering, sports, or acquiring real estate.",
            "Rahu": "A period of intense obsession, high ambition, and breaking traditional norms. You crave success at any absolute cost. Unexpected, sudden rises and falls will occur. Foreign travel or dealings with foreign cultures are highly favorable.",
            "Jupiter": "A period of deep wisdom, structural expansion, and divine grace. You gain immense respect through knowledge, teaching, or consulting. Wealth accumulates organically and steadily. Your family expands.",
            "Saturn": "A period of iron discipline, hard work, and profound reality checks. Growth is highly mathematically steady but slow. You will face heavy responsibilities. You learn deep patience and endurance.",
            "Mercury": "A period of sharp intellect, commerce, and rapid communication. The speed of life increases significantly. You learn new technical skills rapidly. Business and trade flourish. Meticulous networking brings immediate financial gains."
        }
    
    timeline = [{"Age (From-To)": f"0 - {int((first_end - birth_date).days/365.25)}", "Years": f"{curr_date.year} - {first_end.year}", "Mahadasha": t_p.get(first_lord, first_lord) if lang=="Tamil" else first_lord, "Prediction": preds.get(first_lord, "")}]
    curr_date = first_end
    for i in range(1, 9):
        lord = DASHA_ORDER[(nak_idx + i) % 9]
        end_date = curr_date + timedelta(days=DASHA_YEARS[lord] * 365.25)
        timeline.append({"Age (From-To)": f"{int((curr_date - birth_date).days/365.25)} - {int((end_date - birth_date).days/365.25)}", "Years": f"{curr_date.year} - {end_date.year}", "Mahadasha": t_p.get(lord, lord) if lang=="Tamil" else lord, "Prediction": preds.get(lord, "")})
        curr_date = end_date
    return timeline

def get_detailed_bhukti_analysis(md, ad, planet_bhava_map, lang="English"):
    md_house = planet_bhava_map.get(md, 1)
    ad_house = planet_bhava_map.get(ad, 1)
    
    if lang == "Tamil":
        remedy_deity = TAMIL_LIFESTYLE.get(ad, {}).get("Deity", "உங்கள் இஷ்ட தெய்வம்")
        remedy_action = TAMIL_LIFESTYLE.get(ad, {}).get("Action", "தர்ம காரியங்கள்")
        t_topics = {1: "சுய அடையாளம், உடல் ஆரோக்கியம் மற்றும் புதிய தொடக்கங்கள்", 2: "செல்வம், குடும்பம் மற்றும் வருமானப் பெருக்கம்", 3: "தைரியம், குறுகிய பயணங்கள் மற்றும் தகவல் தொடர்பு", 4: "வீடு, வாகனம், தாயார் மற்றும் மன அமைதி", 5: "குழந்தைகள், கலை, மற்றும் புத்திசாலித்தனம்", 6: "ஆரோக்கியம், கடன் தீர்வு மற்றும் எதிரிகளை வெல்லுதல்", 7: "திருமணம், கூட்டாண்மை மற்றும் சமுதாய உறவுகள்", 8: "திடீர் மாற்றங்கள், ரகசியங்கள் மற்றும் ஆழமான தேடல்", 9: "பாக்கியம், தந்தை, உயர் கல்வி மற்றும் ஆன்மீகம்", 10: "தொழில் வெற்றி, பதவி உயர்வு மற்றும் சமூக அந்தஸ்து", 11: "லாபம், நெட்வொர்க் மற்றும் ஆசைகள் நிறைவேறுதல்", 12: "பயணங்கள், முதலீடுகள், செலவுகள் மற்றும் ஆன்மீக தேடல்"}
        t_md, t_ad = t_p.get(md, md), t_p.get(ad, ad)
        
        base = f"இந்த காலகட்டம் {t_md} தசையின் (நீண்டகால இலக்கு) ஒட்டுமொத்த நோக்கங்களை, {t_ad} புக்தியின் (உடனடி செயல்கள்) மூலமாக நிஜ வாழ்க்கையில் பிரதிபலிக்கும்.\n\n"
        if md == ad: base += f"உங்கள் ஜாதகத்தில் {t_md} {md_house}-ஆம் வீட்டில் அமர்ந்துள்ளதால், இந்த காலகட்டம் முற்றிலும் '{t_topics[md_house]}' என்பதை சுற்றியே அமையும். இது ஒரு தசா சந்தி (அதிகபட்ச தாக்கம்) என்பதால் இதன் சக்தி வீரியமாக இருக்கும்.\n\n"
        else: base += f"உங்கள் ஜாதகத்தில் {t_md} {md_house}-ஆம் வீட்டில் அமர்ந்துள்ளதால் நீண்டகால இலக்குகள் அதைச் சார்ந்திருக்கும். ஆனால் தற்போது {t_ad} புக்தி நடப்பதால், உங்கள் அன்றாட நிகழ்வுகள் மற்றும் பலன்கள் நேரடியாக '{t_topics[ad_house]}' வழியே நடைபெறும்.\n\n"

        base += "முக்கிய கணிப்புகள்:\n"
        base += f"- உங்களின் முழு கவனமும் '{t_topics[ad_house].split(',')[0]}' மீது திரும்பும்.\n"

        if ad in ["Saturn", "Mars", "Rahu", "Ketu", "Sun"]: base += "எச்சரிக்கை: இது இயற்கையாகவே சற்று தீவிரமான கிரகத்தின் காலம் என்பதால், கோபத்தையும் அவசர முடிவுகளையும் கட்டாயம் தவிர்க்க வேண்டும். ஆவணங்களில் கையெழுத்திடும் முன் கவனமாகப் படிக்கவும்.\n"
        else: base += "எச்சரிக்கை: இது ஒரு சாதகமான காலம் என்றாலும், சோம்பேறித்தனத்தை தவிர்த்து தொடர்ந்து உழைப்பது அவசியம். உங்கள் தினசரி கட்டுப்பாடுகளைத் தளர்த்த வேண்டாம்.\n"
        base += f"பரிகாரம்: இந்தக் காலத்தை சிறப்பாக்க {remedy_action.lower()} செய்யவும். மேலும், தினசரி {remedy_deity} ஐ மனதார வழிபடவும்."
    else:
        remedy_deity = lifestyle_guidance.get(ad, {}).get("Deity", "your personal deity")
        remedy_action = lifestyle_guidance.get(ad, {}).get("Action", "charitable acts")
        topics = {1: "personal identity, physical vitality, and major life directions", 2: "wealth accumulation, family dynamics, and financial planning", 3: "courage, self-effort, short travels, and communication", 4: "domestic peace, real estate, mother, and inner emotional foundations", 5: "creativity, children, speculative investments, and intellect", 6: "health routines, resolving debts, and overcoming competitors", 7: "marriage, business partnerships, and public dealings", 8: "deep transformation, hidden knowledge, unexpected events, and shared finances", 9: "luck, higher learning, long-distance travel, and mentorship", 10: "career advancement, public status, and professional authority", 11: "network expansion, large gains, and the fulfillment of long-term desires", 12: "spiritual retreats, foreign connections, high expenditures, and letting go"}
        base = f"This phase brings the overarching agenda of {md} (Strategy) into physical reality through the specific execution of {ad} (Tactics).\n\n"
        if md == ad: base += f"Because {md} is placed in your {md_house}th House, this period is intensely, heavily focused. The absolute center of your life right now revolves around {topics[md_house]}. This is a 'Dasha Sandhi' (peak intensification) where the planetary energy is completely undiluted.\n\n"
        else: base += f"In your specific chart, {md} sits in the {md_house}th House, making your long-term, background focus center on {topics[md_house]}. However, {ad} is currently activating your {ad_house}th House. This means your immediate, day-to-day events, actions, and results will manifest specifically through {topics[ad_house]}.\n\n"

        base += "Key Predictions:\n"
        base += f"- Core focus shifts heavily toward {topics[ad_house].split(',')[0]}.\n"

        if ad in ["Saturn", "Mars", "Rahu", "Ketu", "Sun"]: base += "Precautions: This sub-period is ruled by a naturally intense, aggressive planet. You must actively avoid impulsive decisions, practice extreme patience, and do not force outcomes prematurely. Verify all legal documents carefully.\n"
        else: base += "Precautions: While this is a generally supportive and gentle energy, do not become intellectually or physically complacent. Avoid over-indulgence and heavily maintain your daily discipline.\n"
        base += f"Actionable Pariharam: To optimize this specific {ad} period, focus heavily on {remedy_action.lower()}. Regularly worship or silently meditate upon {remedy_deity}."
    return base

def generate_current_next_bhukti(moon_lon, birth_date, planet_bhava_map, lang="English"):
    current_date = datetime.now()
    nak_idx = int(moon_lon / 13.333333333)
    bal = 1 - ((moon_lon % 13.333333333) / 13.333333333)
    curr_md_start = birth_date
    md_idx = nak_idx % 9
    
    for _ in range(20):
        md_lord = DASHA_ORDER[md_idx % 9]
        md_dur = DASHA_YEARS[md_lord] * bal if curr_md_start == birth_date else DASHA_YEARS[md_lord]
        md_end = curr_md_start + timedelta(days=md_dur * 365.25)
        
        if curr_md_start <= current_date <= md_end:
            ad_start = curr_md_start
            ad_idx = DASHA_ORDER.index(md_lord)
            for i in range(9):
                ad_lord = DASHA_ORDER[(ad_idx + i) % 9]
                ad_dur = (DASHA_YEARS[md_lord] * DASHA_YEARS[ad_lord]) / 120
                ad_end = ad_start + timedelta(days=ad_dur * 365.25)
                
                if ad_start <= current_date <= ad_end:
                    pd_start = ad_start
                    pd_idx = DASHA_ORDER.index(ad_lord)
                    for j in range(9):
                        pd_lord = DASHA_ORDER[(pd_idx + j) % 9]
                        pd_dur = (ad_dur * DASHA_YEARS[pd_lord]) / 120
                        pd_end = pd_start + timedelta(days=pd_dur * 365.25)
                        if pd_start <= current_date <= pd_end:
                            t_md, t_ad, t_pd = (t_p.get(md_lord, md_lord), t_p.get(ad_lord, ad_lord), t_p.get(pd_lord, pd_lord)) if lang=="Tamil" else (md_lord, ad_lord, pd_lord)
                            
                            active_pd = {"MD": t_md, "AD": t_ad, "PD": t_pd, "Start": pd_start.strftime('%d %b %Y'), "End": pd_end.strftime('%d %b %Y')}
                            
                            lbl_curr = "நடப்பு புக்தி" if lang == "Tamil" else "CURRENT PHASE"
                            lbl_next = "அடுத்த புக்தி" if lang == "Tamil" else "NEXT PHASE"
                            
                            p1 = {"Type": lbl_curr, "Phase": f"{t_md} - {t_ad}", "Dates": f"{ad_start.strftime('%b %Y')} to {ad_end.strftime('%b %Y')}", "Text": get_detailed_bhukti_analysis(md_lord, ad_lord, planet_bhava_map, lang)}
                            
                            next_ad = DASHA_ORDER[(ad_idx + i + 1) % 9]
                            t_next_ad = t_p.get(next_ad, next_ad) if lang=="Tamil" else next_ad
                            p2 = {"Type": lbl_next, "Phase": f"{t_md} - {t_next_ad}", "Dates": "விரைவில்..." if lang=="Tamil" else "Upcoming", "Text": get_detailed_bhukti_analysis(md_lord, next_ad, planet_bhava_map, lang)}
                            
                            return [p1, p2], active_pd
                        pd_start = pd_end
                ad_start = ad_end
        curr_md_start = md_end
        md_idx += 1
        bal = 1

# ==========================================
# 4. HTML VISUAL GENERATORS (For Streamlit UI)
# ==========================================
def get_south_indian_chart_html(p_pos, lagna_rasi, title, lang="English"):
    g = {i: [] for i in range(1, 13)}
    g[lagna_rasi].append("<span style='color:#e74c3c; font-size:12px;'><b>Asc</b></span>")
    for p, r in p_pos.items():
        name = TAMIL_NAMES.get(p, p[:2]) if lang == "Tamil" else p[:2]
        g[r].append(f"<span style='font-size:12px; font-weight:bold; color:#2c3e50;'>{name}</span>")
    for i in g: g[i] = "<br>".join(g[i])
    z = ZODIAC_TA if lang == "Tamil" else ZODIAC
    # Create a helper to safely get the zodiac name by index (1-12)
    def get_z(idx):
        if isinstance(z, dict): return z.get(idx, "")
        return z[idx] if idx < len(z) else ""
        
    return f"<div style='max-width: 450px; margin: auto; font-family: sans-serif;'><table style='width: 100%; border-collapse: collapse; text-align: center; font-size: 14px; background-color: #ffffff; border: 2px solid #333;'><tr><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(12)} (12)</div>{g[12]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(1)} (1)</div>{g[1]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(2)} (2)</div>{g[2]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(3)} (3)</div>{g[3]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(11)} (11)</div>{g[11]}</td><td colspan='2' rowspan='2' style='border: none; vertical-align: middle; font-weight: bold; font-size: 16px; color:#2c3e50; background-color: #ffffff;'>{title}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(4)} (4)</div>{g[4]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(10)} (10)</div>{g[10]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(5)} (5)</div>{g[5]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(9)} (9)</div>{g[9]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(8)} (8)</div>{g[8]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(7)} (7)</div>{g[7]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{get_z(6)} (6)</div>{g[6]}</td></tr></table></div>"

# ==========================================
# 5. ROBUST HTML EXPORT ENGINE (FLAWLESS BILINGUAL REPORT)
# ==========================================
def generate_html_report(name_in, p_pos, p_d9, lagna_rasi, sav_scores, career_txt, edu_txt, health_txt, love_txt, id_data, lagna_str, moon_str, star_str, yogas, fc, micro_transits, mahadasha_data, phases, pd_info, guide, transit_texts, lang="English"):
    
    def format_section(text_list):
        out = ""
        for line in text_list:
            if line.startswith("#### "): out += f"<h4>{line.replace('#### ', '')}</h4>"
            else: out += f"<p>{line}</p>"
        return out

    h_title = f"ஜோதிட அறிக்கை: {name_in}" if lang == "Tamil" else f"Vedic Astrology Premium Report: {name_in}"
    l_lbl = "லக்னம்" if lang == "Tamil" else "Lagna"
    m_lbl = "ராசி" if lang == "Tamil" else "Moon"
    s_lbl = "நட்சத்திரம்" if lang == "Tamil" else "Star"

    chart1 = get_south_indian_chart_html(p_pos, lagna_rasi, "ராசி சக்கரம்" if lang == "Tamil" else "Rasi Chart", lang)
    d9_lagna_idx = get_navamsa_chart(p_pos.get("Lagna", lagna_rasi*30))
    chart2 = get_south_indian_chart_html(p_d9, d9_lagna_idx, "நவாம்சம்" if lang == "Tamil" else "Navamsa", lang)

    score_html = "<table class='bar-chart'>"
    for i in range(12):
        house_num = i + 1
        score = sav_scores[(lagna_rasi - 1 + i) % 12]
        bar_w = int((score / 45) * 100)
        color_class = "high" if score >= 30 else "low" if score < 25 else ""
        lbl = "பாவம்" if lang == "Tamil" else "H"
        score_html += f"<tr><td width='15%'><b>{lbl} {house_num}</b></td><td width='75%'><div class='bar {color_class}' style='width: {bar_w}%;'></div></td><td width='10%'><b>{score}</b></td></tr>"
    score_html += "</table>"

    z_names = ZODIAC_TA if lang == "Tamil" else ZODIAC
    def get_z(idx):
        if isinstance(z_names, dict): return z_names.get(idx, "")
        return z_names[idx] if idx < len(z_names) else ""

    l_str = get_z(lagna_rasi)
    m_str = get_z(moon_rasi)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>{h_title}</title>
    <style>
        body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6; padding: 40px; max-width: 900px; margin: auto; }}
        h1 {{ text-align: center; color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px; font-size: 28px; }}
        h2 {{ color: #2980b9; margin-top: 40px; border-bottom: 1px solid #eee; padding-bottom: 5px; font-size: 22px; page-break-after: avoid; }}
        h4 {{ color: #2c3e50; margin-bottom: 5px; font-size: 16px; margin-top: 20px; }}
        p {{ margin-top: 5px; text-align: justify; font-size: 15px; color: #444; }}
        .subtitle {{ text-align: center; font-style: italic; color: #7f8c8d; margin-bottom: 40px; font-size: 16px; }}
        
        .bar-chart {{ width: 100%; border-collapse: collapse; margin-top: 20px; page-break-inside: avoid; font-size: 15px; }}
        .bar-chart td {{ padding: 8px 0; vertical-align: middle; border-bottom: 1px dashed #eee; }}
        .bar {{ background-color: #95a5a6; height: 22px; border-radius: 4px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.1); }}
        .bar.high {{ background-color: #27ae60; }}
        .bar.low {{ background-color: #e74c3c; }}
        
        .page-break {{ page-break-before: always; margin-top: 40px; }}
        .footer {{ text-align: center; font-size: 13px; color: #95a5a6; margin-top: 60px; border-top: 1px solid #eee; padding-top: 20px; }}
        
        table.timeline {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; page-break-inside: auto; }}
        table.timeline th, table.timeline td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; vertical-align: top; }}
        table.timeline tr:nth-child(even) {{ background-color: #fcfcfc; }}
        table.timeline th {{ background-color: #f0f3f4; font-weight: bold; color: #2c3e50; }}
        
        .remedy-box {{ background-color: #fdfae6; border-left: 4px solid #f1c40f; padding: 15px; margin-top: 20px; border-radius: 0 4px 4px 0; }}
        .remedy-box ul {{ margin: 0; padding-left: 20px; font-size: 15px; }}
        .remedy-box li {{ margin-bottom: 8px; }}
        
        @media print {{
            body {{ padding: 0; max-width: 100%; }}
            .page-break {{ page-break-before: always; }}
            * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
            h2 {{ margin-top: 20px; }}
        }}
    </style>
    </head>
    <body>
        <h1>{h_title}</h1>
        <div class="subtitle"><b>{l_lbl}:</b> {l_str} &nbsp;|&nbsp; <b>{m_lbl}:</b> {m_str} &nbsp;|&nbsp; <b>{s_lbl}:</b> {star_str}</div>

        <h2>{"1. சுயவிவரம் (Identity)" if lang == "Tamil" else "1. Identity & Personality"}</h2>
        <p><b>{"நோக்கம்" if lang=="Tamil" else "Purpose"}:</b> {id_data['Purpose']}</p>
        <p><b>{"குணம்" if lang=="Tamil" else "Personality"}:</b> {id_data['Personality']}</p>
        <p><b>{"பலங்கள்" if lang=="Tamil" else "Strengths"}:</b> {id_data['Strengths']}</p>
        <p><b>{"பலவீனங்கள்" if lang=="Tamil" else "Weaknesses"}:</b> {id_data['Weaknesses']}</p>

        <h2>{"2. ராசி சக்கரம் (Rasi Chakra)" if lang == "Tamil" else "2. Birth Chart (Rasi Chakra)"}</h2>
        {chart1}

        <h2>{"3. அஷ்டகவர்க்கம் (Destiny Radar)" if lang == "Tamil" else "3. Destiny Radar (Scorecard)"}</h2>
        {score_html}

        <div class="page-break"></div>

        <h2>{"4. கல்வி மற்றும் தொழில் (Work & Intellect)" if lang == "Tamil" else "4. Work & Intellect"}</h2>
        {format_section(edu_txt)}
        <hr style="border: 0; border-top: 1px dashed #ccc; margin: 20px 0;">
        {format_section(career_txt)}

        <h2>{"5. திருமணம் (Love & Marriage)" if lang == "Tamil" else "5. Love & Marriage"}</h2>
        <div style="margin-bottom: 20px;">{chart2}</div>
        {format_section(love_txt)}

        <h2>{"6. ஆரோக்கியம் (Health & Vitality)" if lang == "Tamil" else "6. Health & Vitality"}</h2>
        {format_section(health_txt)}

        <div class="page-break"></div>

        <h2>{"7. யோகங்கள் (Wealth & Power Combinations)" if lang == "Tamil" else "7. Wealth & Power Yogas"}</h2>
    """
    
    for y in yogas: html += f"<h4>{y['Name']} ({y['Type']})</h4><p>{y['Description']}</p>"

    html += f"<h2>{'8. வருடாந்திர கணிப்பு (Annual Forecast)' if lang == 'Tamil' else '8. Annual Forecast'}</h2>"
    pred_lbl = "கணிப்பு" if lang == "Tamil" else "Prediction"
    rem_lbl = "பரிகாரம்" if lang == "Tamil" else "Remedy"
    for cat, data in fc.items(): html += f"<h4>{cat}</h4><p><b>{pred_lbl}:</b> {data[0]}<br><span style='color:#e67e22;'><b>{rem_lbl}:</b> {data[1]}</span></p>"

    html += f"<h2>{'9. கிரகப் பெயர்ச்சிகள் (Planetary Transits)' if lang == 'Tamil' else '9. Planetary Transits'}</h2>"
    for txt in transit_texts: html += f"<p>{txt.replace(chr(10), '<br>')}</p>"

    if micro_transits:
        html += f"<h4>{'நுண்ணிய கிரகப் பெயர்ச்சிகள் (Micro-Transits)' if lang == 'Tamil' else 'Micro-Transits'}</h4><ul>"
        for m in micro_transits: html += f"<li style='margin-bottom: 8px;'><b style='color:#c0392b;'>{m['Dates']}:</b> {m['Trigger']}<br>{m['Impact']}</li>"
        html += "</ul>"

    age_lbl = "வயது" if lang == "Tamil" else "Age"
    yr_lbl = "ஆண்டுகள்" if lang == "Tamil" else "Years"
    md_lbl = "மகா தசை" if lang == "Tamil" else "Mahadasha"
    
    html += f"""
        <div class="page-break"></div>
        <h2>{"10. தசா புக்தி (Strategic Roadmap)" if lang == "Tamil" else "10. Strategic Roadmap"}</h2>
        <table class="timeline">
            <tr><th width="15%">{age_lbl}</th><th width="15%">{yr_lbl}</th><th width="15%">{md_lbl}</th><th width="55%">{pred_lbl}</th></tr>
    """
    for row in mahadasha_data:
        html += f"<tr><td>{row['Age (From-To)']}</td><td>{row['Years']}</td><td><b>{row['Mahadasha']}</b></td><td>{row['Prediction']}</td></tr>"
    html += "</table>"

    html += f"<h2>{'11. நடப்பு தசா (Phase Drill-Down)' if lang == 'Tamil' else '11. Phase Drill-Down'}</h2>"
    if pd_info: 
        lbl_focus = "முக்கிய கவனம்" if lang == "Tamil" else "IMMEDIATE FOCUS"
        lbl_dates = "காலம்" if lang == "Tamil" else "Active Dates"
        lbl_ruler = "நடப்பு அதிபதி" if lang == "Tamil" else "Current Micro-Ruler"
        html += f"<h4>{lbl_focus}</h4><p><b>{lbl_dates}:</b> {pd_info['Start']} to {pd_info['End']}<br><b>{lbl_ruler}:</b> {pd_info['PD']} (Operating under {pd_info['MD']} / {pd_info['AD']})</p><hr style='border:0; border-top:1px solid #eee;'>"
    
    for p in phases: html += f"<h4>{p['Type']}: {p['Phase']} ({p['Dates']})</h4><p>{p['Text'].replace(chr(10), '<br>')}</p>"

    html += f"<h2>{'12. பரிகாரங்கள் (Lucky Lifestyle)' if lang == 'Tamil' else '12. Lucky Lifestyle'}</h2>"
    
    d_lbl = "தெய்வம்" if lang == "Tamil" else "Deity"
    m_lbl = "மந்திரம்" if lang == "Tamil" else "Mantra"
    h_lbl = "பழக்கவழக்கம்" if lang == "Tamil" else "Daily Habit"
    b_lbl = "பலன்" if lang == "Tamil" else "Benefit"
    a_lbl = "பொருட்கள்" if lang == "Tamil" else "Accessories"
    av_lbl = "தவிர்க்க வேண்டியவை" if lang == "Tamil" else "Avoid"
    
    html += f"<div class='remedy-box'><ul><li><b>{d_lbl}:</b> {guide.get('Deity', '')}</li><li><b>{m_lbl}:</b> {guide.get('Mantra', '')}</li><li><b>{h_lbl}:</b> {guide.get('Daily', '')}</li><li><b>{b_lbl}:</b> {guide.get('Benefit', '')}</li><li><b>{a_lbl}:</b> {guide.get('Accessory', '')}</li><li><b>{av_lbl}:</b> {guide.get('Avoid', '')}</li></ul></div>"

    html += f"<div class='footer'>{'வேத ஜோதிட என்ஜின் மூலம் உருவாக்கப்பட்டது' if lang == 'Tamil' else 'Generated by Vedic Astro Engine (Platinum Edition)'}</div>"
    html += "</body></html>"
    
    return html.encode('utf-8')

# ==========================================
# 6. STREAMLIT APP UI & EXECUTION
# ==========================================

if 'report_generated' not in st.session_state: st.session_state.report_generated = False
if 'messages' not in st.session_state: st.session_state.messages = []

with st.sidebar:
    LANG = st.radio("Language / மொழி", ["English", "Tamil"])
    st.header("Birth Details")
    name_in = st.text_input("Name", "Padmanabhan")
    dob_in = st.date_input("Date of Birth", datetime(1977, 11, 14))
    tob_in = st.time_input("Time of Birth", datetime.now().replace(hour=1, minute=45))
    loc_query = st.text_input("City", "Saidapet, Chennai")
    
    f_year = st.number_input("Forecast Year", 2024, 2050, 2026)
    
    lat_val, lon_val, tz_val = 13.08, 80.27, "Asia/Kolkata"
    if loc_query:
        results = get_location_search(loc_query)
        if results:
            addr_list = [format_address(l.address) for l in results]
            selection = st.selectbox("Select exact location:", list(dict.fromkeys(addr_list)))
            chosen = results[addr_list.index(selection)]
            tf = TimezoneFinder()
            tz_val = tf.timezone_at(lng=chosen.longitude, lat=chosen.latitude)
            lat_val, lon_val = chosen.latitude, chosen.longitude
            
    if st.button("Generate Report"):
        st.session_state.report_generated = True
        st.session_state.messages = []

if st.session_state.report_generated:
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    birth_dt = datetime.combine(dob_in, tob_in)
    offset = get_utc_offset(tz_val, birth_dt)
    ut_hour = (tob_in.hour + (tob_in.minute/60.0)) - offset
    jd_ut = swe.julday(dob_in.year, dob_in.month, dob_in.day, ut_hour)
    
    bhava_cusps = get_bhava_chalit(jd_ut, lat_val, lon_val)
    ascmc = swe.houses_ex(jd_ut, lat_val, lon_val, b'P', swe.FLG_SIDEREAL)[1]
    lagna_rasi = int(ascmc[0]/30)+1
    d9_lagna = get_navamsa_chart(ascmc[0])
    d10_lagna = get_dasamsa_chart(ascmc[0])
    
    moon_res = swe.calc_ut(jd_ut, swe.MOON, swe.FLG_SIDEREAL)[0]
    moon_rasi = int(moon_res[0]/30)+1
    current_age = datetime.now().year - dob_in.year
    
    ketu_lon = (swe.calc_ut(jd_ut, swe.MEAN_NODE, swe.FLG_SIDEREAL)[0][0] + 180) % 360
    ketu_bhava_h = determine_house(ketu_lon, bhava_cusps)

    planets = {"Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE}
    p_pos, p_d9, p_d10, p_lon_absolute, bhava_placements = {}, {}, {}, {}, {}
    master_table = []
    
    for p, pid in planets.items():
        res = swe.calc_ut(jd_ut, pid, swe.FLG_SIDEREAL)[0]
        p_lon_absolute[p] = res[0]
        r1 = int(res[0]/30)+1
        p_pos[p] = r1
        p_d9[p] = get_navamsa_chart(res[0])
        p_d10[p] = get_dasamsa_chart(res[0])
        bhava_h = determine_house(res[0], bhava_cusps)
        bhava_placements[p] = bhava_h 
        h = (r1 - lagna_rasi + 1) if (r1 - lagna_rasi + 1) > 0 else (r1 - lagna_rasi + 1) + 12
        dig = get_dignity(p, r1)
        status = "Avg"
        if r1 == p_d9[p]: status = "VARGOTTAMA"
        elif dig == "Exalted": status = "ROYAL"
        elif dig == "Neecha": status = "WEAK"
        master_table.append({"Planet": p, "Rasi": ZODIAC_TA[r1] if LANG=="Tamil" else ZODIAC[r1], "House": h, "Bhava": bhava_h, "Dignity": dig, "Status": status})

    p_pos["Lagna"] = lagna_rasi
    bhava_placements["Ketu"] = ketu_bhava_h 
    sav_scores = calculate_sav_score(p_pos, lagna_rasi)
    nak, lord = get_nakshatra_details(moon_res[0])
    
    yogas = scan_yogas(p_pos, lagna_rasi, lang=LANG)
    career_txt = analyze_career_professional(p_pos, d10_lagna, lagna_rasi, sav_scores, bhava_placements, lang=LANG)
    edu_txt = analyze_education(p_pos, lagna_rasi, lang=LANG)
    health_txt = analyze_health(p_pos, lagna_rasi, lang=LANG)
    love_txt = analyze_love_marriage(lagna_rasi, d9_lagna, p_d9, p_pos, lang=LANG)
    fc = generate_annual_forecast(moon_rasi, sav_scores, f_year, current_age, lang=LANG)
    
    t_data = get_transit_data_advanced(f_year)
    sat_h = (t_data['Saturn']['Rasi'] - moon_rasi + 1) if (t_data['Saturn']['Rasi'] - moon_rasi + 1) > 0 else (t_data['Saturn']['Rasi'] - moon_rasi + 1) + 12
    if LANG == "Tamil":
        sat_txt = f"தற்போதைய நிலை: {ZODIAC_TA[t_data['Saturn']['Rasi']]} லிருந்து {ZODIAC_TA[t_data['Saturn']['NextSignIdx']]} க்கு {t_data['Saturn']['NextDate']} அன்று பெயர்ச்சி.\nவிளைவு: {sat_h}-ஆம் வீட்டில் சஞ்சரிப்பது குறிப்பிட்ட கர்ம பலன்களைத் தரும்."
        jup_txt = f"தற்போதைய நிலை: {ZODIAC_TA[t_data['Jupiter']['Rasi']]} லிருந்து {ZODIAC_TA[t_data['Jupiter']['NextSignIdx']]} க்கு {t_data['Jupiter']['NextDate']} அன்று பெயர்ச்சி.\nவிளைவு: செல்வம் மற்றும் ஞானம் அதிகரிக்கும்."
        rahu_txt = f"தற்போதைய அச்சு: ராகு {ZODIAC_TA[t_data['Rahu']['Rasi']]} / கேது {ZODIAC_TA[(t_data['Rahu']['Rasi']+6-1)%12+1]}\nவிளைவு: ராகு ஆசையை உருவாக்குவார், கேது பற்றின்மையை உருவாக்குவார்."
    else:
        sat_txt = f"Moving From: {ZODIAC[t_data['Saturn']['Rasi']]} to {ZODIAC[t_data['Saturn']['NextSignIdx']]} on {t_data['Saturn']['NextDate']}\nPsychology: You may feel a heavy weight of responsibility or a need to isolate.\nOutcome: Transiting the {sat_h}th House indicates specific karmic results."
        jup_txt = f"Moving From: {ZODIAC[t_data['Jupiter']['Rasi']]} to {ZODIAC[t_data['Jupiter']['NextSignIdx']]} on {t_data['Jupiter']['NextDate']}\nPsychology: Optimism returns. You feel supported by invisible hands.\nOutcome: Growth in wealth and wisdom."
        rahu_txt = f"Current Axis: Rahu in {ZODIAC[t_data['Rahu']['Rasi']]} / Ketu in {ZODIAC[(t_data['Rahu']['Rasi']+6-1)%12+1]}\nPsychology: Rahu creates obsession where it sits, while Ketu creates detachment."
    transit_texts = [sat_txt, jup_txt, rahu_txt]
    
    micro_transits = get_micro_transits(f_year, p_lon_absolute, lang=LANG)
    mahadasha_data = generate_mahadasha_table(moon_res[0], datetime.combine(dob_in, tob_in), lang=LANG)
    phases, pd_info = generate_current_next_bhukti(moon_res[0], datetime.combine(dob_in, tob_in), bhava_placements, lang=LANG)
    
    # DATABASE SELECTION
    db_id = TAMIL_IDENTITY_DB if LANG == "Tamil" else identity_db
    db_lev = TAMIL_LEVERAGE_GUIDE if LANG == "Tamil" else house_leverage_guide
    db_eff = TAMIL_EFFORT_GUIDE if LANG == "Tamil" else house_effort_guide
    db_life = TAMIL_LIFESTYLE if LANG == "Tamil" else lifestyle_guidance
    guide = db_life.get(RASI_RULERS[moon_rasi], db_life.get("Moon", {}))

    c_left, c_right = st.columns([3, 1])
    with c_left:
        st.subheader(f"Analysis for {name_in}" if LANG=="English" else f"ஜோதிட அறிக்கை: {name_in}")
        l_name = ZODIAC_TA[lagna_rasi] if LANG == "Tamil" else ZODIAC[lagna_rasi]
        m_name = ZODIAC_TA[moon_rasi] if LANG == "Tamil" else ZODIAC[moon_rasi]
        st.markdown(f"> **{'லக்னம்' if LANG=='Tamil' else 'Lagna'}:** {l_name} | **{'ராசி' if LANG=='Tamil' else 'Moon'}:** {m_name} | **{'நட்சத்திரம்' if LANG=='Tamil' else 'Star'}:** {nak}")
    
    with c_right:
        report_id_data = db_id.get(ZODIAC[lagna_rasi], list(db_id.values())[0])
        html_bytes = generate_html_report(name_in, p_pos, p_d9, lagna_rasi, sav_scores, career_txt, edu_txt, health_txt, love_txt, report_id_data, ZODIAC[lagna_rasi], ZODIAC[moon_rasi], nak, yogas, fc, micro_transits, mahadasha_data, phases, pd_info, guide, transit_texts, lang=LANG)
        st.download_button(label="📄 Download Full HTML Report", data=html_bytes, file_name=f"{name_in}_Astro_Report.html", mime="text/html")

    tb_lbls = ["Profile", "Scorecard", "Work & Intellect", "Love & Health", "Yogas", "Forecast", "Roadmap", "💬 AI Oracle"] if LANG == "English" else ["சுயவிவரம்", "அஷ்டகவர்க்கம்", "கல்வி & தொழில்", "திருமணம் & ஆரோக்கியம்", "யோகங்கள்", "ஆண்டு பலன்கள்", "தசா புக்தி", "💬 AI ஜோதிடர்"]
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(tb_lbls)

    with t1:
        st.subheader("Identity" if LANG == "English" else "சுயவிவரம்")
        user_id = report_id_data
        st.markdown(f"**{'நோக்கம்' if LANG=='Tamil' else 'Purpose'}:** {user_id['Purpose']}")
        st.markdown(f"**{'குணம்' if LANG=='Tamil' else 'Personality'}:** {user_id['Personality']}")
        c1, c2 = st.columns(2)
        with c1: st.markdown(f"#### {'பலங்கள்' if LANG=='Tamil' else 'Strengths'}"); st.markdown(user_id['Strengths'])
        with c2: st.markdown(f"#### {'பலவீனங்கள்' if LANG=='Tamil' else 'Weaknesses'}"); st.markdown(user_id['Weaknesses'])
        st.divider()
        st.markdown(f"<h3 style='text-align: center;'>{'ராசி சக்கரம்' if LANG=='Tamil' else 'Birth Chart (Rasi)'}</h3>", unsafe_allow_html=True)
        st.markdown(get_south_indian_chart_html(p_pos, lagna_rasi, "ராசி சக்கரம்" if LANG=="Tamil" else "Rasi Chart", LANG), unsafe_allow_html=True)
        st.markdown(f"<h4 style='text-align: center; margin-top: 30px;'>{'கிரக நிலைகள்' if LANG=='Tamil' else 'Planetary Details'}</h4>", unsafe_allow_html=True)
        
        headers = ["கிரகம்", "ராசி", "பாவம்", "பலம்", "நிலை"] if LANG == "Tamil" else ["Planet", "Rasi", "House", "Dignity", "Status"]
        table_md = f"<table style='width: 80%; margin: 20px auto; border-collapse: collapse; font-family: sans-serif; font-size: 15px; text-align: center;'><tr style='background-color: #f8f9fa; border-bottom: 2px solid #ccc;'><th style='padding: 12px 8px;'>{headers[0]}</th><th style='padding: 12px 8px;'>{headers[1]}</th><th style='padding: 12px 8px;'>{headers[2]}</th><th style='padding: 12px 8px;'>{headers[3]}</th><th style='padding: 12px 8px;'>{headers[4]}</th></tr>"
        for row in master_table:
            p_name = TAMIL_NAMES.get(row['Planet'], row['Planet']) if LANG == "Tamil" else row['Planet']
            table_md += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 12px 8px;'><b>{p_name}</b></td><td style='padding: 12px 8px;'>{row['Rasi']}</td><td style='padding: 12px 8px;'>{row['House']}</td><td style='padding: 12px 8px;'>{row['Dignity']}</td><td style='padding: 12px 8px;'>{row['Status']}</td></tr>"
        table_md += "</table>"
        st.markdown(table_md, unsafe_allow_html=True)

    with t2:
        st.subheader("Destiny Radar" if LANG == "English" else "அஷ்டகவர்க்கம் (Destiny Radar)")
        p_lbl = "பாவம்" if LANG == "Tamil" else "H"
        cats_labels = [f"{p_lbl} {i+1}" for i in range(12)]
        vals = [sav_scores[(lagna_rasi-1+i)%12] for i in range(12)]
        text_colors = ['#27ae60' if v >= 30 else '#e74c3c' if v < 25 else '#333333' for v in vals]
        fig_bar = go.Figure(data=[go.Bar(x=vals, y=cats_labels, orientation='h', marker_color='#bdc3c7', text=[f"<b>{v}</b>" for v in vals], textposition='outside', textfont=dict(color=text_colors, size=14))])
        fig_bar.add_vline(x=28, line_width=2, line_dash="dash", line_color="#7f8c8d", annotation_text="Average (28)" if LANG=="English" else "சராசரி (28)", annotation_position="top right")
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=20, r=20, t=40, b=20), height=400)
        st.plotly_chart(fig_bar, use_container_width=True)
        c1, c2 = st.columns(2)
        sorted_houses = sorted([(sav_scores[(lagna_rasi-1+i)%12], i+1) for i in range(12)], key=lambda x: x[0], reverse=True)
        with c1:
            st.markdown(f"<h4 style='color: #27ae60; margin-bottom: 0px;'>{'அதிக பலம் பெற்ற பாவங்கள்' if LANG=='Tamil' else 'Power Zones'}</h4>", unsafe_allow_html=True)
            for s, h in sorted_houses[:3]: st.markdown(f"**{p_lbl} {h} - {s} Points:**\n{db_lev[h]}")
        with c2:
            st.markdown(f"<h4 style='color: #e74c3c; margin-bottom: 0px;'>{'கவனம் தேவைப்படும் பாவங்கள்' if LANG=='Tamil' else 'Challenge Zones'}</h4>", unsafe_allow_html=True)
            for s, h in sorted_houses[-3:]: st.markdown(f"**{p_lbl} {h} - {s} Points:**\n{db_eff[h]}")

    with t3:
        st.subheader("Education & Intellect" if LANG == "English" else "கல்வி மற்றும் அறிவு")
        for line in edu_txt: st.markdown(line)
        st.divider()
        st.subheader("The CEO Engine (Career)" if LANG == "English" else "தொழில் மற்றும் வெற்றி வியூகம்")
        for line in career_txt: st.markdown(line)

    with t4:
        st.markdown(f"<h3 style='text-align: center;'>{'நவாம்ச சக்கரம் (Navamsa)' if LANG=='Tamil' else 'Destiny Chart (Navamsa)'}</h3>", unsafe_allow_html=True)
        st.markdown(get_south_indian_chart_html(p_d9, d9_lagna, "நவாம்சம்" if LANG=="Tamil" else "Navamsa", LANG), unsafe_allow_html=True)
        st.divider()
        st.subheader("Love & Marriage" if LANG == "English" else "காதல் மற்றும் திருமணம்")
        for line in love_txt: st.markdown(line)
        st.divider()
        st.subheader("Health & Vitality" if LANG == "English" else "ஆரோக்கியம்")
        for line in health_txt: st.markdown(line)

    with t5:
        st.subheader("Wealth & Power Yogas" if LANG == "English" else "முக்கிய யோகங்கள்")
        for y in yogas:
            st.markdown(f"#### {y['Name']}")
            st.markdown(f"> **{'Focus' if LANG=='English' else 'பலன்'}:** {y['Type']}")
            st.markdown(y['Description'])

    with t6:
        st.subheader(f"Annual Forecast {f_year}" if LANG == "English" else f"{f_year} ஆண்டு பலன்கள்")
        c1, c2 = st.columns(2)
        keys = list(fc.keys())
        with c1:
            st.markdown(f"#### {keys[0]}")
            st.markdown(fc[keys[0]][0])
            st.markdown(f"> **{'Remedy' if LANG=='English' else 'பரிகாரம்'}:** {fc[keys[0]][1]}")
        with c2:
            st.markdown(f"#### {keys[1]}")
            st.markdown(fc[keys[1]][0])
            st.markdown(f"> **{'Remedy' if LANG=='English' else 'பரிகாரம்'}:** {fc[keys[1]][1]}")
        c3, c4 = st.columns(2)
        with c3:
            st.markdown(f"#### {keys[2]}")
            st.markdown(fc[keys[2]][0])
            st.markdown(f"> **{'Remedy' if LANG=='English' else 'பரிகாரம்'}:** {fc[keys[2]][1]}")
        with c4:
            st.markdown(f"#### {keys[3]}")
            st.markdown(fc[keys[3]][0])
            st.markdown(f"> **{'Remedy' if LANG=='English' else 'பரிகாரம்'}:** {fc[keys[3]][1]}")
        st.divider()
        st.subheader("Planetary Transits" if LANG == "English" else "கிரகப் பெயர்ச்சிகள்")
        for txt in transit_texts: st.markdown(txt.replace('\n', '  \n'))
        if micro_transits:
            st.markdown(f"#### {'Micro-Transits' if LANG == 'English' else 'நுண்ணிய பெயர்ச்சிகள்'}")
            for mt in micro_transits:
                st.markdown(f"**{mt['Dates']}**: {mt['Trigger']}")
                st.markdown(mt['Impact'])

    with t7:
        st.subheader("Strategic Roadmap" if LANG == "English" else "தசா புக்தி அறிக்கை")
        if pd_info:
            st.markdown(f"#### {'IMMEDIATE FOCUS' if LANG=='English' else 'நடப்பு தசா புக்தி'}")
            st.markdown(f"**{pd_info['Start']} to {pd_info['End']}**: {pd_info['PD']} ({pd_info['MD']} / {pd_info['AD']})")
            st.divider()
        for p in phases:
            st.markdown(f"**{p['Type']}: {p['Phase']}**")
            st.markdown(f"> {p['Dates']}")
            st.markdown(p['Text'].replace('\n', '  \n'))
            st.divider()

        st.markdown(f"#### {'Life Chapters' if LANG=='English' else 'மகா தசை விவரங்கள்'}")
        planet_colors = {"Sun": "#d35400", "Moon": "#95a5a6", "Mars": "#c0392b", "Mercury": "#27ae60", "Jupiter": "#f39c12", "Venus": "#8e44ad", "Saturn": "#2c3e50", "Rahu": "#34495e", "Ketu": "#7f8c8d", "சூரியன்": "#d35400", "சந்திரன்": "#95a5a6", "செவ்வாய்": "#c0392b", "புதன்": "#27ae60", "குரு": "#f39c12", "சுக்கிரன்": "#8e44ad", "சனி": "#2c3e50", "ராகு": "#34495e", "கேது": "#7f8c8d"}
        dasha_names = []
        start_years = []
        durations = []
        for row in mahadasha_data:
            dasha_names.append(row['Mahadasha'])
            s_year = int(row['Years'].split(' - ')[0])
            e_year = int(row['Years'].split(' - ')[1])
            start_years.append(s_year)
            durations.append(e_year - s_year)
        fig_timeline = go.Figure()
        fig_timeline.add_trace(go.Bar(
            y=['']*len(dasha_names), x=durations, base=start_years, name="Mahadashas", orientation='h',
            text=dasha_names, textposition='inside', textangle=0, insidetextfont=dict(color='white', size=12),
            marker=dict(color=[planet_colors.get(d, '#333') for d in dasha_names])
        ))
        fig_timeline.update_layout(barmode='stack', height=100, margin=dict(l=0, r=0, t=10, b=0), template='plotly_white', showlegend=False, xaxis=dict(title=None, showticklabels=True), yaxis=dict(showticklabels=False, fixedrange=True))
        st.plotly_chart(fig_timeline, use_container_width=True)

    with t8:
        st.subheader("💬 Ask the AI Astrologer" if LANG == "English" else "💬 AI ஜோதிடரிடம் கேளுங்கள்")
        st.info("I am an AI trained on your exact astrological coordinates. We can chat back and forth!" if LANG == "English" else "உங்கள் பிறந்த ஜாதகத்தை நான் முழுமையாகப் படித்துவிட்டேன். உங்களுக்குத் தேவையான கேள்விகளைக் கேட்கலாம்.")

        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt_input := st.chat_input("Ask a question... / உங்கள் கேள்வியைக் கேளுங்கள்..."):
            if not GEMINI_API_KEY:
                st.error("API Key missing! Please add your key to api_config.py")
            else:
                st.session_state.messages.append({"role": "user", "content": prompt_input})
                with chat_container:
                    with st.chat_message("user"): st.markdown(prompt_input)
                    with st.chat_message("assistant"):
                        with st.spinner("Analyzing..." if LANG=="English" else "கணிக்கப்படுகிறது..."):
                            try:
                                genai.configure(api_key=GEMINI_API_KEY)
                                chart_context = f"User is Ascendant {ZODIAC[lagna_rasi]} and Moon {ZODIAC[moon_rasi]}. "
                                chart_context += f"Planetary positions: {p_pos}. "
                                if pd_info: chart_context += f"Current Dasha Phase: {pd_info['MD']} Mahadasha, {pd_info['AD']} Antardasha. "
                                chart_context += f"House strengths out of 40: {dict(zip(range(1,13), vals))}. "
                                chart_context += f"CRITICAL CONTEXT: Target forecast year is {f_year}. "
                                chart_context += f"For {f_year}, major transits are: Saturn in {ZODIAC[t_data['Saturn']['Rasi']]}, Jupiter in {ZODIAC[t_data['Jupiter']['Rasi']]}, Rahu in {ZODIAC[t_data['Rahu']['Rasi']]}. "
                                
                                sys_lang = "natural, poetic, and traditional Tamil script (like a wise Nadi astrologer)" if LANG == "Tamil" else "English"
                                persona = "You are a wise, highly accurate, and compassionate Vedic Astrologer. "
                                rules = f"Answer the user's question practically in 3 to 4 sentences based on the data. CRITICAL: You are fully bilingual. If the user asks for Tamil, or if the interface language is set to Tamil, you MUST output your ENTIRE response in Tamil script. Never apologize or say you can only speak English. Default Language for this response: {sys_lang}. Always conclude with a practical remedy."
                                
                                conversation_history = "Chat History:\n"
                                for msg in st.session_state.messages[:-1]: 
                                    role = "User" if msg["role"] == "user" else "Astrologer"
                                    conversation_history += f"{role}: {msg['content']}\n"
                                
                                full_prompt = f"{persona} {rules}\n\nAstrological Data: {chart_context}\n\n{conversation_history}\nUser: {prompt_input}\nAstrologer:"
                                
                                try:
                                    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                                    target_model = None
                                    if 'models/gemini-1.5-flash' in available_models: target_model = 'models/gemini-1.5-flash'
                                    elif 'models/gemini-1.0-pro' in available_models: target_model = 'models/gemini-1.0-pro'
                                    elif len(available_models) > 0: target_model = available_models[0]
                                    
                                    if target_model:
                                        model = genai.GenerativeModel(target_model)
                                        response = model.generate_content(full_prompt)
                                        st.markdown(response.text)
                                        st.session_state.messages.append({"role": "assistant", "content": response.text})
                                    else:
                                        st.error("Your Google API key does not have access to text-generation models.")
                                except:
                                    model = genai.GenerativeModel('gemini-1.5-flash-latest')
                                    response = model.generate_content(full_prompt)
                                    st.markdown(response.text)
                                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                                    
                            except Exception as e:
                                st.error(f"AI Generation Failed. Error details: {e}")
                st.rerun()

        if st.session_state.messages:
            st.write("")
            if st.button("🗑️ Clear Chat History" if LANG=="English" else "🗑️ உரையாடலை அழி"):
                st.session_state.messages = []
                st.rerun()
