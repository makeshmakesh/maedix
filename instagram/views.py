# pylint:disable=all
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.urls import reverse
from datetime import datetime, timedelta
from .models import InstagramAccount
from realestate.models import (
    Company,
    Lead,
    ConversationMessage,
    PropertyListing,
    Membership,
)
from core.models import Configuration
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
import logging
import urllib.parse
import os

logger = logging.getLogger(__name__)
from realestate.models import Company, Lead
from django.utils import timezone
from typing import List, Optional
from asgiref.sync import sync_to_async
from asgiref.sync import async_to_sync
from agents import Agent, Runner
import threading
from .utils import extract_lead_data_async


class MyCustomSession:
    """Custom session backed by the ConversationMessage model."""

    def __init__(self, conversation_id: str, lead):
        self.conversation_id = conversation_id
        self.lead = lead

    async def get_items(self, limit: Optional[int] = None) -> List[dict]:
        """Retrieve messages for this conversation."""
        queryset = ConversationMessage.objects.filter(
            conversation_id=self.conversation_id
        ).order_by("timestamp")
        if limit:
            queryset = queryset[:limit]
        messages = await sync_to_async(list)(queryset)
        res = []
        for m in messages:
            if m.message_text:
                res.append({"role": m.sender_type, "content": m.message_text})
        return res

    async def add_items(self, items: List[dict]) -> None:
        """Store new messages."""
        objs = []
        for item in items:
            if not item.get("message_text", ""):
                continue
            objs.append(
                ConversationMessage(
                    lead=self.lead,
                    conversation_id=self.conversation_id,
                    sender_type=item.get("sender_type", "assistant"),
                    message_text=item.get("message_text", ""),
                    message_type=item.get("message_type", "follow_up"),
                    extracted_data=item.get("extracted_data", {}),
                    confidence_score=item.get("confidence_score"),
                    is_from_instagram=item.get("is_from_instagram", False),
                    instagram_message_id=item.get("instagram_message_id", None),
                )
            )
        await sync_to_async(ConversationMessage.objects.bulk_create)(objs)

    async def pop_item(self) -> Optional[dict]:
        """Remove and return the latest message."""
        latest = await sync_to_async(
            lambda: ConversationMessage.objects.filter(
                conversation_id=self.conversation_id
            )
            .order_by("-timestamp")
            .first()
        )()
        if not latest:
            return None
        data = {
            "sender_type": latest.sender_type,
            "message_text": latest.message_text,
            "timestamp": latest.timestamp.isoformat(),
            "message_type": latest.message_type,
        }
        await sync_to_async(latest.delete)()
        return data

    async def clear_session(self) -> None:
        """Delete all messages for this conversation."""
        await sync_to_async(
            lambda: ConversationMessage.objects.filter(
                conversation_id=self.conversation_id
            ).delete()
        )()


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
            response["recipient"] = message_data["recipient"]["id"]
            response["message"] = message_data["message"]["text"]
            response["message_id"] = message_data["message"]["mid"]
            return response
        if "changes" in latest_entry:
            comment_data = latest_entry["changes"][0]
            response["webhook_type"] = "comment"
            response["sender"] = comment_data["value"]["from"]["id"]
            response["sender_username"] = comment_data["value"]["from"]["username"]
            response["post_id"] = comment_data["value"]["media"]["id"]
            response["post_type"] = comment_data["value"]["media"]["media_product_type"]
            response["comment_text"] = comment_data["value"]["text"]
            return response
        return response
    except Exception as error:
        print("Error on webhook data parse", error)
        return {"webhook_type": "unknown"}


from .utils import find_relevant_properties


