import streamlit as st
import swisseph as swe
from datetime import datetime, timedelta
import plotly.graph_objects as go
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
import pytz
from fpdf import FPDF
import google.generativeai as genai
import os

# Safely import the API key from your config file
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
# 3. DEEP ANALYSIS ENGINES
# ==========================================
def scan_yogas(p_pos, lagna_rasi):
    yogas = []
    p_houses = {p: ((r - lagna_rasi + 1) if (r - lagna_rasi + 1) > 0 else (r - lagna_rasi + 1) + 12) for p, r in p_pos.items() if p != "Lagna"}
    
    if p_pos.get("Sun") == p_pos.get("Mercury"):
        yogas.append({"Name": "Budhaditya Yoga", "Type": "Intellect & Commerce", "Description": f"The Sun and Mercury are structurally conjunct in your {p_houses.get('Sun')}th House. This forms a highly analytical and brilliant business mind. You combine the executive authority of the Sun with the tactical communication of Mercury, indicating strong wealth potential through advisory, technology, trade, or writing."})
    
    if "Jupiter" in p_pos and "Moon" in p_pos:
        jup_from_moon = (p_pos["Jupiter"] - p_pos["Moon"] + 1) if (p_pos["Jupiter"] - p_pos["Moon"] + 1) > 0 else (p_pos["Jupiter"] - p_pos["Moon"] + 1) + 12
        if jup_from_moon in [1, 4, 7, 10]:
            yogas.append({"Name": "Gajakesari Yoga", "Type": "Fame & Institutional Protection", "Description": "Jupiter is placed in a foundational angle from your Natal Moon. This is an elite combination for earning widespread respect and divine protection. It grants a noble reputation, social comfort, and the unique ability to defeat competitors through wisdom and diplomacy rather than brute force."})
    
    pm_planets = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa", "Venus": "Malavya", "Saturn": "Sasa"}
    for p, y_name in pm_planets.items():
        if p in p_houses and p_houses[p] in [1, 4, 7, 10] and get_dignity(p, p_pos[p]) in ["Own", "Exalted"]:
            yogas.append({"Name": f"{y_name} Mahapurusha Yoga", "Type": "Exceptional Domain Authority", "Description": f"{p} is exceptionally strong in a foundational angle ({p_houses[p]}th House). You are mathematically destined to be a recognized authority in the domain ruled by {p}. This grants immense psychological resilience and elevates your status significantly."})
    
    lord_9 = RASI_RULERS[(lagna_rasi + 8) % 12 or 12]
    lord_10 = RASI_RULERS[(lagna_rasi + 9) % 12 or 12]
    if p_pos.get(lord_9) == p_pos.get(lord_10) and lord_9 != lord_10:
        yogas.append({"Name": "Dharma Karmadhipati Yoga", "Type": "Ultimate Career Destiny", "Description": f"The rulers of your 9th House of Luck and 10th House of Career are united. This represents the highest form of professional Raja Yoga. Your internal life purpose and your external profession are seamlessly aligned."})
    
    if not yogas:
        yogas.append({"Name": "Independent Karma Yoga", "Type": "Self-Made Destiny", "Description": "Your chart does not rely on passive, inherited yogas. Instead, your success is generated purely through active free-will and executing the specific strategies highlighted in your House Scorecard."})
    
    return yogas

def analyze_education(p_pos, lagna_rasi):
    analysis = []
    lord_5 = RASI_RULERS[(lagna_rasi + 4) % 12 or 12]
    mercury_dig = get_dignity("Mercury", p_pos["Mercury"])
    
    analysis.append("#### Academic Profile & Learning Style")
    analysis.append(f"Your primary intellect and academic capacity are governed by the 5th House lord, {lord_5}. This indicates that you learn best when the subject matter naturally aligns with {lord_5}'s energy.")
    if mercury_dig in ["Exalted", "Own"]: analysis.append(f"Because Mercury (the planet of logic) is highly dignified ({mercury_dig}), your capacity to process complex data is elite. You excel in technical, analytical, or heavily communicative fields.")
    elif mercury_dig == "Neecha": analysis.append("Your Mercury is mathematically debilitated, which actually means you possess highly intuitive, abstract intelligence rather than strict rote-memorization skills.")
    else: analysis.append("Your logical processing is balanced. You can apply yourself to a wide variety of subjects successfully, provided you maintain academic discipline.")
    
    analysis.append("#### Strategic Application")
    if lord_5 == "Mars": analysis.append("Apply your knowledge through immediate, hands-on execution. Your primary improvement opportunity is patience.")
    elif lord_5 == "Venus": analysis.append("Apply your knowledge by making systems more harmonious or aesthetically pleasing.")
    elif lord_5 == "Mercury": analysis.append("Apply your learnings by teaching, writing, or building analytical frameworks.")
    elif lord_5 == "Jupiter": analysis.append("Apply your wisdom in advisory, mentorship, or policy-making roles.")
    elif lord_5 == "Saturn": analysis.append("Apply your knowledge to build long-lasting, highly structured systems.")
    elif lord_5 == "Sun": analysis.append("Apply your intellect to take on absolute leadership and public authority roles.")
    elif lord_5 == "Moon": analysis.append("Apply your learnings to emotionally intelligent leadership, HR, or healing.")
    return analysis

def analyze_health(p_pos, lagna_rasi):
    analysis = []
    lagna_lord = RASI_RULERS[lagna_rasi]
    ll_dig = get_dignity(lagna_lord, p_pos[lagna_lord])
    lord_6 = RASI_RULERS[(lagna_rasi + 5) % 12 or 12]
    
    analysis.append("#### Core Physical Resilience")
    if ll_dig in ["Exalted", "Own"]: analysis.append(f"Your Ascendant Lord ({lagna_lord}) is exceptionally strong. This grants you a highly robust physical constitution and excellent natural immunity.")
    elif ll_dig == "Neecha": analysis.append(f"Your Ascendant Lord ({lagna_lord}) is weak by sign placement. Your physical energy is finite and must be carefully managed.")
    else: analysis.append(f"Your Ascendant Lord ({lagna_lord}) is in a neutral state. Your physical resilience is average. It will directly reflect your lifestyle choices.")
    
    analysis.append("#### Vulnerabilities & Preventative Care")
    if lord_6 == "Mars": analysis.append("Watch for inflammation, heat-related issues, blood pressure spikes, and physical accidents.")
    elif lord_6 == "Venus": analysis.append("Watch for issues related to sugar intake, kidneys, and hormonal imbalances.")
    elif lord_6 == "Mercury": analysis.append("Watch for nervous system exhaustion, anxiety, and digestive/gut issues.")
    elif lord_6 == "Jupiter": analysis.append("Watch for issues related to liver function, weight gain, and cholesterol.")
    elif lord_6 == "Saturn": analysis.append("Watch for bone density issues, joint stiffness, arthritis, and chronic, slow-moving ailments.")
    elif lord_6 == "Sun": analysis.append("Watch for heart health, eyesight deterioration, and upper back/spine issues.")
    elif lord_6 == "Moon": analysis.append("Watch for water retention, chest/lung congestion, and heavily psychosomatic illnesses.")
    return analysis

