import logging
import re

from mcp.server.fastmcp import FastMCP

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medvero-mcp")

mcp = FastMCP("MedVero-MCP")

# Simulated Medical Reference Database
DRUG_DATABASE = {
    "acetaminophen": {
        "brand_names": ["tylenol", "paracetamol"],
        "class": "Analgesic / Antipyretic",
        "description": "Used to treat mild to moderate pain and reduce fever.",
        "max_daily_dose_mg": 4000.0,
        "standard_frequency": "Every 4-6 hours as needed",
        "route": "oral",
        "contraindications": ["severe liver disease", "liver failure", "alcoholism"],
        "interactions": {
            "alcohol": "Major risk of hepatotoxicity (severe liver damage). Avoid concurrent consumption.",
            "warfarin": "Moderate risk. Chronic high-dose acetaminophen may increase bleeding risk."
        }
    },
    "ibuprofen": {
        "brand_names": ["advil", "motrin"],
        "class": "Nonsteroidal Anti-inflammatory Drug (NSAID)",
        "description": "Used to reduce hormones that cause pain and inflammation in the body.",
        "max_daily_dose_mg": 3200.0,
        "standard_frequency": "Every 4-6 hours",
        "route": "oral",
        "contraindications": ["active peptic ulcer", "severe kidney disease", "kidney failure", "severe heart failure", "pregnancy (third trimester)"],
        "interactions": {
            "aspirin": "Moderate risk. Concomitant use decreases cardioprotective effects of aspirin and increases GI bleeding risk.",
            "lisinopril": "Moderate risk. NSAIDs may decrease the antihypertensive effect of ACE inhibitors and increase risk of renal impairment.",
            "warfarin": "Major risk. Concurrent use increases the risk of severe gastrointestinal bleeding.",
            "alcohol": "Increased risk of gastrointestinal irritation and bleeding."
        }
    },
    "lisinopril": {
        "brand_names": ["prinivil", "zestril"],
        "class": "ACE Inhibitor",
        "description": "Used to treat high blood pressure (hypertension), congestive heart failure, and improve survival after a heart attack.",
        "max_daily_dose_mg": 40.0,
        "standard_frequency": "Once daily",
        "route": "oral",
        "contraindications": ["history of angioedema", "pregnancy", "bilateral renal artery stenosis"],
        "interactions": {
            "potassium": "Moderate risk. Lisinopril increases potassium levels; supplements can cause severe hyperkalemia.",
            "spironolactone": "Moderate risk. Co-administration can lead to hyperkalemia.",
            "ibuprofen": "NSAIDs can decrease blood pressure control and increase kidney injury risk."
        }
    },
    "metformin": {
        "brand_names": ["glucophage"],
        "class": "Biguanide (Antidiabetic)",
        "description": "First-line medication for the treatment of type 2 diabetes.",
        "max_daily_dose_mg": 2550.0,
        "standard_frequency": "With meals twice daily",
        "route": "oral",
        "contraindications": ["severe renal impairment", "renal failure", "metabolic acidosis", "diabetic ketoacidosis"],
        "interactions": {
            "alcohol": "Major risk. Increases the risk of lactic acidosis, a rare but life-threatening complication.",
            "contrast dye": "Major risk. Intravenous contrast media can cause temporary renal failure, leading to metformin accumulation and lactic acidosis."
        }
    },
    "amoxicillin": {
        "brand_names": ["amoxil", "moxatag"],
        "class": "Penicillin Antibiotic",
        "description": "Used to treat many different types of infection caused by bacteria.",
        "max_daily_dose_mg": 3000.0,
        "standard_frequency": "Every 8 or 12 hours",
        "route": "oral",
        "contraindications": ["penicillin allergy", "history of cholestatic jaundice or hepatic dysfunction associated with amoxicillin"],
        "interactions": {
            "methotrexate": "Moderate risk. Penicillins may decrease clearance of methotrexate, increasing risk of toxicity.",
            "oral contraceptives": "Minor/Debated risk. May slightly reduce effectiveness of birth control pills; backup contraception recommended."
        }
    }
}