@method_decorator(csrf_exempt, name="dispatch")
class InstagramWebHookView(View):

    def update_lead_from_ai(self, lead, update_data: dict):
        changed = False
        for field, value in update_data.items():
            if value is not None and hasattr(lead, field):
                setattr(lead, field, value)
                changed = True

        # Optionally update summary and timestamp
        if update_data.get("summary"):
            lead.ai_conversation_summary = update_data["summary"]
        if changed:
            lead.last_interaction_at = timezone.now()
            lead.save()

    def get(self, request):
        token_sent = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if token_sent == VERIFY_TOKEN:
            return HttpResponse(challenge)
        return HttpResponse("Invalid verification token", status=403)

    async def get_reply_from_llm_async(self, conversation_id, user_message):
        """Uses OpenAI Agent to get a contextual LLM reply."""
        session = MyCustomSession(conversation_id, self.lead)
        context_snippets = await sync_to_async(find_relevant_properties)(user_message)
        context_text = "\n".join(context_snippets)
        messages = await session.get_items()
        print("History going to LLM:", messages)
        agent = Agent(
    name="Instagram Real Estate Assistant",
    model="gpt-4-turbo",
    instructions=f"""
You are a friendly, helpful real estate assistant for {self.company.name}, 
chatting with potential buyers on Instagram DMs.

YOUR PERSONALITY:
- Warm, conversational, and genuine — like a real team member, not a bot
- Keep responses short and natural (2-3 sentences max per message)
- Mirror the user's energy and tone
- Use their name when they share it
- Be helpful and proactive, not pushy

YOUR GOAL:
Have a natural conversation while collecting these key details naturally:
- Name
- Phone number (priority — ask once early , if not shared, ask again in different way later in conversation, but don't miss it)
- Budget range
- Preferred location/neighborhood
- Property type and requirements (bedrooms, sqft, amenities)
- Timeline (when they want to buy)
- Payment method (cash/loan/both)
- First-time buyer status
- Whether they own/need to sell another property
- Email (optional, for follow-up)

CONVERSATION FLOW (ONE QUESTION AT A TIME):

**Message 1-2: Greeting**
- Welcome them warmly
- Example: "Hey! Thanks for reaching out! 👋 what is your name?"

**Message 3: Phone Number (ASK ONCE)**
- After they told name, naturally ask for phone
- Example: "Love it! To make sure we can follow up with you quickly, could I grab your phone number?"
- If they ignore this and answer your next question instead, ask again un different way.
- Move forward with conversation naturally

**Message 4+: Understand Their Needs**
Ask one question at a time based on what's missing:

Location:
- "What area are you interested in? chennai, banglore, delhi, noida, or a specific neighborhood?"
- "Which neighborhoods sound good to you?"

Property Type:
- "What type are you looking for — apartment, villa, or land?"
- "How many bedrooms do you need?"

Budget:
- "What's your budget range?"
- "Great! And what's the upper limit you're comfortable with?"

Timeline:
- "When are you looking to buy — soon or taking your time?"
- "Are you thinking this month, next quarter, or further out?"

Payment Method:
- "Will you be paying with cash or planning to home loan?"
- "Are you open to both options?"

Buyer Status:
- "Is this your first property purchase?"
- "Do you currently own a property?"

**Message 5+: Suggest & Engage**
- Once you understand their basics, suggest relevant properties
- Explain WHY each fits their needs
- Keep them engaged with property details
- Reference what they told you ("You mentioned budget of X and like Y area...")

HANDLING COMMON SCENARIOS:

"Just browsing":
→ "No worries! Happy to show you what's available. What kind of property interests you?"

"Not sure about budget":
→ "That's totally fine! Just roughly — are you thinking under 50L, 50-100L, or above?"

"Looking for something nice":
→ "Perfect! To narrow it down — what would your ideal budget be?"

"Can they negotiate?":
→ "Great question! Let me check what options we have in your budget. First, what's your range?"

Don't know location:
→ "Which part of the city are you thinking? Or what matters most — proximity to work, schools, etc.?"

TONE & STYLE:
- Use casual language ("Love it!", "Perfect!", "Great question!")
- Use emojis occasionally but not excessively
- Reference their answers ("You mentioned...")
- Compliment their choices ("Smart thinking!")
- Be genuine, not scripted
- Keep it conversational — this is a chat, not a form

IMPORTANT RULES:
- NEVER ask 2 questions in one message
- ALWAYS wait for their response before asking next question
- Ask phone number ONCE early — if ignored, try again in different way.
- Don't repeat questions they've already answered
- If they're vague, ask ONE clarifying question, not multiple
- Keep messages 2-3 sentences max
- Share your personality — be warm and helpful
- Listen and respond to what they say, not just follow a script

Property listings context:
{context_text}

Remember: This is a real conversation with a real person. They might take tangents, ask random questions, or ignore something you ask. That's okay! Go with the flow, answer their questions, and naturally work toward understanding their needs. The goal is to build trust and help them find the right property.
""",
)
        result = await Runner.run(agent, input=user_message, session=session)
        return result.final_output

    def get_reply_from_llm(self, conversation_id, user_message):
        return async_to_sync(self.get_reply_from_llm_async)(
            conversation_id, user_message
        )

    def reply_to_message(
        self, company_business_ig_id, recipient_ig_id, message, access_token
    ):
        url = f"https://graph.instagram.com/v24.0/{company_business_ig_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        data = {"recipient": {"id": recipient_ig_id}, "message": {"text": message}}

        response = requests.post(url, json=data, headers=headers)
        return response.json()

        return {}

    def handle_message(self, data: dict):
        if not data["recipient"]:
            return {}
        message_id = data["message_id"]
        try:
            message = ConversationMessage.objects.get(instagram_message_id=message_id)
            print("Message already processed", message_id)
            return {}
        except ConversationMessage.DoesNotExist:
            pass
        try:
            company_instagram_account = InstagramAccount.objects.get(
                fb_data__instagram_business_account_id=data["recipient"]
            )
        except InstagramAccount.DoesNotExist:
            return {}
        conversation_id = str(data["recipient"]) + "_" + str(data["sender"])
        self.company = company_instagram_account.company
        lead, created = Lead.objects.update_or_create(
            instagram_conversation_id=conversation_id,
            defaults={
                "company": company_instagram_account.company,
                "source_type": "instagram_dm",
                "instagram_username": str(data["sender"]),  # or resolved username
                "qualification_status": "initiated",
                "status": "active",
                "last_customer_message": str(data["message"]),
                "last_interaction_at": timezone.now(),
            },
        )
        self.lead = lead

        # Initialize the custom session
        session = MyCustomSession(conversation_id, self.lead)
        # Store the user's message via session abstraction
        async_to_sync(session.add_items)(
            [
                {
                    "sender_type": "user",
                    "message_text": str(data["message"]),
                    "message_type": "initial_inquiry",
                    "extracted_data": {},
                    "confidence_score": None,
                    "is_from_instagram": True,
                    "instagram_message_id": message_id,
                }
            ]
        )
        reply_message = self.get_reply_from_llm(conversation_id, data["message"])

        # Send reply via Instagram API
        response_to_user = self.reply_to_message(
            recipient_ig_id=data["sender"],
            company_business_ig_id=data["recipient"],
            message=reply_message,
            access_token=company_instagram_account.instagram_data["access_token"],
        )
        print("Response to user", response_to_user)
        threading.Thread(
            target=extract_lead_data_async, args=(self.lead.id,), daemon=True
        ).start()
        # Store assistant reply
        async_to_sync(session.add_items)(
            [
                {
                    "sender_type": "assistant",
                    "message_text": reply_message,
                    "message_type": "follow_up",
                    "extracted_data": {},
                    "confidence_score": 1.0,
                    "is_from_instagram": True,
                    "instagram_message_id": response_to_user.get("message_id"),
                }
            ]
        )

    def post(self, request):
        print("Webhook data", request.body)
        data = parse_instagram_payload(json.loads(request.body))
        if data["webhook_type"] == "message":
            response = self.handle_message(data=data)
        # if data["webhook_type"] == "comment":
        #     response = self.handle_comments(data=data)
        return JsonResponse({"status": "received"})