def analyze_love_marriage(d1_lagna, d9_lagna, p_d9, p_d1):
    analysis = []
    lord_5 = RASI_RULERS[(d1_lagna + 4) % 12 or 12]
    d9_7th_lord = RASI_RULERS[(d9_lagna + 6) % 12 or 12]
    
    analysis.append("#### The Dating Phase vs. The Marriage Phase")
    analysis.append(f"Your approach to early romance (5th House) is governed by {lord_5}, meaning you initially seek partners who align with {lord_5}'s energy.")
    analysis.append(f"The 7th House of your Navamsa (D9) reveals your ultimate spousal archetype. To achieve a permanently successful marriage, your partner must fundamentally embody {d9_7th_lord}'s mature traits.")
    
    analysis.append("#### Venus Strength")
    venus_dig = get_dignity("Venus", p_d9['Venus'])
    if venus_dig in ["Exalted", "Own"] or p_d1['Venus'] == p_d9['Venus']: analysis.append("Exceptional. Your capacity to give and receive love matures beautifully over time.")
    elif venus_dig == "Neecha": analysis.append("Requires active effort. You must consciously work on not being overly critical in intimate relationships.")
    else: analysis.append("Balanced. Your relationships require standard daily maintenance, mutual respect, and active listening to thrive.")
        
    vargottama = [p for p in p_d1.keys() if p != "Lagna" and p in p_d9 and p_d1[p] == p_d9[p]]
    if vargottama:
        v_str = ", ".join(vargottama)
        analysis.append(f"#### Vargottama Strengths\nPlanets in the exact same sign in D1 and D9 are tremendously powerful. You have {v_str} as Vargottama. These act as unshakeable structural pillars in your life.")
    return analysis

def analyze_career_professional(p_pos, d10_lagna, lagna_rasi, sav_scores, bhava_placements):
    analysis = []
    analysis.append("#### Bhava Chalit Analysis (The Nuance)")
    sun_rasi_h = (p_pos['Sun'] - lagna_rasi + 1) if (p_pos['Sun'] - lagna_rasi + 1) > 0 else (p_pos['Sun'] - lagna_rasi + 1) + 12
    sun_bhava_h = bhava_placements['Sun'] 
    
    if sun_rasi_h != sun_bhava_h:
        analysis.append(f"Crucial Shift: Your Sun is in the {sun_rasi_h}th Sign (Psychology), but effectively works in the {sun_bhava_h}th House (Result).")
    else: analysis.append(f"Direct Impact: Your Sun aligns perfectly in Sign and House ({sun_rasi_h}th). Your internal intent matches your external career results.")

    analysis.append("#### Mid-Life Strategy (Age 48+)")
    if sav_scores[9] > 28: analysis.append("Legacy Building: Your Career House is structurally strong. Double down entirely on your established expertise.")
    else: analysis.append("Strategic Pivot: Your Career House requires support. Rely heavily on the 11th House (Network) or 9th House (Advisory) to maintain your status.")

    analysis.append("#### The CEO Engine (Dasamsa D10)")
    d10_lord = RASI_RULERS[(d10_lagna + 9) % 12 or 12]
    role, traits = "General Management", "Leadership"
    if d10_lord == "Mars": role, traits = "Engineering, Operations, Real Estate", "Decisiveness"
    elif d10_lord == "Mercury": role, traits = "Data Science, Finance, Commerce", "Analysis"
    elif d10_lord == "Jupiter": role, traits = "Consulting, Advisory, Education", "Wisdom"
    elif d10_lord == "Venus": role, traits = "Creative Direction, Brand, Hospitality", "Diplomacy"
    elif d10_lord == "Saturn": role, traits = "Infrastructure, Logistics, Public Admin", "Discipline"
    elif d10_lord == "Sun": role, traits = "Government, CEO, Public Policy", "Governance"
    
    analysis.append(f"Archetype: {role}. Workplace Application: Your Dasamsa Lord is {d10_lord}. In meetings and decisions, rely on {traits}.")
    return analysis

# --- MODULE: FORECASTING & TRANSITS ---
def get_transit_positions(f_year):
    jd = swe.julday(f_year, 1, 1, 12.0)
    return {"Saturn": int(swe.calc_ut(jd, swe.SATURN, swe.FLG_SIDEREAL)[0][0] / 30) + 1, "Jupiter": int(swe.calc_ut(jd, swe.JUPITER, swe.FLG_SIDEREAL)[0][0] / 30) + 1, "Rahu": int(swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SIDEREAL)[0][0] / 30) + 1}

