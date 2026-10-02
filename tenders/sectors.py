"""Tender sector ("what kind of work is this?") from the title and the portal's categories.

GePNIC's own Product Category is precise when the buyer picks a specific one ("Civil
Works - Highways") but often generic ("Civil Works", "Miscellaneous Services"). So:

  1. distinctive title words that are never ambiguous (CCTV, software, ...)
  2. a specific Product Category
  3. ordered title keyword rules (services like sweeping before the roads they sweep)
  4. a generic Product Category
  5. the tender category (Works / Goods / Services)
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Sector:
    slug: str
    label: str
    description: str


SECTORS = [
    Sector("roads", "Roads & Bridges", "Highways, roads, bridges, flyovers, pavements"),
    Sector(
        "buildings", "Buildings & Civil", "Construction, renovation, repairs, civil maintenance"
    ),
    Sector(
        "electrical", "Electrical & Power", "Electrical works, power, solar, lighting, HVAC, lifts"
    ),
    Sector(
        "water", "Water & Sanitation", "Water supply, pipelines, drainage, sewerage, irrigation"
    ),
    Sector(
        "it", "IT & Technology", "Software, computers, networks, data centres, digital services"
    ),
    Sector("security", "Security & Safety", "Security services, CCTV, surveillance, fire safety"),
    Sector("health", "Health & Medical", "Medical equipment, drugs, hospital consumables"),
    Sector("lab", "Science & Lab", "Laboratory and scientific equipment, chemicals, reagents"),
    Sector(
        "facility", "Facility & Manpower", "Housekeeping, manpower, catering, gardening, cleaning"
    ),
    Sector("transport", "Vehicles & Transport", "Vehicle hiring, transport, logistics"),
    Sector("consultancy", "Consultancy & Surveys", "Consultancy, DPRs, surveys, studies, audits"),
    Sector("supplies", "Goods & Supplies", "Furniture, stationery, equipment and other goods"),
    Sector("other", "Other", "Everything else"),
]
SECTOR_BY_SLUG = {s.slug: s for s in SECTORS}


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.I)


# Step 1: words that settle the sector on their own.
DISTINCTIVE = [
    (
        # Not procurement of work at all: rights, licences and sales.
        "other",
        _rx(
            r"\badverti[sz]\w* rights\b",
            r"\bsale of (scrap|condemned)\b",
            r"\bdisposal of scrap\b",
            r"\brenting out\b",
            r"\blicen[cs]e to operate\b",
            r"\ballotment of (space|shops?)\b",
        ),
    ),
    (
        "security",
        _rx(
            r"\bsecurity (services?|guards?|personnel|agency|staff)\b",
            r"\bcctv\b",
            r"\bsurveillance\b",
            r"\bfire (alarm|fighting|safety|extinguish\w*|detection|hydrant|suppression)\b",
            r"\baccess control\b",
            r"\bmetal detectors?\b",
            r"\bbaggage scanners?\b",
            r"\bsecurity guards?\b",
            r"\bbollards?\b",
        ),
    ),
    (
        "it",
        _rx(
            r"\bsoftware\b",
            r"\bcomputers?\b",
            r"\blaptops?\b",
            r"\bdesktops?\b",
            r"\bservers?\b",
            r"\bnetworking\b",
            r"\b(computer|it|lan|wan|campus|wireless|data) networks?\b",
            r"\bnetwork (switch(es)?|equipment|infrastructure|cabling|devices|security|upgrade)\b",
            r"\bwebsite\b",
            r"\bdata cent(er|re)\b",
            r"\bcyber\b",
            r"\bict\b",
            r"\berp\b",
            r"\bwi-?fi\b",
            r"\boptical fib(er|re)\b",
            r"\bofc\b",
            r"\bit (services|infrastructure|equipment|hardware)\b",
            r"\bprinters?\b",
        ),
    ),
]

# Step 2 / 4: Product Category -> sector. Generic ones only apply after title keywords.
SPECIFIC_CATEGORY = {
    "Civil Works - Highways": "roads",
    "Civil Works - Roads": "roads",
    "Civil Works - Bridges": "roads",
    "Civil Works - Buildings": "buildings",
    "Civil Works - Water Works": "water",
    "Electrical Works": "electrical",
    "Power/Energy Projects/Products": "electrical",
    "Electrical Goods/Equipment": "electrical",
    "Electrical Goods/Equipments": "electrical",
    "Street Lighting": "electrical",
    "Solar Street Lights": "electrical",
    "Air-Conditioner": "electrical",
    "Pipes and Pipe related activities": "water",
    "Pipe Laying Works": "water",
    "Water Supply/Equipments/Meter/Drilling/Boring": "water",
    "Drilling Works": "water",
    "Solid Waste Management": "water",
    "Computer- H/W": "it",
    "Computer- S/W": "it",
    "Computer- Data Processing": "it",
    "Info. Tech. Services": "it",
    "Information Technology": "it",
    "OFC Laying Works": "it",
    "Electronics Equipment": "it",
    "Surveillance Equipments": "security",
    "Fire & Safety": "security",
    "Equipments (Hospital / Lab)": "health",
    "Medical Equipments/Waste": "health",
    "Consumables (Hospital / Lab)": "health",
    "Non Consumables (Hospital / Lab)": "health",
    "Drugs and Pharmaceutical Products": "health",
    "Laboratory and scientific equipment": "lab",
    "Manpower Supply": "facility",
    "Facility Management Services": "facility",
    "Hotel/ Catering": "facility",
    "Hiring of Vehicles": "transport",
    "Vehicles/Vehicle Spares": "transport",
    "Shipping/ Transportation/ Vehicle": "transport",
    "Aviation": "transport",
    "Consultancy": "consultancy",
    "Survey": "consultancy",
    "Stationery": "supplies",
    "Furniture/ Fixture": "supplies",
    "Sports Goods/Equipments": "supplies",
}
GENERIC_CATEGORY = {
    "Civil Works": "buildings",
    "Civil Works - Others": "buildings",
    "Construction Works": "buildings",
    "Miscellaneous Works": "buildings",
    "Civil Construction Goods": "buildings",
    "Paint / Enamel Works": "buildings",
    "Marine Works": "water",
    "Miscellaneous Goods": "supplies",
    "Machineries/ Mechanical Engg Items": "supplies",
    "Mechanical Tools and Equipment": "supplies",
    "Machinery and Machining Tools": "supplies",
    "Electronic Components And Devices": "supplies",
    "Consumables- Raw materials": "supplies",
    "Food Products": "supplies",
    "Metal Fabrication": "supplies",
}

# Step 3: ordered; the first match wins, so specific rules come before broad ones.
KEYWORDS = [
    (
        "facility",
        _rx(
            r"\bhousekeeping\b",
            r"\bmanpower\b",
            r"\bcleaning\b",
            r"\bsweeping\b",
            r"\bscavenging\b",
            r"\boutsourc\w*\b",
            r"\bcatering\b",
            r"\bcanteen\b",
            r"\blaundry\b",
            r"\bhorticultur\w*\b",
            r"\bgardening\b",
            r"\bpest control\b",
            r"\bfacility management\b",
            r"\blawns?\b",
        ),
    ),
    (
        "roads",
        _rx(
            r"\broads?\b",
            r"\bhighways?\b",
            r"\bnh-?\s?\d+",
            r"\bbridges?\b",
            r"\bflyovers?\b",
            r"\bculverts?\b",
            r"\bpavements?\b",
            r"\bcarriageway\b",
            r"\bbituminous\b",
            r"\bblack ?topping\b",
            r"\bexpressway\b",
            r"\bfoot ?(path|over bridge)\b",
            r"\brob\b",
            r"\b(two|four|six|eight|[2468])[- ]?lan(e|es|ing)\b",
            r"\bpaved shoulders?\b",
        ),
    ),
    (
        "water",
        _rx(
            r"\bwater supply\b",
            r"\bpipe ?lines?\b",
            r"\bsewer(age)?\b",
            r"\bsewage\b",
            r"\bdrain(age|s)?\b",
            r"\bsanitation\b",
            r"\bstp\b",
            r"\b(bore|tube) ?wells?\b",
            r"\bwater ?(body|bodies|tank|treatment|works)\b",
            r"\bpumps?\b",
            r"\bplumbing\b",
            r"\bcanals?\b",
            r"\birrigation\b",
            r"\bdesilting\b",
            r"\bwaterbod(y|ies)\b",
        ),
    ),
    (
        "electrical",
        _rx(
            r"\belectric(al|ity)?\b",
            r"\bpower (plant|supply|station)\b",
            r"\bsub-?stations?\b",
            r"\btransformers?\b",
            r"\bsolar\b",
            r"\blighting\b",
            r"\bstreet lights?\b",
            r"\bcables?\b",
            r"\bwiring\b",
            r"\bd\.?g\.? sets?\b",
            r"\bgenerators?\b",
            r"\b\d+\s?kva\b",
            r"\b\d+\s?kwp?\b",
            r"\bair.?condition\w*\b",
            r"\bhvac\b",
            r"\blifts?\b",
            r"\belevators?\b",
            r"\be&m\b",
            r"\bhigh voltage\b",
            r"\brelays?\b",
        ),
    ),
    (
        "health",
        _rx(
            r"\bmedic(al|ine|ines)\b",
            r"\bdrugs?\b",
            r"\bsurgical\b",
            r"\bpharma\w*\b",
            r"\bdiagnostic\b",
            r"\bpatients?\b",
            r"\bambulances?\b",
            r"\bx-?ray\b",
            r"\bmri\b",
            r"\bventilators?\b",
            r"\bdental\b",
            r"\bvaccines?\b",
            r"\bhospital (equipment|consumables|supplies)\b",
            r"\bmgps\b",
            r"\bmedical gas\b",
        ),
    ),
    (
        "lab",
        _rx(
            r"\blaborator(y|ies)\b",
            r"\blab\b",
            r"\bscientific\b",
            r"\bmicroscopes?\b",
            r"\bspectro\w*\b",
            r"\bchromatograph\w*\b",
            r"\breagents?\b",
            r"\bchemicals?\b",
            r"\banaly[sz]ers?\b",
        ),
    ),
    (
        "transport",
        _rx(
            r"\bvehicles?\b",
            r"\btaxis?\b",
            r"\bbuses\b",
            r"\btransportation\b",
            r"\blogistics\b",
            r"\btrucks?\b",
            r"\bhiring of (cars?|jeeps?)\b",
        ),
    ),
    (
        "consultancy",
        _rx(
            r"\bconsultan(cy|ts?)\b",
            r"\bdpr\b",
            r"\bdetailed project report\b",
            r"\bfeasibility\b",
            r"\bsurvey\b",
            r"\bstudy\b",
            r"\baudit\b",
            r"\bproject management\b",
            r"\bpmc\b",
            r"\barchitect\w*\b",
        ),
    ),
    (
        "buildings",
        _rx(
            r"\bbuildings?\b",
            r"\bconstruction\b",
            r"\brenovation\b",
            r"\brepairs?\b",
            r"\bquarters?\b",
            r"\bqtrs?\b",
            r"\bflooring\b",
            r"\bpainting\b",
            r"\bwhite ?washing\b",
            r"\bdistemper\w*\b",
            r"\btoilets?\b",
            r"\bboundary wall\b",
            r"\broof\w*\b",
            r"\bplaster\w*\b",
            r"\bcivil\b",
            r"\bm/o\b",
            r"\bhostels?\b",
            r"\bconservation\b",
            r"\bmonuments?\b",
        ),
    ),
]

CATEGORY_FALLBACK = {"Works": "buildings", "Goods": "supplies"}


def classify(title: str, product_category: str = "", category: str = "") -> str:
    text = title or ""
    for slug, rx in DISTINCTIVE:
        if rx.search(text):
            return slug
    if product_category in SPECIFIC_CATEGORY:
        return SPECIFIC_CATEGORY[product_category]
    for slug, rx in KEYWORDS:
        if rx.search(text):
            return slug
    if product_category in GENERIC_CATEGORY:
        return GENERIC_CATEGORY[product_category]
    return CATEGORY_FALLBACK.get(category, "other")