class InstagramWebHookSubscribe(View):
    def post(self, request, company_id):
        try:
            company = get_object_or_404(Company, id=company_id)

            # Get Instagram account
            instagram_account = InstagramAccount.objects.filter(company=company).first()

            if not instagram_account:
                return JsonResponse(
                    {"success": False, "error": "No Instagram account connected"},
                    status=400,
                )

            if not instagram_account.instagram_data["access_token"]:
                return JsonResponse(
                    {"success": False, "error": "No access token available"}, status=400
                )

            # Call Instagram Graph API to subscribe to messages
            user_id = instagram_account.instagram_data["instagram_app_user_id"]
            access_token = instagram_account.instagram_data["access_token"]
            if not user_id or not access_token:
                return JsonResponse(
                    {"success": False, "error": "Invalid page data"}, status=400
                )

            url = f"https://graph.instagram.com/v24.0/{user_id}/subscribed_apps"

            params = {
                "subscribed_fields": "comments,messages",
                "access_token": access_token,
            }

            logger.info(
                f"Subscribing to message events for Instagram account: {user_id}"
            )

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
                # Update the webhook_subscribed field
                instagram_account.instagram_data["webhook_subscribed"] = True
                instagram_account.save(update_fields=["instagram_data"])

                return JsonResponse(
                    {
                        "success": True,
                        "message": "Successfully subscribed to message events",
                    }
                )
            else:
                error_message = response_data.get("error", {}).get(
                    "message", "Unknown error"
                )
                logger.error(f"Failed to subscribe: {error_message}")

                return JsonResponse(
                    {"success": False, "error": error_message}, status=400
                )

        except requests.RequestException as e:
            logger.error(f"Request error during subscription: {str(e)}")
            return JsonResponse(
                {"success": False, "error": f"Network error: {str(e)}"}, status=500
            )

        except Exception as e:
            logger.error(f"Error subscribing to Instagram messages: {str(e)}")
            return JsonResponse({"success": False, "error": str(e)}, status=500)