def generate_annual_forecast(moon_rasi, sav_scores, f_year, age):
    transits = get_transit_positions(f_year)
    sat_dist = (transits["Saturn"] - moon_rasi + 1) if (transits["Saturn"] - moon_rasi + 1) > 0 else (transits["Saturn"] - moon_rasi + 1) + 12
    jup_dist = (transits["Jupiter"] - moon_rasi + 1) if (transits["Jupiter"] - moon_rasi + 1) > 0 else (transits["Jupiter"] - moon_rasi + 1) + 12
    career_score = sav_scores[9]
    wealth_score = sav_scores[1]
    fc = {}
    
    if sat_dist in [3, 6, 11] and career_score > 28: fc['Career'] = ("EXCELLENT GROWTH PHASE (High Impact). Saturn is in a growth house AND your career chart strength is mathematically high. Expect a major promotion.", "Light a lamp with sesame oil on Saturdays.")
    elif sat_dist in [3, 6, 11]: fc['Career'] = ("POSITIVE GROWTH. You will see solid progress, but it requires more direct effort than usual. Keep pushing.", "Light a lamp with sesame oil.")
    elif sat_dist in [1, 2, 12]: fc['Career'] = ("SADE SATI PHASE (Caution). You may feel professionally undervalued or stuck. Consolidate internal skills.", "Chant Hanuman Chalisa daily.")
    else: fc['Career'] = ("STEADY PROGRESS. There are no major highs or lows indicated. This is a highly productive year to clear pending projects.", "Keep your workspace completely decluttered.")

    if jup_dist in [2, 11] and wealth_score > 30: fc['Wealth'] = ("WEALTH EXPLOSION. Jupiter blesses your income house AND your wealth score is exceptionally high. Investments made during this window will generate massive returns.", "Donate yellow food (bananas/dal) on Thursdays.")
    elif jup_dist in [2, 11]: fc['Wealth'] = ("HIGH FINANCIAL INFLOW. Jupiter heavily blesses your income house. Favorable time to buy gold or secure land.", "Donate yellow food on Thursdays.")
    else: fc['Wealth'] = ("STABLE INCOME. Strictly avoid high-risk speculation this year. Focus purely on savings.", "Keep a small turmeric stick in your wallet.")

    if sat_dist in [1, 7]: fc['Rel'] = ("TESTING TIME. Saturn may bring coldness or distance in marriage. Deep patience is required.", "Offer white flowers to flowing water on Fridays.")
    else: fc['Rel'] = ("HARMONIOUS. Excellent structural support from family. A peaceful year for personal life.", "Gift something sweet to your partner.")
    
    if age < 25: fc['Focus'] = ("EDUCATION & SKILLS. Focus entirely on acquiring degrees and certifications.", "Worship Saraswati.")
    elif 25 <= age < 55: fc['Focus'] = ("FAMILY & ASSETS. Focus your energy on building home equity and financial stability.", "Worship Ganesha.")
    else: fc['Focus'] = ("HEALTH & SPIRIT. Focus entirely on preventative physical health and deep spiritual retreats.", "Worship Shiva.")
    return fc

def get_next_transit_date(planet_id, current_rasi, start_date):
    search_date = start_date
    for _ in range(1200):
        search_date += timedelta(days=2)
        jd = swe.julday(search_date.year, search_date.month, search_date.day, 12.0)
        new_rasi = int(swe.calc_ut(jd, planet_id, swe.FLG_SIDEREAL)[0][0] / 30) + 1
        if new_rasi != current_rasi: return search_date.strftime("%d %b %Y"), ZODIAC[new_rasi]
    return "Long Term", ZODIAC[current_rasi]

def get_transit_data_advanced(f_year):
    jd = swe.julday(f_year, 1, 1, 12.0)
    current_date = datetime(f_year, 1, 1)
    data = {}
    for p_name, p_id in [("Saturn", swe.SATURN), ("Jupiter", swe.JUPITER), ("Rahu", swe.MEAN_NODE)]:
        curr_rasi = int(swe.calc_ut(jd, p_id, swe.FLG_SIDEREAL)[0][0] / 30) + 1
        next_date, next_sign = get_next_transit_date(p_id, curr_rasi, current_date)
        data[p_name] = {"Rasi": curr_rasi, "NextDate": next_date, "NextSign": next_sign}
    return data

def get_micro_transits(f_year, p_lon_absolute):
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
        if trp == "Saturn":
            if np == "Sun": meaning = "Heavy pressure on career and ego. Yield to authority."
            elif np == "Moon": meaning = "Peak Sade Sati energy. Emotional weight and forced maturity."
            elif np == "Mars": meaning = "Extreme frustration or blocked energy. Avoid physical risks."
            elif np == "Mercury": meaning = "Serious mental focus. Great for heavy analytical work."
            elif np == "Jupiter": meaning = "A clash between growth and restriction. Solidify finances."
            elif np == "Venus": meaning = "Relationships face a reality check. Commitment is strictly tested."
            elif np == "Saturn": meaning = "Saturn Return. A major milestone of rebuilding your life structure."
            elif np == "Lagna": meaning = "Massive personal restructuring. High physical fatigue."
        elif trp == "Jupiter":
            if np == "Sun": meaning = "Massive visibility and career grace. Promotions arise."
            elif np == "Moon": meaning = "Deep emotional healing. Auspicious events at home."
            elif np == "Mars": meaning = "A surge of confident energy. Excellent time to launch initiatives."
            elif np == "Mercury": meaning = "Intellectual breakthroughs. High success in trade and networking."
            elif np == "Jupiter": meaning = "Jupiter Return. A 12-year peak of luck and financial opportunity."
            elif np == "Venus": meaning = "High romantic and financial luck. Luxury and ease."
            elif np == "Saturn": meaning = "Relief from long-standing burdens. Hard work gets rewarded."
            elif np == "Lagna": meaning = "Physical and spiritual protection. A highly optimistic period."
        elif trp == "Rahu":
            if np == "Sun": meaning = "Sudden desire for power. Beware of ego-traps."
            elif np == "Moon": meaning = "High emotional turbulence. Guard your mental peace carefully."
            elif np == "Mars": meaning = "Explosive, unpredictable energy. Massive drive, but high risk of accidents."
            elif np == "Mercury": meaning = "Obsessive thinking. Beware of deceptive communications."
            elif np == "Jupiter": meaning = "Breaking traditional rules for success. Financial windfalls."
            elif np == "Venus": meaning = "Intense romantic or financial desires. Sudden infatuations."
            elif np == "Saturn": meaning = "Karmic acceleration. Breaking old rules to build new structures."
            elif np == "Lagna": meaning = "A sudden urge to completely reinvent your physical appearance."
        if meaning: events.append({"Trigger": f"Transiting {trp} crosses Natal {np}", "Dates": date_txt, "Impact": meaning})
    return events

