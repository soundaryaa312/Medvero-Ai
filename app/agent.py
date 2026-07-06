# ruff: noqa
import datetime
import json
import logging
import re
from typing import Any
from pydantic import BaseModel, Field
from google.adk.agents import Agent
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.workflow import Workflow, node
from google.genai import types
from app.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medvero-agent")

model_wrapper = Gemini(
    model=config.model,
    retry_options=types.HttpRetryOptions(attempts=3),
)

# ==========================================
# Pydantic Model
# ==========================================

class MedicalEvaluationReport(BaseModel):
    summary: str = Field(description="Brief summary of the user's medication question.")
    what_we_found: str = Field(description="Evidence-based evaluation of the medication claim or interaction.")
    why: str = Field(description="Simple explanation based on trusted medical evidence.")
    risk_level: str = Field(description="Risk Level: Low, Moderate, High, or Not Enough Information.")
    recommendation: str = Field(description="Short, safe recommendation encouraging professional medical advice when appropriate.")
    confidence: str = Field(description="Realistic confidence percentage (e.g. 95%).")

# ==========================================
# Shared Instructions Prompt
# ==========================================

SHARED_PROMPT = """You are MedVero AI, an intelligent Medical Information Evaluation Assistant.
Your goal is to evaluate the user's query or medical content accurately, safely, and in simple English.

Directly evaluate the query and output the MedicalEvaluationReport.

Rules:
1. Identify medicines, diseases, symptoms, treatments, dosages, and medical claims.
2. If the query is NOT medical or not medication-related, set risk_level to "Not Enough Information", confidence to "100%", and other fields appropriately.
3. For medication-related queries:
   - Provide a brief summary of the medication question.
   - Give an evidence-based evaluation of the claim or interaction.
   - Explain the mechanism ("Why?") in simple language.
   - Assess the Risk Level: Low, Moderate, or High.
   - Provide a safe recommendation (never diagnose, prescribe, or recommend starting/stopping medicines).
   - Assign a realistic confidence percentage (e.g., 95%).
4. Keep the text concise to reduce token usage.
5. Do not generate markdown, JSON examples, code blocks, or conversational text outside the schema.
"""

# ==========================================
# Five Logical Agents
# ==========================================

claims_extractor = Agent(
    name="claims_extractor",
    model=model_wrapper,
    instruction=SHARED_PROMPT,
    output_schema=MedicalEvaluationReport,
)

evidence_verifier = Agent(
    name="evidence_verifier",
    model=model_wrapper,
    instruction=SHARED_PROMPT,
    output_schema=MedicalEvaluationReport,
)

drug_safety = Agent(
    name="drug_safety",
    model=model_wrapper,
    instruction=SHARED_PROMPT,
    output_schema=MedicalEvaluationReport,
)

report_generator = Agent(
    name="report_generator",
    model=model_wrapper,
    instruction=SHARED_PROMPT,
    output_schema=MedicalEvaluationReport,
)

orchestrator = Agent(
    name="orchestrator",
    model=model_wrapper,
    instruction=SHARED_PROMPT,
    output_schema=MedicalEvaluationReport,
)

# ==========================================
# Workflow Nodes
# ==========================================

def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    """PII scrubbing, injection detection, and audit logging."""
    if hasattr(node_input, "query"):
        query = node_input.query
    elif hasattr(node_input, "parts") and node_input.parts:
        query = node_input.parts[0].text
    elif isinstance(node_input, dict):
        query = node_input.get("query", node_input.get("text", str(node_input)))
    else:
        query = str(node_input)

    scrubbed = query
    scrubbed = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "[PHONE REDACTED]", scrubbed)
    scrubbed = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', "[ID REDACTED]", scrubbed)
    scrubbed = re.sub(r'\bPAT-\d{4,8}\b', "[ID REDACTED]", scrubbed)

    injection_kw = ["ignore previous instructions", "system prompt", "bypass", "override", "you are no longer"]
    unsafe_kw = ["lethal dose", "suicide", "self-harm", "overdose intentionally"]
    blocked = any(kw in query.lower() for kw in injection_kw + unsafe_kw)

    audit = {
        "timestamp": datetime.datetime.now().isoformat(),
        "severity": "CRITICAL" if blocked else "INFO",
        "verdict": "REJECTED" if blocked else "APPROVED",
        "query_preview": query[:60],
    }
    if blocked:
        logger.warning(f"SECURITY: {json.dumps(audit)}")
        return Event(output=json.dumps(audit), route="security_event")

    logger.info(f"SECURITY: {json.dumps(audit)}")
    return Event(output=scrubbed, route="continue", state={"scrubbed_query": scrubbed})