CLINICAL_EVIDENCE = [
    {
        "keywords": ["acetaminophen", "liver", "damage", "alcohol"],
        "text": "According to FDA warnings and clinical studies, combining therapeutic doses of acetaminophen with chronic alcohol consumption (3 or more drinks daily) significantly increases the risk of acute liver failure. Standard packaging labels recommend avoiding alcohol entirely while taking acetaminophen.",
        "source": "FDA Safety Communication (2023) / DailyMed Reference"
    },
    {
        "keywords": ["ibuprofen", "peptic", "ulcer", "bleeding"],
        "text": "A meta-analysis published in the American Journal of Medicine indicates that NSAIDs like ibuprofen increase the risk of serious upper gastrointestinal bleeding or peptic ulcers by 3 to 5 fold. This risk is highly elevated in patients with a history of peptic ulcers or concurrent warfarin use.",
        "source": "AJM Gastroenterology Guidelines (2022)"
    },
    {
        "keywords": ["lisinopril", "pregnancy", "fetal"],
        "text": "Lisinopril is contraindicated during pregnancy due to the risk of fetal toxicity. Drugs that act on the renin-angiotensin system can cause injury and death to the developing fetus, particularly during the second and third trimesters.",
        "source": "FDA Boxed Warning for ACE Inhibitors"
    },
    {
        "keywords": ["metformin", "lactic", "acidosis", "renal"],
        "text": "Metformin-associated lactic acidosis (MALA) is a rare but serious metabolic complication (mortality rate up to 50%). It occurs almost exclusively in patients with significant renal impairment. The FDA contraindicates metformin in patients with an eGFR below 30 mL/min/1.73m².",
        "source": "ADA Clinical Practice Recommendations (2024)"
    },
    {
        "keywords": ["ibuprofen", "lisinopril", "kidney"],
        "text": "Concomitant administration of NSAIDs (like ibuprofen) and ACE inhibitors (like lisinopril) has been associated with acute kidney injury, particularly in elderly or volume-depleted patients. NSAIDs inhibit renal prostaglandins, causing afferent arteriolar vasoconstriction, while ACE inhibitors cause efferent vasodilation, compromising glomerular filtration.",
        "source": "NEJM Nephrology Review (2021)"
    }
]

def _normalize_name(name: str) -> str:
    """Normalize drug or condition name for lookup."""
    name_clean = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
    for canonical, data in DRUG_DATABASE.items():
        if name_clean == canonical:
            return canonical
        for brand in data["brand_names"]:
            if name_clean == brand:
                return canonical
    return name_clean

def _parse_dosage_to_mg(dosage_str: str) -> float:
    """Helper to convert dosage strings (e.g. 500mg, 1g) to mg."""
    dosage_str = dosage_str.lower().strip()
    match = re.search(r'([\d\.]+)\s*(mg|g|mcg|micrograms)', dosage_str)
    if not match:
        return 0.0
    val = float(match.group(1))
    unit = match.group(2)
    if unit == 'g':
        return val * 1000.0
    elif unit in ('mcg', 'micrograms'):
        return val / 1000.0
    return val

@mcp.tool()
def fetch_drug_info(drug_name: str) -> str:
    """Retrieve details about a drug including class, standard usage, and safety categories.
    
    Args:
        drug_name: The name of the drug (brand or generic).
    """
    logger.info(f"fetch_drug_info called with: {drug_name}")
    norm = _normalize_name(drug_name)
    if norm in DRUG_DATABASE:
        data = DRUG_DATABASE[norm]
        return (
            f"Drug: {norm.capitalize()}\n"
            f"Class: {data['class']}\n"
            f"Description: {data['description']}\n"
            f"Max Daily Dose: {data['max_daily_dose_mg']} mg\n"
            f"Standard Frequency: {data['standard_frequency']}\n"
            f"Route: {data['route'].capitalize()}"
        )
    return f"Drug '{drug_name}' not found in the reference database. Standard safety verification is advised."

@mcp.tool()
def check_drug_interactions(drugs: list[str]) -> str:
    """Checks for known drug-drug interactions between two or more drugs.
    
    Args:
        drugs: List of drug names to check.
    """
    logger.info(f"check_drug_interactions called with: {drugs}")
    normalized_drugs = [_normalize_name(d) for d in drugs]
    warnings = []

    # Check pairwise interactions
    for i in range(len(normalized_drugs)):
        for j in range(i + 1, len(normalized_drugs)):
            d1, d2 = normalized_drugs[i], normalized_drugs[j]

            # Check database for d1 -> d2
            if d1 in DRUG_DATABASE and d2 in DRUG_DATABASE[d1]["interactions"]:
                warnings.append(f"[{d1.capitalize()} + {d2.capitalize()}]: {DRUG_DATABASE[d1]['interactions'][d2]}")
            # Check database for d2 -> d1
            elif d2 in DRUG_DATABASE and d1 in DRUG_DATABASE[d2]["interactions"]:
                warnings.append(f"[{d2.capitalize()} + {d1.capitalize()}]: {DRUG_DATABASE[d2]['interactions'][d1]}")

    if warnings:
        return "\n".join(warnings)
    return "No major interactions detected between the provided medications in our reference database."