# --- MODULE: TIMING & DASHAS ---
def generate_mahadasha_table(moon_lon, birth_date):
    nak_idx = int(moon_lon / 13.333333333)
    bal = 1 - ((moon_lon % 13.333333333) / 13.333333333)
    curr_date = birth_date
    first_lord = DASHA_ORDER[nak_idx % 9]
    first_end = curr_date + timedelta(days=DASHA_YEARS[first_lord] * bal * 365.25)
    
    preds = {
        "Ketu": "A period of detachment, introspection, and spiritual growth. You may feel cut off from superficial material ambitions.",
        "Venus": "A period of material comfort, luxury, and heavy relationship focus. Significant career growth comes through networking or arts.",
        "Sun": "A period of absolute authority, power, and identity formation. You actively seek recognition and leadership roles.",
        "Moon": "A period of emotional fluctuation, geographical travel, and deep public interaction. Your internal focus shifts to the home.",
        "Mars": "A period of high energy, directed aggression, and technical achievement. Excellent for real estate or conquering obstacles.",
        "Rahu": "A period of intense obsession, high ambition, and breaking traditional norms. Unexpected, sudden rises and falls will occur.",
        "Jupiter": "A period of deep wisdom, structural expansion, and divine grace. You gain immense respect through knowledge. Wealth accumulates.",
        "Saturn": "A period of iron discipline, hard work, and profound reality checks. Growth is highly mathematically steady but slow.",
        "Mercury": "A period of sharp intellect, commerce, and rapid communication. The speed of life increases significantly. Business flourishes."
    }
    
    timeline = [{"Age (From-To)": f"0 - {int((first_end - birth_date).days/365.25)}", "Years": f"{curr_date.year} - {first_end.year}", "Mahadasha": first_lord, "Prediction": preds.get(first_lord, "")}]
    curr_date = first_end
    for i in range(1, 9):
        lord = DASHA_ORDER[(nak_idx + i) % 9]
        end_date = curr_date + timedelta(days=DASHA_YEARS[lord] * 365.25)
        timeline.append({"Age (From-To)": f"{int((curr_date - birth_date).days/365.25)} - {int((end_date - birth_date).days/365.25)}", "Years": f"{curr_date.year} - {end_date.year}", "Mahadasha": lord, "Prediction": preds.get(lord, "")})
        curr_date = end_date
    return timeline

def get_detailed_bhukti_analysis(md, ad, planet_bhava_map):
    md_house = planet_bhava_map.get(md, 1)
    ad_house = planet_bhava_map.get(ad, 1)
    topics = {1: "personal identity and vitality", 2: "wealth accumulation", 3: "courage and communication", 4: "domestic peace and real estate", 5: "creativity, children and intellect", 6: "health routines and overcoming competitors", 7: "marriage and partnerships", 8: "deep transformation and sudden events", 9: "luck, higher learning, and mentorship", 10: "career advancement and public status", 11: "network expansion and large gains", 12: "spiritual retreats and foreign connections"}
    remedy_deity = lifestyle_guidance.get(ad, {}).get("Deity", "your personal deity")
    
    base = f"This phase brings the overarching agenda of {md} (Strategy) into physical reality through the specific execution of {ad} (Tactics).\n\n"
    if md == ad: base += f"Because {md} is placed in your {md_house}th House, this period is intensely, heavily focused around {topics[md_house]}.\n\n"
    else: base += f"In your specific chart, {md} sits in the {md_house}th House (long-term focus), while {ad} is currently activating your {ad_house}th House. This means immediate events will manifest specifically through {topics[ad_house]}.\n\n"

    base += "Key Predictions:\n"
    base += f"- Core focus shifts heavily toward {topics[ad_house]}.\n"

    if ad in ["Saturn", "Mars", "Rahu", "Ketu", "Sun"]: base += "Precautions: This sub-period is ruled by an intense, aggressive planet. Avoid impulsive decisions and verify all legal documents.\n"
    else: base += "Precautions: While this is a supportive energy, do not become intellectually or physically complacent.\n"
    base += f"Actionable Pariharam: Regularly worship or meditate upon {remedy_deity}."
    return base

def generate_current_next_bhukti(moon_lon, birth_date, planet_bhava_map):
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
                            active_pd = {"MD": md_lord, "AD": ad_lord, "PD": pd_lord, "Start": pd_start.strftime('%d %b %Y'), "End": pd_end.strftime('%d %b %Y')}
                            p1 = {"Type": "CURRENT PHASE", "Phase": f"{md_lord} - {ad_lord}", "Dates": f"{ad_start.strftime('%b %Y')} to {ad_end.strftime('%b %Y')}", "Text": get_detailed_bhukti_analysis(md_lord, ad_lord, planet_bhava_map)}
                            next_ad = DASHA_ORDER[(ad_idx + i + 1) % 9]
                            p2 = {"Type": "NEXT PHASE", "Phase": f"{md_lord} - {next_ad}", "Dates": "Upcoming", "Text": get_detailed_bhukti_analysis(md_lord, next_ad, planet_bhava_map)}
                            return [p1, p2], active_pd
                        pd_start = pd_end
                ad_start = ad_end
        curr_md_start = md_end
        md_idx += 1
        bal = 1

# ==========================================
# 4. HTML VISUAL GENERATORS
# ==========================================
def get_south_indian_chart_html(p_pos, lagna_rasi, title, lang="English"):
    g = {i: [] for i in range(1, 13)}
    g[lagna_rasi].append("<span style='color:#e74c3c; font-size:12px;'><b>Asc</b></span>")
    for p, r in p_pos.items():
        name = TAMIL_NAMES[p] if lang == "Tamil" and p in TAMIL_NAMES else p[:2]
        g[r].append(f"<span style='font-size:12px; font-weight:bold; color:#2c3e50;'>{name}</span>")
    for i in g: g[i] = "<br>".join(g[i])
    z = ["", "Mesha", "Rishabha", "Mithuna", "Kataka", "Simha", "Kanya", "Thula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"]
    return f"<div style='max-width: 450px; margin: auto; font-family: sans-serif;'><table style='width: 100%; border-collapse: collapse; text-align: center; font-size: 14px; background-color: #ffffff; border: 2px solid #333;'><tr><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[12]} (12)</div>{g[12]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[1]} (1)</div>{g[1]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[2]} (2)</div>{g[2]}</td><td style='border: 1px solid #333; width: 25%; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[3]} (3)</div>{g[3]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[11]} (11)</div>{g[11]}</td><td colspan='2' rowspan='2' style='border: none; vertical-align: middle; font-weight: bold; font-size: 16px; color:#2c3e50; background-color: #ffffff;'>{title}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[4]} (4)</div>{g[4]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[10]} (10)</div>{g[10]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[5]} (5)</div>{g[5]}</td></tr><tr><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[9]} (9)</div>{g[9]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[8]} (8)</div>{g[8]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[7]} (7)</div>{g[7]}</td><td style='border: 1px solid #333; height: 95px; vertical-align: top; padding: 5px; background-color:#fafafa;'><div style='font-size:11px; color:#7f8c8d; text-align:left;'>{z[6]} (6)</div>{g[6]}</td></tr></table></div>"

