
#pylint: disable=all
from openai import OpenAI
from realestate.models import PropertyListing
client = OpenAI()
from pgvector.django import CosineDistance
from asgiref.sync import sync_to_async
from django.utils import timezone
from agents import Agent, Runner
from realestate.models import Lead, ConversationMessage
import json

from asgiref.sync import async_to_sync


def format_conversation_messages(messages):
    formatted_strings = []
    for msg in messages:
        formatted_strings.append(
            f"[{msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {msg.sender_type}: {msg.message_text}"
        )
    return "\n".join(formatted_strings)

def extract_lead_data_async(lead_id, lead=None):
    lead = lead if lead else Lead.objects.get(id=lead_id)
    messages = ConversationMessage.objects.filter(conversation_id=lead.instagram_conversation_id).order_by("timestamp")
    conversation_text = format_conversation_messages(messages)

    agent = Agent(
    name="Lead Data Extractor",
    model="gpt-4-turbo",
    instructions="""
You are an AI assistant that reads a real estate chat conversation and extracts structured lead data.
Output a single valid JSON object **only**, with the following fields:

REQUIRED FIELDS:
- customer_name: string or null
- phone_number: string (digits, include country code if possible) or null
- email: string or null
- preferred_location: string or null
- budget_min: number or null
- budget_max: number or null
- timeline: one of ["immediate", "short", "medium", "long", "just_browsing"] or null
- payment_method: one of ["cash", "loan", "both", "unknown"]
- property_requirements: JSON object (example: {"bedrooms": 2, "bathrooms": 2, "area_sqft": 1200}) or empty object {}
- intent_level: one of ["low", "medium", "high", "hot"] or null
- qualification_status: one of ["initiated", "in_progress", "qualified", "unqualified", "no_response", "ready_for_agent"]
- status: one of ["active", "qualified_hot", "qualified_warm", "qualified_cold", "unqualified", "spam", "closed_won", "closed_lost"]
- ai_conversation_summary: string, concise summary of user conversation

EXTRACTION RULES:

1. Output only valid JSON. No extra text outside the JSON object.
2. If a field value is unknown, use null (not empty string).
3. property_requirements must be an object, even if empty {}.
4. Always include all fields.
5. All numbers must be valid JSON numbers (not strings).

QUALIFICATION LOGIC (Critical):

Set qualification_status based on conversation analysis:
- "initiated" → Just started talking, minimal info
- "in_progress" → Has provided some info (name, location, or timeline mentioned)
- "qualified" → Has name/phone + at least 2 of: budget + location + property type + timeline
- "unqualified" → Explicitly not interested, spam, or rude
- "no_response" → They stopped responding mid-conversation
- "ready_for_agent" → Qualified + phone number present → MARK THIS FOR HANDOFF

Set status based on engagement and qualification:
- "active" → Actively chatting, responding well
- "qualified_hot" → Has phone + budget + location + timeline → HOT LEAD (ready for immediate agent follow-up)
- "qualified_warm" → Has phone + 2-3 of (budget/location/timeline/property type) → Warm lead
- "qualified_cold" → Has basic info but vague on budget/timeline → Cold lead
- "unqualified" → Not interested or spam
- "spam" → Irrelevant messages, multiple requests, suspicious behavior
- "closed_won" → Lead converted/property bought (if mentioned)
- "closed_lost" → Explicitly said not interested or stopped responding

INTENT LEVEL MAPPING (based on what they say and ask):
- "low" → Passive browsing, no urgency, vague responses
- "medium" → Interested but still exploring, some hesitation
- "high" → Active interest, asking specific questions, has preferences
- "hot" → Very engaged, phone provided, clear budget/timeline, ready to move forward

TIMELINE INTERPRETATION:
- immediate → "ASAP", "this month", "URGENTLY", "right now"
- short → "next month", "1-3 months", "soon", "Q1"
- medium → "3-6 months", "half year", "this year"
- long → "6+ months", "next year", "taking time"
- just_browsing → "just looking", "exploring", "browsing", "no rush"

PROPERTY REQUIREMENTS:
Extract these if mentioned:
- bedrooms: number
- bathrooms: number
- area_sqft: number
- property_type: "apartment", "villa", "land", "builder floor", etc.
- amenities: ["list", "of", "amenities"] if mentioned
- furnished: "furnished", "semi-furnished", "unfurnished"

EXAMPLE OUTPUT:

{
    "customer_name": "John Doe",
    "phone_number": "+911234567890",
    "email": "johndoe@example.com",
    "preferred_location": "Bangalore, Whitefield",
    "budget_min": 5000000,
    "budget_max": 8000000,
    "timeline": "short",
    "payment_method": "loan",
    "property_requirements": {"bedrooms": 3, "bathrooms": 2, "area_sqft": 1500, "property_type": "apartment"},
    "intent_level": "high",
    "qualification_status": "ready_for_agent",
    "status": "qualified_hot",
    "ai_conversation_summary": "John is looking for a 3BHK apartment in Whitefield, budget 50-80L, wants to buy in 1-3 months using home loan. Very engaged, provided phone number. Ready for agent follow-up."
}

SPECIAL CASES:

1. If they provide phone + budget + location + clear timeline → ALWAYS "qualified_hot" and "ready_for_agent"
2. If vague on all fronts but engaging → "in_progress" and "active"
3. If they say "just browsing" → "qualified_cold" at best, never "hot"
4. If conversation died out → "no_response" but keep "active" status if recent
5. If they're rude or irrelevant → "unqualified" and "spam"

Now analyze the following conversation and produce a JSON strictly matching the fields above.
""",
)

    # Run the async agent synchronously
    result = async_to_sync(Runner.run)(agent, input=conversation_text)


    try:
        lead_update = json.loads(result.final_output)  # parse string to dict
    except json.JSONDecodeError:
        print("❌ Failed to parse agent output as JSON:", result.final_output)
        lead_update = {}

    if lead_update:
        changed = False
        for field, value in lead_update.items():
            if value is not None and hasattr(lead, field):
                setattr(lead, field, value)
                changed = True
        if changed:
            lead.last_interaction_at = timezone.now()
            print("✅ Lead updated with", lead_update)
            lead.save()


