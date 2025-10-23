
#pylint: disable=all
from openai import OpenAI
from realestate.models import PropertyListing
client = OpenAI()
from pgvector.django import CosineDistance



import threading
from asgiref.sync import sync_to_async
from django.utils import timezone
from agents import Agent, Runner
from realestate.models import Lead, ConversationMessage
import json

from asgiref.sync import async_to_sync

def extract_lead_data_async(lead_id, lead=None):
    lead = lead if lead else Lead.objects.get(id=lead_id)
    messages = ConversationMessage.objects.filter(conversation_id=lead.instagram_conversation_id).order_by("timestamp")
    conversation_text = "\n".join([m.message_text for m in messages])

    agent = Agent(
        name="Lead Data Extractor",
        model="gpt-4-turbo",
        instructions="""
    You are an AI assistant that reads a real estate chat conversation and extracts structured lead data.
    Output a single valid JSON object **only**, with the following fields:

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
    - summary: string, concise summary of user conversation

    Rules:
    1. Output only JSON. Do not include any extra text or explanations outside the JSON object.
    2. If a field value is unknown, use null (not empty string).
    3. property_requirements must be an object even if empty.
    4. Always include all fields.
    5. All numbers must be valid JSON numbers (not strings).

    Example output:

    {
        "customer_name": "John Doe",
        "phone_number": "+911234567890",
        "email": "johndoe@example.com",
        "preferred_location": "Bangalore, Whitefield",
        "budget_min": 5000000,
        "budget_max": 8000000,
        "timeline": "short",
        "payment_method": "loan",
        "property_requirements": {"bedrooms": 3, "bathrooms": 2, "area_sqft": 1500},
        "intent_level": "high",
        "qualification_status": "in_progress",
        "summary": "User is looking for a 3BHK apartment in Whitefield within 5-8M INR, wants to buy in 1-3 months using a home loan."
    }

    Now analyze the following conversation and produce a JSON strictly matching the fields above.
    """
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
    """Create a concise text summary for LLM context."""
    summary = (
        f"🏡 {listing.title}\n"
        f"Type: {listing.property_type}, Status: {listing.status}\n"
        f"Location: {listing.location}\n"
        f"Price: {listing.price} {listing.currency} ({listing.price_type})\n"
        f"Bedrooms: {listing.bedrooms or '-'}, Bathrooms: {listing.bathrooms or '-'}\n"
        f"Area: {listing.area_sqft or '-'} sqft\n"
        f"Amenities: {listing.amenities or '-'}\n"
        f"Description: {listing.description[:300] if listing.description else '-'}"
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