class InstagramConnectView(LoginRequiredMixin, View):

    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        membership = get_object_or_404(Membership, user=request.user, company=company)
        if membership.role not in ["admin"]:
            messages.warning(
                request,
                "You do not have permission to connect Instagram for this company, only admin can connect instagram.",
            )
            return redirect("company-detail", company_id=company_id)
        instagram_data = (
            company.instagram_account.instagram_data
            if company and hasattr(company, "instagram_account")
            else None
        )
        fb_data = (
            company.instagram_account.fb_data
            if company and hasattr(company, "instagram_account")
            else None
        )
        fb_connected = True if fb_data else False
        instagram_connected = True if instagram_data else False
        instagram_account = company.instagram_account if instagram_connected else None

        context = {
            "company": company,
            "instagram_connected": instagram_connected,
            "instagram_account": instagram_account,
            "fb_connected": fb_connected,
            "webhook_subscribed": (
                instagram_account.instagram_data.get("webhook_subscribed")
                if instagram_connected
                else False
            ),
        }

        return render(request, "instagram/connect-instagram.html", context)


class InstagramOAuthRedirectView(LoginRequiredMixin, View):

    def post(self, request, company_id):
        configs = Configuration.objects.filter(
            key__in=["app_root_url", "instagram_app_id"]
        )
        data = {conf.key: conf.value for conf in configs}

        redirect_uri = f"{data["app_root_url"]}/instagram/callback/instagram"

        scopes = [
            "instagram_business_basic",
            "instagram_business_content_publish",
            "instagram_business_manage_comments",
            "instagram_business_manage_messages",
        ]

        params = {
            "client_id": data["instagram_app_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "force_reauth": True,
            "state": company_id,
        }

        oauth_url = (
            "https://www.instagram.com/oauth/authorize?"
            + urllib.parse.urlencode(params)
        )
        return redirect(oauth_url)


class FBOAuthRedirectView(LoginRequiredMixin, View):

    def post(self, request, company_id):
        configs = Configuration.objects.filter(key__in=["app_root_url", "fb_app_id"])
        data = {conf.key: conf.value for conf in configs}

        redirect_uri = f"{data["app_root_url"]}/instagram/callback/fb"

        scopes = [
            "instagram_basic",
            "instagram_manage_comments",
            "instagram_manage_messages",
            "pages_read_engagement",
            "business_management",
            "pages_show_list",
            "instagram_manage_insights",
        ]

        params = {
            "client_id": data["fb_app_id"],
            "response_type": "token",
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "force_reauth": True,
            "state": company_id,
            "auth_type": "rerequest",
        }

        oauth_url = "https://www.facebook.com/dialog/oauth?" + urllib.parse.urlencode(
            params
        )
        return redirect(oauth_url)


VERIFY_TOKEN = "Speed#123"


@csrf_exempt
def instagram_save_token(request):
    try:
        payload = json.loads(request.body.decode())
        long_lived_token = payload.get("long_lived_token")
        token_expires_at = datetime.now() + timedelta(seconds=5184000)
        company_id = payload.get("company_id")
        url = "https://graph.facebook.com/v24.0/me/accounts"
        params = {
            "fields": "id,name,access_token,instagram_business_account",
            "access_token": long_lived_token,
        }

        response = requests.get(url, params=params)
        user_data = response.json()
        print("Facebook page data", user_data)
        company = get_object_or_404(Company, id=company_id)
        response_data = user_data.get("data", [])
        if not response_data:
            return JsonResponse(
                {"status": "error", "message": "Failed to fetch user data"}, status=400
            )
        user_info = response_data[0].get("instagram_business_account", {})
        if not user_info:
            return JsonResponse(
                {"status": "error", "message": "No Instagram business account found"},
                status=400,
            )
        instagram_business_account_id = user_info.get("id", "")
        print("Connected user info", instagram_business_account_id, company_id)
        fb_data = {
            "instagram_business_account_id": instagram_business_account_id,
            "username": user_info.get("username", ""),
            "access_token": long_lived_token,
            "token_expires_at": str(token_expires_at),
            "is_active": True,
            "page_data": response_data[0],
        }
        instagram_account, created = InstagramAccount.objects.update_or_create(
            company=company,
            defaults={"fb_data": fb_data},
        )
        return JsonResponse({"status": "ok"})
    except Exception as e:
        print("Error saving Instagram token", str(e))
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


class FBCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "instagram/instagram-callback.html")


class InstagramCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        state = request.GET.get("state")
        code = request.GET.get("code")
        error_description = request.GET.get("error_description")
        error_reason = request.GET.get("error_reason")
        # Basic parameter validation
        if error_description or error_reason:
            messages.error(request, f"Instagram connection failed: {error_reason}")
            return redirect("dashboard")

        if not code or not state:
            messages.error(request, "Invalid callback parameters.")
            return redirect("dashboard")

        company_id = state
        company = get_object_or_404(Company, id=company_id)

        # ---- Step 0: Load configuration ----
        configs = Configuration.objects.filter(
            key__in=["app_root_url", "instagram_app_id", "instagram_app_secret"]
        )
        config_data = {conf.key: conf.value for conf in configs}
        missing_keys = [
            k
            for k in ["app_root_url", "instagram_app_id", "instagram_app_secret"]
            if k not in config_data
        ]
        if missing_keys:
            messages.error(request, f"Missing configuration: {', '.join(missing_keys)}")
            return redirect("instagram_connect", company_id=company_id)

        redirect_uri = (
            f"{config_data['app_root_url'].rstrip('/')}/instagram/callback/instagram"
        )

        try:
            # ---- Step 1: Exchange code for short-lived token ----
            token_response = requests.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": config_data["instagram_app_id"],
                    "client_secret": config_data["instagram_app_secret"],
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=10,
            )
            token_data = token_response.json()

            if not token_response.ok or "access_token" not in token_data:
                raise ValueError(
                    token_data.get("error_message")
                    or token_data.get("error", "Invalid token response")
                )

            short_lived_token = token_data["access_token"]
            user_id = token_data.get("user_id")
            # ---- Step 2: Exchange for long-lived token ----
            long_lived_response = requests.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": config_data["instagram_app_secret"],
                    "access_token": short_lived_token,
                },
                timeout=100,
            )
            long_lived_data = long_lived_response.json()
            if not long_lived_response.ok or "access_token" not in long_lived_data:
                raise ValueError(
                    long_lived_data.get("error_message")
                    or long_lived_data.get("error", "Invalid long-lived token response")
                )

            access_token = long_lived_data["access_token"]
            expires_in = long_lived_data.get("expires_in", 5184000)
            token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            # ---- Step 3: Fetch IG user details ----
            user_info_response = requests.get(
                "https://graph.instagram.com/v21.0/me",
                params={
                    "fields": "id,username",
                    "access_token": access_token,
                },
                timeout=10,
            )
            if not user_info_response.ok:
                raise ValueError(
                    f"Failed to fetch Instagram user info: {user_info_response.text}"
                )

            user_info = user_info_response.json()
            print("Connected user info", user_info)

            # ---- Step 4: Update or create InstagramAccount ----
            instagram_data = {
                "instagram_app_user_id": user_info.get("id", ""),
                "username": user_info.get("username", ""),
                "access_token": access_token,
                "token_expires_at": str(token_expires_at),
                "is_active": True,
            }
            instagram_account, created = InstagramAccount.objects.update_or_create(
                company=company,
                defaults={"instagram_data": instagram_data},
            )

            action = "connected" if created else "updated"
            messages.success(request, f"Instagram account successfully {action}!")

        except requests.RequestException as e:
            print("Error - RequestException occurred", str(e))
            messages.error(
                request, f"Network error while connecting to Instagram: {str(e)}"
            )
        except ValueError as e:
            print("Error - ValueError occurred", str(e))
            messages.error(request, f"Instagram API error: {str(e)}")
        except Exception as e:
            print("Error - Exception occurred", str(e))
            messages.error(request, f"Unexpected error: {str(e)}")

        return redirect("instagram_connect", company_id=company_id)


