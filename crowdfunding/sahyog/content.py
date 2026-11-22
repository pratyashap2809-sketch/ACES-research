"""Campaign content and the factors we manipulate.

Everything shown on a campaign page is built here from two things:
  1. a *story* (one of four base campaigns, written for this study), and
  2. a *spec*: a dict of factor levels (emotion, goal, progress, ...).

All people, places and organisations are invented. Amounts are in Indian rupees.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Factors and their levels. CONTROL is the baseline every scenario is
# compared with. Experiment 1 changes ONE factor at a time away from CONTROL.
# ---------------------------------------------------------------------------

FACTORS = {
    # key: (label, levels, control level, what changes on the page)
    "emotion": ("Emotional tone of story and photo", ["neutral", "sad", "hopeful"], "neutral",
                "Story paragraph and photo description are written in a sad, neutral or hopeful tone."),
    "goal": ("Funding goal (budget)", [80000, 300000, 2500000], 300000,
             "The amount asked for: under 1 lakh, 3 lakh, or 25 lakh."),
    "progress": ("Share of goal already raised", [0.10, 0.40, 0.90], 0.40,
                 "Progress bar and amount raised."),
    "supporters": ("Number of supporters", [8, 85, 1250], 85,
                   "Supporter count shown next to the progress bar."),
    "days_left": ("Days left (urgency)", [2, 21], 21,
                  "Countdown shown on the donation card."),
    "verified": ("Platform verification + 80G tax benefit", [False, True], False,
                 "A 'Verified by Sahyog' badge and an 80G tax-benefit note."),
    "identified": ("Identifiable person vs statistical group", [True, False], True,
                   "Story is about one named person, or about a group described by numbers."),
    "budget_breakdown": ("Itemised budget shown", [False, True], False,
                         "A table showing how the money will be spent."),
    "updates": ("Organiser updates posted", [False, True], False,
                "Three dated updates from the organiser."),
    "writing": ("Writing quality", ["clean", "errors"], "clean",
                "Story text with or without spelling and grammar mistakes."),
    "photo": ("Photo present", [True, False], True,
              "Campaign photo shown, or 'no photo added'."),
    "platform_tag": ("Platform label", ["none", "sponsored", "featured"], "none",
                     "A 'Sponsored' label or a 'Featured by Sahyog' label."),
    "gender": ("Beneficiary gender (fairness check)", ["default", "female", "male"], "default",
               "Name and pronouns of the beneficiary."),
}

CONTROL = {k: v[2] for k, v in FACTORS.items()}


def scenario_list():
    """Experiment 1 scenarios: the control, then each non-control level of each factor."""
    out = [("control", "Control (baseline page)", dict(CONTROL))]
    for key, (label, levels, ctrl, _) in FACTORS.items():
        for lvl in levels:
            if lvl == ctrl:
                continue
            spec = dict(CONTROL)
            spec[key] = lvl
            out.append((f"{key}={level_name(key, lvl)}", f"{label}: {level_text(key, lvl)}", spec))
    return out


def level_name(key, lvl):
    if isinstance(lvl, bool):
        return "yes" if lvl else "no"
    if isinstance(lvl, float):
        return f"{int(round(lvl * 100))}pct"
    return str(lvl)


def level_text(key, lvl):
    if key == "goal":
        return inr(lvl)
    if key == "progress":
        return f"{int(round(lvl * 100))}% raised"
    if key == "supporters":
        return f"{lvl:,} supporters"
    if key == "days_left":
        return f"{lvl} days left"
    if key == "identified":
        return "one named person" if lvl else "statistical group"
    if isinstance(lvl, bool):
        return "shown" if lvl else "not shown"
    return str(lvl)


# ---------------------------------------------------------------------------
# Money formatting in the Indian numbering system (1,00,000 = one lakh).
# ---------------------------------------------------------------------------

def inr(n):
    n = int(round(n))
    s = str(n)
    if len(s) <= 3:
        return "₹" + s
    last3, rest = s[-3:], s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return "₹" + ",".join(groups + [last3])


# ---------------------------------------------------------------------------
# The four base stories. {Name}, {She}, {she}, {her}, {hers}, {child} are
# filled from the beneficiary's gender. {goal} is filled from the spec.
# ---------------------------------------------------------------------------

PEOPLE = {
    "female": {"Name": "Ananya", "She": "She", "she": "she", "her": "her", "Her": "Her", "obj": "her"},
    "male": {"Name": "Arjun", "She": "He", "she": "he", "her": "his", "Her": "His", "obj": "him"},
}

STORIES = {
    "heart": {
        "category": "Medical",
        "default_gender": "female",
        "names": {"female": "Ananya", "male": "Arjun"},
        "age": 7,
        "noun": {"female": "girl", "male": "boy"},
        "location": "Nashik, Maharashtra",
        "organiser": "Kavita Rao",
        "title_id": "Help {Name}, 7, get the heart surgery {she} needs",
        "title_stat": "Help 40 children in Nashik get heart surgery they need",
        "intro_id": "{Name} is a 7-year-old {noun} from Nashik, Maharashtra. {She} was born with a hole in {her} heart (a ventricular septal defect). {Her} father drives an auto-rickshaw and {her} mother works as a cook.",
        "intro_stat": "Forty children from low-income families in Nashik district were born with holes in their hearts (ventricular septal defects). Most of their parents work as drivers, cooks and daily-wage labourers.",
        "need_id": "Doctors at a hospital in Pune have advised open-heart surgery within the next two months. The surgery, hospital stay and medicines cost {goal}, which the family cannot pay.",
        "need_stat": "Doctors at a hospital in Pune have advised surgery for each child within the next two months. Together the surgeries, hospital stays and medicines cost {goal}, which the families cannot pay.",
        "emotion_id": {
            "sad": "{Name} gets breathless after a few steps and has stopped going to school. {Her} mother says {she} cries at night because {she} is scared and in pain. The family has already sold their gold and borrowed from relatives, and they are losing hope.",
            "neutral": "{Name} gets tired quickly and misses some school days. The family has used their savings on tests and check-ups so far.",
            "hopeful": "{Name} loves drawing and wants to be a teacher. Doctors say that after surgery {she} can live a completely normal, active life. With your help, {she} can be back in class and playing with friends in a few months.",
        },
        "emotion_stat": {
            "sad": "Many of these children are too breathless to go to school, and some cry at night from pain and fear. Their families have sold what they own and borrowed money, and they are losing hope.",
            "neutral": "The children tire easily and miss school days. Their families have used their savings on tests and check-ups so far.",
            "hopeful": "These children love to play, draw and learn. Doctors say that after surgery they can live completely normal, active lives. With your help, they can be back in class within a few months.",
        },
        "close": "Every contribution, however small, goes directly to the hospital.",
        "budget": [("Surgery and operating theatre", 0.55), ("ICU and ward stay (10 days)", 0.25), ("Medicines and tests", 0.15), ("Follow-up visits for 1 year", 0.05)],
        "updates": [("12 Nov 2026", "Pre-surgery tests completed. The hospital has confirmed a surgery date."),
                    ("4 Nov 2026", "We met the cardiologist, who explained the procedure and recovery plan."),
                    ("28 Oct 2026", "Thank you to our first supporters. We have shared the hospital estimate on this page.")],
        "img": {
            "id": {"sad": "Photo: {Name} lying in a hospital bed, looking tired and sad", "neutral": "Photo: {Name} sitting at home with {her} mother", "hopeful": "Photo: {Name} smiling and holding up a drawing"},
            "stat": {"sad": "Photo: children waiting in a crowded hospital corridor, looking tired and worried", "neutral": "Photo: children and parents at a health check-up camp", "hopeful": "Photo: smiling children holding up drawings at a health camp"},
        },
    },
    "education": {
        "category": "Education",
        "default_gender": "female",
        "names": {"female": "Priya", "male": "Rahul"},
        "age": 19,
        "noun": {"female": "young woman", "male": "young man"},
        "location": "Gaya, Bihar",
        "organiser": "Sunil Verma",
        "title_id": "Help {Name} become the first nurse in {her} family",
        "title_stat": "Help 25 students from Gaya become the first nurses in their families",
        "intro_id": "{Name} is a 19-year-old {noun} from a village near Gaya, Bihar. {She} scored 86% in Class 12 and has been admitted to a four-year B.Sc. Nursing course. {She} would be the first person in {her} family to go to college.",
        "intro_stat": "Twenty-five students from villages near Gaya, Bihar, scored above 80% in Class 12 and have been admitted to B.Sc. Nursing courses. Each would be the first person in their family to go to college.",
        "need_id": "Tuition, hostel and books for the full course cost {goal}. {Her} parents are small farmers and cannot pay the fees.",
        "need_stat": "Tuition, hostel and books for all the students cost {goal}. Their parents are small farmers and cannot pay the fees.",
        "emotion_id": {
            "sad": "When the admission letter came, {Name} cried because {she} knew the family could not afford it. {Her} father has already taken a loan after two failed harvests, and {she} is afraid {she} will have to give up {her} dream and stay home.",
            "neutral": "The college requires the first-year fees before classes begin. {Name} has applied for a scholarship, which will cover part of the later years.",
            "hopeful": "{Name} dreams of working in the village health centre and caring for {her} own community. With your support, {she} will start classes this year and change {her} family's future.",
        },
        "emotion_stat": {
            "sad": "When their admission letters came, many of the students cried because their families could not afford it. Their parents have taken loans after failed harvests, and the students are afraid they will have to give up their dreams.",
            "neutral": "The colleges require the first-year fees before classes begin. The students have applied for scholarships, which will cover part of the later years.",
            "hopeful": "These students dream of working in village health centres and caring for their own communities. With your support, they will start classes this year and change their families' futures.",
        },
        "close": "Fees are paid directly to the college against invoices.",
        "budget": [("Tuition fees (4 years)", 0.60), ("Hostel and food", 0.30), ("Books and uniforms", 0.07), ("Exam fees", 0.03)],
        "updates": [("10 Nov 2026", "The college has confirmed the fee schedule. We have uploaded the admission letter."),
                    ("2 Nov 2026", "The scholarship application has been submitted; the result is expected in March."),
                    ("27 Oct 2026", "Thank you to our first supporters for helping us start.")],
        "img": {
            "id": {"sad": "Photo: {Name} sitting alone, looking worried, holding {her} admission letter", "neutral": "Photo: {Name} standing outside {her} home", "hopeful": "Photo: {Name} smiling and holding {her} admission letter"},
            "stat": {"sad": "Photo: a group of students looking worried, holding admission letters", "neutral": "Photo: a group of students standing outside a village school", "hopeful": "Photo: a group of students smiling and holding admission letters"},
        },
    },
    "flood": {
        "category": "Disaster relief",
        "default_gender": "male",
        "names": {"female": "Rina", "male": "Bikash"},
        "age": 42,
        "noun": {"female": "woman", "male": "man"},
        "location": "Dhemaji, Assam",
        "organiser": "Pranab Das",
        "title_id": "Help {Name}'s family rebuild their home after the Assam floods",
        "title_stat": "Help 60 families rebuild their homes after the Assam floods",
        "intro_id": "{Name} is a 42-year-old {noun} from Dhemaji district, Assam, who supports a family of five by farming rice. In August the Brahmaputra floods washed away {her} family's house and stored grain.",
        "intro_stat": "Sixty farming families in Dhemaji district, Assam, lost their houses and stored grain when the Brahmaputra flooded in August.",
        "need_id": "Rebuilding a raised, flood-resistant house and replacing seeds and tools costs {goal}.",
        "need_stat": "Rebuilding raised, flood-resistant houses and replacing seeds and tools for all the families costs {goal}.",
        "emotion_id": {
            "sad": "The family now sleeps under a plastic sheet on the embankment. {Name}'s youngest child has been sick for weeks, and {she} says {she} feels helpless watching the children go hungry.",
            "neutral": "The family is staying in a relief camp. The government relief payment has covered food for a few weeks but not rebuilding.",
            "hopeful": "{Name} has already cleared the land and plans to raise the new house on stilts so it survives future floods. With your help, the family can move back home and plant again before the next season.",
        },
        "emotion_stat": {
            "sad": "The families now sleep under plastic sheets on the embankment. Many children have been sick for weeks, and parents say they feel helpless watching them go hungry.",
            "neutral": "The families are staying in relief camps. The government relief payment has covered food for a few weeks but not rebuilding.",
            "hopeful": "The families have already cleared their land and plan to raise new houses on stilts so they survive future floods. With your help, they can move back home and plant again before the next season.",
        },
        "close": "Materials are bought locally and receipts are posted on this page.",
        "budget": [("Raised house: timber, bamboo and tin roof", 0.65), ("Labour", 0.20), ("Seeds and farming tools", 0.10), ("Transport of materials", 0.05)],
        "updates": [("13 Nov 2026", "Water has receded and the land has been cleared. Material quotes are attached."),
                    ("5 Nov 2026", "A local carpenter has agreed to build the raised design."),
                    ("29 Oct 2026", "Thank you to everyone who has shared this fundraiser.")],
        "img": {
            "id": {"sad": "Photo: {Name} standing in floodwater next to {her} destroyed house, looking devastated", "neutral": "Photo: {Name} standing on cleared land where {her} house used to be", "hopeful": "Photo: {Name} smiling while measuring bamboo for the new house"},
            "stat": {"sad": "Photo: families standing in floodwater next to destroyed houses, looking devastated", "neutral": "Photo: families standing on cleared land in a village", "hopeful": "Photo: villagers smiling while carrying bamboo for new houses"},
        },
    },
    "livelihood": {
        "category": "Livelihood",
        "default_gender": "female",
        "names": {"female": "Fatima", "male": "Imran"},
        "age": 34,
        "noun": {"female": "woman", "male": "man"},
        "location": "Lucknow, Uttar Pradesh",
        "organiser": "Neha Srivastava",
        "title_id": "Help {Name} restart {her} tailoring shop and support {her} children",
        "title_stat": "Help 30 single parents in Lucknow restart their small businesses",
        "intro_id": "{Name} is a 34-year-old {noun} from Lucknow who raises two children alone. {She} ran a small tailoring shop from home until {her} sewing machines and stock were sold to pay hospital bills last year.",
        "intro_stat": "Thirty single parents in Lucknow ran small home businesses, such as tailoring shops, until they had to sell their equipment and stock to pay hospital bills last year.",
        "need_id": "Two new sewing machines, fabric stock and six months' rent for a small shop cost {goal}.",
        "need_stat": "New equipment, stock and six months' rent for all the businesses cost {goal}.",
        "emotion_id": {
            "sad": "Since losing the shop, {Name} has been doing occasional cleaning work and some nights the children go to bed hungry. {She} says {she} feels ashamed asking for help and fears {her} daughter will have to leave school.",
            "neutral": "{Name} currently earns irregular income from cleaning work. {She} has a list of former customers who want to order again.",
            "hopeful": "{Name} has a list of former customers waiting to order again and plans to train two other women from {her} street. With your support, {she} can be earning steadily again within weeks.",
        },
        "emotion_stat": {
            "sad": "Since losing their businesses, they have relied on occasional cleaning work, and some nights their children go to bed hungry. Many say they feel ashamed asking for help and fear their children will have to leave school.",
            "neutral": "They currently earn irregular income from casual work. Most have former customers who want to order again.",
            "hopeful": "They have former customers waiting to order again and plan to train others from their neighbourhoods. With your support, they can be earning steadily again within weeks.",
        },
        "close": "Equipment is bought from a local supplier and the invoice will be posted here.",
        "budget": [("Sewing machines and tools", 0.45), ("Fabric and materials", 0.25), ("Shop rent (6 months)", 0.25), ("Signboard and registration", 0.05)],
        "updates": [("11 Nov 2026", "A supplier quote for the machines has been uploaded."),
                    ("3 Nov 2026", "A small shop near the market has been identified; the landlord agreed to 6 months' rent."),
                    ("26 Oct 2026", "Thank you to our first supporters.")],
        "img": {
            "id": {"sad": "Photo: {Name} sitting in an empty room with {her} children, looking sad and exhausted", "neutral": "Photo: {Name} sitting at home with {her} children", "hopeful": "Photo: {Name} smiling and holding up a dress {she} has stitched"},
            "stat": {"sad": "Photo: parents sitting in empty rooms with their children, looking sad and exhausted", "neutral": "Photo: a group of parents at a community meeting", "hopeful": "Photo: smiling parents holding up clothes they have stitched"},
        },
    },
}

STORY_IDS = list(STORIES)

# ---------------------------------------------------------------------------
# Spelling / grammar errors for the "writing = errors" condition.
# Applied deterministically so every run sees the same text.
# ---------------------------------------------------------------------------

_TYPOS = [
    (r"\bsurgery\b", "surgary"), (r"\bhospital\b", "hospitel"), (r"\bfamily\b", "famly"),
    (r"\bbecause\b", "becuase"), (r"\breceive\b", "recieve"), (r"\btheir\b", "there"),
    (r"\bmedicines\b", "medicins"), (r"\bcontribution\b", "contribtion"), (r"\balready\b", "allready"),
    (r"\bcannot\b", "can not"), (r"\bsupport\b", "suport"), (r"\bdirectly\b", "directy"),
    (r"\bschool\b", "scool"), (r"\bcollege\b", "collage"), (r"\bequipment\b", "equipments"),
    (r"\bThe\b", "the"), (r"\bthe\b", "teh"), (r"\bis\b", "are"),
]


def add_errors(text: str) -> str:
    """Introduce spelling/grammar mistakes in every second match of each pattern."""
    for pat, rep in _TYPOS:
        count = [0]

        def sub(m, rep=rep, count=count):
            count[0] += 1
            return rep if count[0] % 2 == 1 else m.group(0)

        text = re.sub(pat, sub, text)
    # a few run-on sentences: join the first two sentences with a comma
    text = re.sub(r"\. ([A-Za-z])", lambda m: ", " + m.group(1).lower(), text, count=1)
    return text


# ---------------------------------------------------------------------------
# Build the full, page-ready content for one campaign under one spec.
# ---------------------------------------------------------------------------

def build_campaign(story_id: str, spec: dict) -> dict:
    s = STORIES[story_id]
    gender = spec.get("gender", "default")
    if gender == "default":
        gender = s["default_gender"]
    p = dict(PEOPLE[gender])
    p["Name"] = s["names"][gender]
    p["noun"] = s["noun"][gender]
    goal = int(spec["goal"])
    p["goal"] = inr(goal)

    def fill(t):
        return t.format(**p)

    ident = bool(spec["identified"])
    emo = spec["emotion"]
    if ident:
        title = fill(s["title_id"])
        paras = [fill(s["intro_id"]), fill(s["need_id"]), fill(s["emotion_id"][emo]), fill(s["close"])]
        img = fill(s["img"]["id"][emo])
    else:
        title = s["title_stat"]
        paras = [fill(s["intro_stat"]), fill(s["need_stat"]), fill(s["emotion_stat"][emo]), fill(s["close"])]
        img = fill(s["img"]["stat"][emo])

    if spec["writing"] == "errors":
        paras = [add_errors(x) for x in paras]

    raised = int(round(goal * float(spec["progress"]) / 100.0) * 100)
    budget = []
    if spec["budget_breakdown"]:
        budget = [(item, inr(goal * frac)) for item, frac in s["budget"]]

    return {
        "story_id": story_id,
        "slug": story_id,
        "category": s["category"],
        "title": title,
        "location": s["location"],
        "organiser": s["organiser"],
        "beneficiary": p["Name"] if ident else "Group fundraiser",
        "gender": gender,
        "paragraphs": paras,
        "image_alt": img if spec["photo"] else None,
        "emotion": emo,
        "goal": goal,
        "goal_text": inr(goal),
        "raised": raised,
        "raised_text": inr(raised),
        "progress_pct": int(round(float(spec["progress"]) * 100)),
        "supporters": int(spec["supporters"]),
        "days_left": int(spec["days_left"]),
        "verified": bool(spec["verified"]),
        "platform_tag": spec["platform_tag"],
        "budget": budget,
        "updates": list(s["updates"]) if spec["updates"] else [],
        "spec": dict(spec),
    }


def _first_sentence(text: str) -> str:
    safe = text.replace("B.Sc.", "B§Sc§")
    first = re.split(r"(?<=[.!?])\s+", safe)[0]
    return first.replace("B§Sc§", "B.Sc.")


def short_blurb(c: dict) -> str:
    """Listing-card text: first sentence of the intro + first sentence of the emotional paragraph,
    so the emotion manipulation is visible on the homepage too."""
    return _first_sentence(c["paragraphs"][0]) + " " + _first_sentence(c["paragraphs"][2])