# ==========================================
# 5. ROBUST BILINGUAL PDF EXPORT
# ==========================================
def sanitize_text(text):
    if not isinstance(text, str): return str(text)
    return text.replace('—', '-').replace('–', '-').replace('’', "'").replace('‘', "'")

def write_pdf_section(pdf, text_list, lang="English"):
    font_family = 'NotoTamil' if lang == "Tamil" else 'Arial'
    for line in text_list:
        clean = sanitize_text(line)
        if clean.startswith("#### "):
            pdf.ln(3)
            if lang == "Tamil":
                pdf.set_font(font_family, '', 12)
            else:
                pdf.set_font("Arial", 'B', 12)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 8, clean.replace("#### ", ""), ln=1)
        else:
            pdf.set_font(font_family, '', 11)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 6, clean)
            pdf.ln(2)

def draw_pdf_south_indian_chart(pdf, p_pos, lagna_rasi, title, lang="English"):
    box_map = {12: (0,0), 1: (1,0), 2: (2,0), 3: (3,0), 11: (0,1), 4: (3,1), 10: (0,2), 5: (3,2), 9: (0,3), 8: (1,3), 7: (2,3), 6: (3,3)}
    r_names = {1: "Mesha", 2: "Rishabha", 3: "Mithuna", 4: "Kataka", 5: "Simha", 6: "Kanya", 7: "Thula", 8: "Vrischika", 9: "Dhanu", 10: "Makara", 11: "Kumbha", 12: "Meena"}
    abbr_dict = {"Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me", "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke"}
    font_family = 'NotoTamil' if lang == "Tamil" else 'Arial'
    
    grid = {i: [] for i in range(1, 13)}
    grid[lagna_rasi].append("Asc")
    for p, r in p_pos.items():
        if p in abbr_dict: 
            grid[r].append(TAMIL_NAMES.get(p, p) if lang == "Tamil" else abbr_dict[p])
    
    if pdf.get_y() > 150: pdf.add_page()
    start_x, start_y, box_size = (210 - 120) / 2, pdf.get_y() + 5, 30
    
    pdf.set_fill_color(248, 248, 248)
    pdf.set_draw_color(100, 100, 100)
    
    for rasi, (col, row) in box_map.items():
        x, y = start_x + (col * box_size), start_y + (row * box_size)
        pdf.rect(x, y, box_size, box_size, style='D')
        
        pdf.set_font(font_family, '', 8)
        pdf.set_text_color(120, 120, 120)
        pdf.text(x + 2, y + 4, r_names[rasi])
        
        if lang == "Tamil":
            pdf.set_font(font_family, '', 9)
        else:
            pdf.set_font("Arial", 'B', 9)
        
        pdf.set_text_color(30, 30, 30)
        planets = grid[rasi]
        if planets:
            pdf.set_xy(x, y + 6)
            pdf.multi_cell(box_size, 4, "\n".join(planets), align='C')
    
    if lang == "Tamil":
        pdf.set_font(font_family, '', 12)
    else:
        pdf.set_font("Arial", 'B', 12)
        
    pdf.set_text_color(50, 50, 50)
    pdf.set_xy(start_x + box_size, start_y + box_size)
    pdf.multi_cell(box_size * 2, box_size * 2, title, align='C')
    pdf.set_y(start_y + (box_size * 4) + 15)

def draw_pdf_bar_chart(pdf, sav_scores, lagna_str, lang="English"):
    if pdf.get_y() > 180: pdf.add_page()
    font_family = 'NotoTamil' if lang == "Tamil" else 'Arial'
    
    if lang == "Tamil":
        pdf.set_font(font_family, '', 11)
    else:
        pdf.set_font("Arial", 'B', 11)
        
    start_x, start_y = 25, pdf.get_y() + 5
    lagna_idx = list(ZODIAC).index(lagna_str)
    
    pdf.set_draw_color(255, 255, 255)
    for i in range(12):
        house_num = i + 1
        score = sav_scores[(lagna_idx - 1 + i) % 12]
        
        pdf.set_xy(start_x, start_y + (i * 7))
        pdf.set_text_color(80, 80, 80)
        pdf.set_font(font_family, '', 10)
        label = "பாவம்" if lang == "Tamil" else "H"
        pdf.cell(35, 6, f"{label} {house_num}", ln=0)
        
        bar_width = (score / 45) * 100
        pdf.set_fill_color(200, 200, 200)
        pdf.rect(start_x + 35, start_y + (i * 7) + 1, bar_width, 4, style='F')
        
        if score >= 30: pdf.set_text_color(39, 174, 96)
        elif score < 25: pdf.set_text_color(231, 76, 60)
        else: pdf.set_text_color(50, 50, 50)
        
        pdf.set_font("Arial", 'B', 10)
        pdf.set_xy(start_x + 35 + bar_width + 2, start_y + (i * 7))
        pdf.cell(10, 6, str(score), ln=0)
        
    pdf.set_y(start_y + (12 * 7) + 15)