class InstagramDisconnectView(LoginRequiredMixin, View):
    login_url = "/login/"

    def post(self, request, company_id):
        """Disconnect Instagram account"""
        company = get_object_or_404(Company, id=company_id)

        try:
            if hasattr(company, "instagram_account"):
                instagram_account = company.instagram_account
                instagram_account.instagram_data = {}
                instagram_account.save(update_fields=["instagram_data"])

                messages.success(
                    request, "Instagram account disconnected successfully."
                )
                return JsonResponse(
                    {"success": True, "message": "Disconnected successfully."}
                )
            else:
                return JsonResponse(
                    {"success": False, "error": "No Instagram account connected."},
                    status=404,
                )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    def get(self, request, *args, **kwargs):
        """Reject GET requests explicitly"""
        return JsonResponse(
            {"success": False, "error": "Method not allowed"}, status=405
        )

        """def handle_comment_without_listing(self, data: dict):
        print("Handling a comment ,which does not have a listing with maedix")
        return {}

    def reply_to_comment(self, ig_comment_id, message, access_token):
        url = f"https://graph.facebook.com/v24.0/{ig_comment_id}/replies"
        headers = {"Content-Type": "application/json"}
        payload = {"message": message, "access_token": access_token}

        response = requests.post(url, json=payload, headers=headers)
        return response.json()

    def handle_comments(self, data: dict):
        print("Comment data", data)
        post_id = data.get("post_id", "")
        if not post_id:
            return {}
        company_listing_of_post_id = None
        try:
            company_listing_of_post_id = PropertyListing.objects.get(
                instagram_post_id=post_id
            )
        except PropertyListing.DoesNotExist:
            return self.handle_comment_without_listing(data=data)
        print("User commented on listing", company_listing_of_post_id.title)
        return self.reply_to_comment()
        """


class FBDisconnectView(LoginRequiredMixin, View):
    login_url = "/login/"

    def post(self, request, company_id):
        """Disconnect FB account"""
        company = get_object_or_404(Company, id=company_id)

        try:
            if hasattr(company, "instagram_account"):
                instagram_account = company.instagram_account
                instagram_account.fb_data = {}
                instagram_account.save(update_fields=["fb_data"])

                messages.success(request, "FB account disconnected successfully.")
                return JsonResponse(
                    {"success": True, "message": "Disconnected successfully."}
                )
            else:
                return JsonResponse(
                    {"success": False, "error": "No FB account connected."},
                    status=404,
                )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    def get(self, request, *args, **kwargs):
        """Reject GET requests explicitly"""
        return JsonResponse(
            {"success": False, "error": "Method not allowed"}, status=405
        )