def summarize_property(listing: PropertyListing) -> str:
    """Create a concise but complete text summary for LLM context."""
    summary = (
        f"🏡 {listing.title}\n"
        f"Type: {listing.get_property_type_display()} | Status: {listing.get_status_display()}\n"
        f"Location: {listing.location}\n"
        f"Company: {listing.company.name if hasattr(listing, 'company') else '-'}\n"
        f"Price: {listing.price or '-'} {listing.currency} ({listing.get_price_type_display()})\n"
        f"Bedrooms: {listing.bedrooms or '-'} | Bathrooms: {listing.bathrooms or '-'}\n"
        f"Area: {listing.area_sqft or '-'} sqft\n"
        f"Land Area: {listing.land_area or '-'} {listing.land_unit or '-'}\n"
        f"Amenities: {listing.amenities or '-'}\n\n"
        f"Description: {(listing.description[:400] + '...') if listing.description and len(listing.description) > 400 else (listing.description or '-')}\n\n"
        f"Additional Info: {listing.ai_context_notes or '-'}\n"
        f"Created: {listing.created_at.strftime('%Y-%m-%d %H:%M:%S') if listing.created_at else '-'} | "
        f"Updated: {listing.updated_at.strftime('%Y-%m-%d %H:%M:%S') if listing.updated_at else '-'}"
    )
    return summary

def find_relevant_properties(user_message, limit=10):
    """Find the most semantically similar properties to a user's query."""
    client = OpenAI()
    query_embedding = client.embeddings.create(
        model="text-embedding-3-large",
        input=user_message
    ).data[0].embedding

    listings = (
        PropertyListing.objects
        .exclude(embedding=None)
        .annotate(similarity=CosineDistance("embedding", query_embedding))
        .order_by("similarity")[:limit]
    )

    # Return full summaries for context feeding
    return [summarize_property(l) for l in listings]


def parse_instagram_payload(data: dict):
    try:
        response = {"webhook_type": "unknown"}
        entry = data.get("entry", [])
        if not entry:
            return response
        latest_entry = entry[0]
        if not latest_entry:
            return response
        if "messaging" in latest_entry:
            message_data = latest_entry["messaging"][0]
            response["webhook_type"] = "message"
            response["sender"] = message_data["sender"]["id"]
            response["sender_username"] = message_data["sender"]["id"]
            response["recipient"] = message_data["recipient"]["id"]
            response["message"] = message_data["message"]["text"]
            response["message_id"] = message_data["message"]["mid"]
            return response
        if "changes" in latest_entry:
            comment_data = latest_entry["changes"][0]
            response["webhook_type"] = "comment"
            response["recipient"] = latest_entry["id"]
            response["sender"] = comment_data["value"]["from"]["id"]
            response["sender_username"] = comment_data["value"]["from"]["username"]
            response["post_id"] = comment_data["value"]["media"]["id"]
            response["parent_id"] = comment_data["value"].get("parent_id","")
            response["comment_id"] = comment_data["value"]["id"]
            response["post_type"] = comment_data["value"]["media"]["media_product_type"]
            response["comment_text"] = comment_data["value"]["text"]
            return response
        return response
    except Exception as error:
        print("Error on webhook data parse", error)
        return {"webhook_type": "unknown"}