def generate_pdf_report(name_in, p_pos, p_d9, lagna_rasi, sav_scores, career_txt, edu_txt, health_txt, love_txt, id_data, lagna_str, moon_str, star_str, yogas, fc, micro_transits, mahadasha_data, phases, pd_info, guide, transit_texts, lang="English"):
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        font_family = 'Arial'
        if lang == "Tamil":
            if os.path.exists("NotoSansTamil.ttf"):
                pdf.add_font("NotoTamil", "", "NotoSansTamil.ttf")
                font_family = 'NotoTamil'
            else:
                return b"PDF Error: Missing NotoSansTamil.ttf font file in the folder! Please download it and place it next to app.py."
                
        pdf.add_page()
        
        h_title = f"ஜோதிட அறிக்கை: {name_in}" if lang == "Tamil" else f"Vedic Astrology Report: {name_in}"
        h_id = "1. சுயவிவரம் (Identity)" if lang == "Tamil" else "1. Identity & Personality"
        h_rasi = "2. ராசி சக்கரம் (Rasi Chakra)" if lang == "Tamil" else "2. Birth Chart (Rasi Chakra)"
        h_score = "3. அஷ்டகவர்க்கம் (Destiny Radar)" if lang == "Tamil" else "3. Destiny Radar (Scorecard)"
        h_work = "4. கல்வி மற்றும் தொழில் (Work & Intellect)" if lang == "Tamil" else "4. Work & Intellect (Education & Career)"
        h_love = "5. திருமணம் (Love & Marriage)" if lang == "Tamil" else "5. Love & Marriage (Navamsa Engine)"
        h_health = "6. ஆரோக்கியம் (Health & Vitality)" if lang == "Tamil" else "6. Health & Vitality"
        
        if lang == "Tamil":
            pdf.set_font(font_family, '', 16)
        else:
            pdf.set_font("Arial", 'B', 16)
            
        pdf.cell(0, 10, sanitize_text(h_title), ln=1, align='C')
        
        if lang == "Tamil":
            pdf.set_font(font_family, '', 12)
        else:
            pdf.set_font("Arial", 'I', 12)
        
        l_txt = ZODIAC[lagna_rasi]
        m_txt = ZODIAC[moon_rasi]
        if lang == "Tamil":
            pdf.cell(0, 10, sanitize_text(f"லக்னம்: {l_txt} | ராசி: {m_txt} | நட்சத்திரம்: {star_str}"), ln=1, align='C')
        else:
            pdf.cell(0, 10, sanitize_text(f"Lagna: {lagna_str} | Moon: {moon_str} | Star: {star_str}"), ln=1, align='C')
            
        pdf.line(10, 30, 200, 30)
        pdf.ln(10)
        
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_id), ln=1)
        
        if lang == "Tamil":
            write_pdf_section(pdf, [f"நோக்கம்: {id_data['Purpose']}", f"குணம்: {id_data['Personality']}", f"பலங்கள்: {id_data['Strengths']}", f"பலவீனங்கள்: {id_data['Weaknesses']}"], lang)
        else:
            write_pdf_section(pdf, [f"Life Purpose: {id_data['Purpose']}", f"Core Trait: {id_data['Personality']}", f"Strengths: {id_data['Strengths']}", f"Weaknesses: {id_data['Weaknesses']}"], lang)
        
        pdf.ln(5)
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_rasi), ln=1)
        draw_pdf_south_indian_chart(pdf, p_pos, lagna_rasi, h_rasi.split(' ')[1] if lang=="Tamil" else "Rasi Chart", lang)
        
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_score), ln=1)
        draw_pdf_bar_chart(pdf, sav_scores, lagna_str, lang)
        
        pdf.add_page()
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_work), ln=1)
        write_pdf_section(pdf, edu_txt, lang)
        write_pdf_section(pdf, career_txt, lang)

        pdf.add_page()
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_love), ln=1)
        d9_lagna_idx = get_navamsa_chart(p_pos.get("Lagna", lagna_rasi*30))
        draw_pdf_south_indian_chart(pdf, p_d9, d9_lagna_idx, "Navamsa", lang)
        write_pdf_section(pdf, love_txt, lang)
        
        pdf.ln(8)
        if lang == "Tamil":
            pdf.set_font(font_family, '', 14)
        else:
            pdf.set_font("Arial", 'B', 14)
            
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, sanitize_text(h_health), ln=1)
        write_pdf_section(pdf, health_txt, lang)

        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        footer = "வேத ஜோதிட என்ஜின் மூலம் உருவாக்கப்பட்டது" if lang == "Tamil" else "Generated by Vedic Astro Engine (Platinum Edition)"
        pdf.cell(0, 10, txt=sanitize_text(footer), align='C', ln=1)
        
        out = pdf.output()
        return bytes(out)
    except Exception as e:
        return f"PDF Error: {str(e)}".encode('utf-8')

# ==========================================
# 6. STREAMLIT APP UI & EXECUTION
# ==========================================

if 'report_generated' not in st.session_state:
    st.session_state.report_generated = False