@mcp.tool()
def fetch_contraindications(drug_name: str, health_conditions: list[str]) -> str:
    """Checks if a drug is contraindicated for a list of health conditions.
    
    Args:
        drug_name: The name of the drug.
        health_conditions: List of patient's health conditions.
    """
    logger.info(f"fetch_contraindications called with: {drug_name}, {health_conditions}")
    norm_drug = _normalize_name(drug_name)
    if norm_drug not in DRUG_DATABASE:
        return f"Drug '{drug_name}' not found in the reference database. Cannot check contraindications."

    contraindications = DRUG_DATABASE[norm_drug]["contraindications"]
    matches = []
    for condition in health_conditions:
        cond_lower = condition.lower()
        for contra in contraindications:
            if contra in cond_lower or cond_lower in contra:
                matches.append(f"Warning: {norm_drug.capitalize()} is contraindicated in patients with {contra}.")

    if matches:
        return "\n".join(matches)
    return f"No contraindications found for {drug_name} based on the provided conditions: {health_conditions}."

@mcp.tool()
def retrieve_medical_evidence(claim: str) -> str:
    """Looks up clinical and FDA databases for medical evidence matching a claim.
    
    Args:
        claim: The clinical statement or claims description.
    """
    logger.info(f"retrieve_medical_evidence called with: {claim}")
    claim_lower = claim.lower()
    matches = []

    for item in CLINICAL_EVIDENCE:
        # Match if at least two keywords are present in the claim
        keyword_hits = sum(1 for kw in item["keywords"] if kw in claim_lower)
        if keyword_hits >= 2:
            matches.append(f"Evidence: {item['text']}\nSource: {item['source']}")

    if matches:
        return "\n\n".join(matches)
    return "No direct matching clinical evidence found. The claim is unverified by our primary databases."

@mcp.tool()
def validate_dosage(drug_name: str, dosage: str, frequency: str, duration: str) -> str:
    """Validates if the drug dosage details exceed standard adult limits.
    
    Args:
        drug_name: The name of the drug.
        dosage: Single dose strength (e.g. 500mg, 1g).
        frequency: How often it is taken (e.g. 3 times daily, daily, every 4 hours).
        duration: Duration of treatment (e.g. 5 days).
    """
    logger.info(f"validate_dosage called with: {drug_name}, {dosage}, {frequency}, {duration}")
    norm_drug = _normalize_name(drug_name)
    if norm_drug not in DRUG_DATABASE:
        return f"Drug '{drug_name}' not found in database. Unable to perform dosage validation."

    single_mg = _parse_dosage_to_mg(dosage)
    if single_mg == 0.0:
        return f"Could not parse single dosage '{dosage}' to a numerical value in mg."

    # Estimate times per day from frequency
    freq_lower = frequency.lower()
    times_per_day = 1.0
    if "every 4" in freq_lower:
        times_per_day = 6.0
    elif "every 6" in freq_lower:
        times_per_day = 4.0
    elif "every 8" in freq_lower or "three times" in freq_lower or "tid" in freq_lower:
        times_per_day = 3.0
    elif "twice" in freq_lower or "bid" in freq_lower or "every 12" in freq_lower:
        times_per_day = 2.0
    elif "four times" in freq_lower or "qid" in freq_lower:
        times_per_day = 4.0
    elif "once" in freq_lower or "daily" in freq_lower or "qd" in freq_lower:
        times_per_day = 1.0

    daily_mg = single_mg * times_per_day
    max_daily = DRUG_DATABASE[norm_drug]["max_daily_dose_mg"]

    if daily_mg > max_daily:
        return (
            f"WARNING: Dosage limit exceeded! Extrapolated daily dose is {daily_mg} mg "
            f"({single_mg} mg x {times_per_day} times/day), which exceeds the recommended "
            f"maximum daily dose of {max_daily} mg for {norm_drug.capitalize()}."
        )
    return (
        f"Dosage check passed. Extrapolated daily dose is {daily_mg} mg "
        f"({single_mg} mg x {times_per_day} times/day), which is within the safe limit of "
        f"{max_daily} mg for {norm_drug.capitalize()}."
    )

if __name__ == "__main__":
    mcp.run()