def security_event_handler(node_input: Any) -> MedicalEvaluationReport:
    """Returns a blocked-input report."""
    return MedicalEvaluationReport(
        summary="Blocked security input.",
        what_we_found="Input was flagged by the security layer.",
        why="Security violations or potential prompt injection/unsafe keywords detected.",
        risk_level="Not Enough Information",
        recommendation="Please submit a genuine medication-related question for evaluation.",
        confidence="0%",
    )


@node(rerun_on_resume=True)
async def check_confidence(ctx: Context, node_input: Any):
    """HITL pause for low-confidence reports."""
    if isinstance(node_input, dict):
        data = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        try:
            parsed = json.loads(node_input.parts[0].text)
            data = parsed if isinstance(parsed, dict) else {"why": node_input.parts[0].text}
        except Exception:
            data = {"why": str(node_input.parts[0].text)}
    else:
        data = {"why": str(node_input)}

    # Apply fallbacks
    data.setdefault("summary", "Query analysis")
    data.setdefault("what_we_found", "No medical evaluation performed.")
    data.setdefault("why", "")
    data.setdefault("risk_level", "Not Enough Information")
    data.setdefault("recommendation", "Consult a healthcare professional.")
    data.setdefault("confidence", "95%")

    conf_str = data.get("confidence", "95%")
    match = re.search(r'\d+', conf_str)
    try:
        confidence_val = float(match.group(0)) / 100.0 if match else 0.95
    except Exception:
        confidence_val = 0.95

    if confidence_val < config.min_confidence and "clinician_review" not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="clinician_review",
            message=f"Low confidence ({conf_str}). Please provide professional clinical guidance to override."
        )
        return

    if "clinician_review" in ctx.resume_inputs:
        notes = ctx.resume_inputs["clinician_review"]
        data["recommendation"] = data.get("recommendation", "") + f"\n\n[Clinical Note]: {notes}"
        data["confidence"] = "95%"
        data["risk_level"] = "Approved"

    yield Event(output=data)

@node()
async def final_output(ctx: Context, node_input: dict):
    """Formats and emits the final evaluation report in the requested layout."""
    query = ctx.state.get("scrubbed_query", "User Question")
    
    report_text = (
        f"Medical Query\n\n"
        f"\"{query}\"\n\n"
        f"Summary\n"
        f"{node_input.get('summary', '')}\n\n"
        f"What We Found\n"
        f"{node_input.get('what_we_found', '')}\n\n"
        f"Why?\n"
        f"{node_input.get('why', '')}\n\n"
        f"Risk Level\n"
        f"{node_input.get('risk_level', '')}\n\n"
        f"Recommendation\n"
        f"{node_input.get('recommendation', '')}\n\n"
        f"Confidence\n"
        f"{node_input.get('confidence', '')}\n\n"
        f"Note\n"
        f"This information is for educational purposes only and is not a substitute for professional medical advice."
    )
    
    # 1. Output the clean markdown card block explicitly to the user path
    yield Event(content=types.Content(role="model", parts=[types.Part.from_text(text=report_text)]))
    
    # 2. Output the verified structural payload data back into the validation engine
    yield Event(output=node_input)
# ==========================================
# Workflow Graph
# ==========================================

root_agent = Workflow(
    name="medvero_ai",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {"security_event": security_event_handler, "continue": orchestrator}),
        (orchestrator, check_confidence),
        (check_confidence, final_output),
    ],
    output_schema=MedicalEvaluationReport,
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(enabled=True),
)