if 'messages' not in st.session_state:
    st.session_state.messages = []

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
        master_table.append({"Planet": p, "Rasi": ZODIAC[r1], "House": h, "Bhava": bhava_h, "Dignity": dig, "Status": status})

    p_pos["Lagna"] = lagna_rasi
    bhava_placements["Ketu"] = ketu_bhava_h 
    sav_scores = calculate_sav_score(p_pos, lagna_rasi)
    nak, lord = get_nakshatra_details(moon_res[0])
    
    yogas = scan_yogas(p_pos, lagna_rasi)
    career_txt = analyze_career_professional(p_pos, d10_lagna, lagna_rasi, sav_scores, bhava_placements)
    edu_txt = analyze_education(p_pos, lagna_rasi)
    health_txt = analyze_health(p_pos, lagna_rasi)
    love_txt = analyze_love_marriage(lagna_rasi, d9_lagna, p_d9, p_pos)
    
    fc = generate_annual_forecast(moon_rasi, sav_scores, f_year, current_age)
    t_data = get_transit_data_advanced(f_year)
    sat_h = (t_data['Saturn']['Rasi'] - moon_rasi + 1) if (t_data['Saturn']['Rasi'] - moon_rasi + 1) > 0 else (t_data['Saturn']['Rasi'] - moon_rasi + 1) + 12
    sat_txt = f"Moving From: {ZODIAC[t_data['Saturn']['Rasi']]} to {t_data['Saturn']['NextSign']} on {t_data['Saturn']['NextDate']}\nPsychology: You may feel a heavy weight of responsibility or a need to isolate.\nOutcome: Transiting the {sat_h}th House indicates specific karmic results."
    jup_txt = f"Moving From: {ZODIAC[t_data['Jupiter']['Rasi']]} to {t_data['Jupiter']['NextSign']} on {t_data['Jupiter']['NextDate']}\nPsychology: Optimism returns. You feel supported by invisible hands.\nOutcome: Growth in wealth and wisdom."
    rahu_txt = f"Current Axis: Rahu in {ZODIAC[t_data['Rahu']['Rasi']]} / Ketu in {ZODIAC[(t_data['Rahu']['Rasi']+6-1)%12+1]}\nPsychology: Rahu creates obsession where it sits, while Ketu creates detachment."
    transit_texts = [sat_txt, jup_txt, rahu_txt]
    
    micro_transits = get_micro_transits(f_year, p_lon_absolute)
    mahadasha_data = generate_mahadasha_table(moon_res[0], datetime.combine(dob_in, tob_in))
    phases, pd_info = generate_current_next_bhukti(moon_res[0], datetime.combine(dob_in, tob_in), bhava_placements)
    guide = lifestyle_guidance.get(RASI_RULERS[moon_rasi], lifestyle_guidance["Moon"])

    c_left, c_right = st.columns([3, 1])
    with c_left:
        st.subheader(f"Analysis for {name_in}")
        st.markdown(f"> Lagna: **{ZODIAC[lagna_rasi]}** | Moon: **{ZODIAC[moon_rasi]}** | Star: **{nak}**")
    with c_right:
        eng_id_data = identity_db.get(ZODIAC[lagna_rasi], identity_db["Mesha"])
        
        # --- NEW SAFTEY CHECK FOR PDF EXPORT ---
        pdf_bytes = generate_pdf_report(name_in, p_pos, p_d9, lagna_rasi, sav_scores, career_txt, edu_txt, health_txt, love_txt, eng_id_data, ZODIAC[lagna_rasi], ZODIAC[moon_rasi], nak, yogas, fc, micro_transits, mahadasha_data, phases, pd_info, guide, transit_texts, lang=LANG)
        
        if pdf_bytes.startswith(b"PDF Error:"):
            st.error(pdf_bytes.decode('utf-8'))
        else:
            st.download_button(label="📄 Download PDF Report", data=pdf_bytes, file_name=f"{name_in}_Astro_Report.pdf", mime="application/pdf")

    # Dynamic UI Mapping
    db_id = TAMIL_IDENTITY_DB if LANG == "Tamil" else identity_db
    db_lev = TAMIL_LEVERAGE_GUIDE if LANG == "Tamil" else house_leverage_guide
    db_eff = TAMIL_EFFORT_GUIDE if LANG == "Tamil" else house_effort_guide
    db_life = TAMIL_LIFESTYLE if LANG == "Tamil" else lifestyle_guidance

    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["Profile", "Scorecard", "Work & Intellect", "Love & Health", "Yogas", "Forecast", "Roadmap", "💬 AI Oracle"])

    with t1:
        st.subheader("Identity" if LANG == "English" else "சுயவிவரம்")
        user_id = db_id.get(ZODIAC[lagna_rasi] if LANG == "English" else ZODIAC[lagna_rasi], list(db_id.values())[0])
        st.markdown(f"**Purpose:** {user_id['Purpose']}")
        st.markdown(f"**Personality:** {user_id['Personality']}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Strengths")
            st.markdown(user_id['Strengths'])
        with c2:
            st.markdown("#### Weaknesses")
            st.markdown(user_id['Weaknesses'])
        
        st.divider()
        st.markdown("<h3 style='text-align: center;'>Birth Chart (Rasi Chakra)</h3>", unsafe_allow_html=True)
        st.markdown(get_south_indian_chart_html(p_pos, lagna_rasi, "Birth Chart (Rasi)", LANG), unsafe_allow_html=True)
        
        st.markdown("<h4 style='text-align: center; margin-top: 30px;'>Planetary Details</h4>", unsafe_allow_html=True)
        table_md = "<table style='width: 80%; margin: 20px auto; border-collapse: collapse; font-family: sans-serif; font-size: 15px; text-align: center;'><tr style='background-color: #f8f9fa; border-bottom: 2px solid #ccc;'><th style='padding: 12px 8px;'>Planet</th><th style='padding: 12px 8px;'>Rasi</th><th style='padding: 12px 8px;'>House</th><th style='padding: 12px 8px;'>Bhava</th><th style='padding: 12px 8px;'>Dignity</th><th style='padding: 12px 8px;'>Status</th></tr>"
        for row in master_table:
            p_name = TAMIL_NAMES.get(row['Planet'], row['Planet']) if LANG == "Tamil" else row['Planet']
            table_md += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 12px 8px;'><b>{p_name}</b></td><td style='padding: 12px 8px;'>{row['Rasi']}</td><td style='padding: 12px 8px;'>{row['House']}</td><td style='padding: 12px 8px;'>{row['Bhava']}</td><td style='padding: 12px 8px;'>{row['Dignity']}</td><td style='padding: 12px 8px;'>{row['Status']}</td></tr>"
        table_md += "</table>"
        st.markdown(table_md, unsafe_allow_html=True)

    with t2:
        st.subheader("Destiny Radar" if LANG == "English" else "அஷ்டகவர்க்கம்")
        cats_labels = [f"H{i+1}" for i in range(12)]
        vals = [sav_scores[(lagna_rasi-1+i)%12] for i in range(12)]
        text_colors = ['#27ae60' if v >= 30 else '#e74c3c' if v < 25 else '#333333' for v in vals]
        
        fig_bar = go.Figure(data=[go.Bar(
            x=vals, y=cats_labels, orientation='h', marker_color='#bdc3c7', 
            text=[f"<b>{v}</b>" for v in vals], textposition='outside', textfont=dict(color=text_colors, size=14)
        )])
        fig_bar.add_vline(x=28, line_width=2, line_dash="dash", line_color="#7f8c8d", annotation_text="Average (28)", annotation_position="top right")
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=20, r=20, t=40, b=20), height=400)
        st.plotly_chart(fig_bar, use_container_width=True)
        
        c1, c2 = st.columns(2)
        sorted_houses = sorted([(sav_scores[(lagna_rasi-1+i)%12], i+1) for i in range(12)], key=lambda x: x[0], reverse=True)
        with c1:
            st.markdown("<h4 style='color: #27ae60; margin-bottom: 0px;'>Power Zones (Leverage These)</h4>", unsafe_allow_html=True)
            for s, h in sorted_houses[:3]:
                st.markdown(f"**H{h} - {s} Points:**\n{db_lev[h]}")
        with c2:
            st.markdown("<h4 style='color: #e74c3c; margin-bottom: 0px;'>Challenge Zones (Extra Effort)</h4>", unsafe_allow_html=True)
            for s, h in sorted_houses[-3:]:
                st.markdown(f"**H{h} - {s} Points:**\n{db_eff[h]}")

    with t3:
        st.subheader("Education & Intellect")
        for line in edu_txt: st.markdown(line)
        st.divider()
        st.subheader("The CEO Engine (Career)")
        for line in career_txt: st.markdown(line)

    with t4:
        st.markdown("<h3 style='text-align: center;'>Destiny Chart (Navamsa Chakra)</h3>", unsafe_allow_html=True)
        st.markdown(get_south_indian_chart_html(p_d9, d9_lagna, "Destiny Chart (Navamsa)", LANG), unsafe_allow_html=True)
        st.divider()
        st.subheader("Love & Marriage")
        for line in love_txt: st.markdown(line)
        st.divider()
        st.subheader("Health & Vitality (Medical Astrology)")
        for line in health_txt: st.markdown(line)

    with t5:
        st.subheader("Wealth & Power Combinations (Yogas)")
        for y in yogas:
            st.markdown(f"#### {y['Name']}")
            st.markdown(f"> Focus: **{y['Type']}**")
            st.markdown(y['Description'])

    with t6:
        st.subheader(f"Annual Forecast {f_year}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Career")
            st.markdown(fc['Career'][0])
            st.markdown(f"> Remedy: {fc['Career'][1]}")
        with c2:
            st.markdown("#### Wealth")
            st.markdown(fc['Wealth'][0])
            st.markdown(f"> Remedy: {fc['Wealth'][1]}")
        
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Relationships")
            st.markdown(fc['Rel'][0])
            st.markdown(f"> Remedy: {fc['Rel'][1]}")
        with c4:
            st.markdown("#### Age Focus")
            st.markdown(fc['Focus'][0])
            st.markdown(f"> Remedy: {fc['Focus'][1]}")
            
        st.divider()
        st.subheader("Planetary Transits & Precision Timing")
        st.markdown("#### Macro Transits")
        for txt in transit_texts: st.markdown(txt.replace('\n', '  \n'))
        
        if micro_transits:
            st.markdown("#### Micro-Transits")
            for mt in micro_transits:
                st.markdown(f"**{mt['Dates']}**: {mt['Trigger']}")
                st.markdown(mt['Impact'])

    with t7:
        st.subheader("Strategic Roadmap")
        if pd_info:
            st.markdown("#### IMMEDIATE FOCUS (Pratyantar Dasha)")
            st.markdown(f"You are currently in the micro-period of **{pd_info['PD']}** (operating under {pd_info['MD']} Major and {pd_info['AD']} Minor). This precise energy lasts from **{pd_info['Start']} to {pd_info['End']}**.")
            st.divider()
        
        st.markdown("#### Phase Drill-Down (Detailed)")
        for p in phases:
            st.markdown(f"**{p['Type']}: {p['Phase']}**")
            st.markdown(f"> Duration: {p['Dates']}")
            st.markdown(p['Text'].replace('\n', '  \n'))
            st.divider()

        st.markdown("#### Life Chapters (Timeline)")
        planet_colors = {"Sun": "#d35400", "Moon": "#95a5a6", "Mars": "#c0392b", "Mercury": "#27ae60", "Jupiter": "#f39c12", "Venus": "#8e44ad", "Saturn": "#2c3e50", "Rahu": "#34495e", "Ketu": "#7f8c8d"}
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

        md_table_html = "<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 14px; margin-bottom: 20px;'><tr style='border-bottom: 2px solid #ddd; background-color: #fdfdfd;'><th style='padding: 10px 8px; text-align: left; width: 10%;'>Age</th><th style='padding: 10px 8px; text-align: left; width: 10%;'>Years</th><th style='padding: 10px 8px; text-align: left; width: 15%;'>Mahadasha</th><th style='padding: 10px 8px; text-align: left; width: 65%;'>Prediction</th></tr>"
        for row in mahadasha_data:
            s_year, e_year = row['Years'].split(' - ')
            md_table_html += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 10px 8px; vertical-align: top;'>{row['Age (From-To)']}</td><td style='padding: 10px 8px; vertical-align: top;'>{s_year}<br>{e_year}</td><td style='padding: 10px 8px; vertical-align: top;'><b>{row['Mahadasha']}</b></td><td style='padding: 10px 8px; vertical-align: top;'>{row['Prediction']}</td></tr>"
        md_table_html += "</table>"
        st.markdown(md_table_html, unsafe_allow_html=True)

    with t8:
        st.subheader("💬 Ask the AI Astrologer")
        st.info("I am an AI trained on your exact astrological coordinates. We can chat back and forth!")

        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt_input := st.chat_input("Ask a question (e.g., 'What remedies should I do?'):"):
            if not GEMINI_API_KEY:
                st.error("API Key missing! Please add your key to api_config.py")
            else:
                st.session_state.messages.append({"role": "user", "content": prompt_input})
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt_input)

                    with st.chat_message("assistant"):
                        with st.spinner("The AI Astrologer is analyzing..."):
                            try:
                                genai.configure(api_key=GEMINI_API_KEY)
                                chart_context = f"User is Ascendant {ZODIAC[lagna_rasi]} and Moon {ZODIAC[moon_rasi]}. "
                                chart_context += f"Planetary positions: {p_pos}. "
                                if pd_info: chart_context += f"Current Dasha Phase: {pd_info['MD']} Mahadasha, {pd_info['AD']} Antardasha. "
                                chart_context += f"House strengths out of 40: {dict(zip(range(1,13), vals))}. "
                                chart_context += f"CRITICAL CONTEXT: Target forecast year is {f_year}. "
                                chart_context += f"For {f_year}, major transits are: Saturn in {ZODIAC[t_data['Saturn']['Rasi']]}, Jupiter in {ZODIAC[t_data['Jupiter']['Rasi']]}, Rahu in {ZODIAC[t_data['Rahu']['Rasi']]}. "
                                
                                sys_lang = "poetic, natural, and traditional Tamil (like a wise Nadi astrologer)" if LANG == "Tamil" else "English"
                                persona = "You are a wise, highly accurate, and compassionate Vedic Astrologer. "
                                rules = f"Based STRICTLY on the mathematical chart data, transits, and our conversation history, answer the user's question practically in 3 to 4 sentences. CRITICAL RULE: If the user explicitly asks you to speak in a specific language in their prompt, you MUST use that requested language. Otherwise, default to answering entirely in {sys_lang}. Do NOT sound like a machine translation. Always conclude with a brief, encouraging remedy."
                                
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
            if st.button("🗑️ Clear Chat History"):
                st.session_state.messages = []
                st.rerun()
