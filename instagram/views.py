# pylint:disable=all
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
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
from asgiref.sync import sync_to_async, async_to_sync

from agents import Agent, Runner
import threading
from .utils import (
    extract_lead_data_async,
    parse_instagram_payload,
    find_relevant_properties,
)
from core.models import Subscription, EventRegister
from .session import MyCustomSession
from .agent_instructions import AGENT_1, AGENT_2


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
            instructions=AGENT_1.format(
                company_name=self.company.name, context_text=context_text
            ),
        )
        result = await Runner.run(agent, input=user_message, session=session)
        return result.final_output
        #return "Reply from llm"

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
        if not self.company.detail.get('enable_dm_response', True):
            print("DM response feature not enabled for company", self.company.id)
            return {}
        subscription = Subscription.objects.filter(company=self.company).first()
        if (
            not subscription
            or not subscription.is_active()
            or subscription.has_permission("instagram_dm") is False
        ):
            print("No active subscription to handle DM")
            return {}
        lead, created = Lead.objects.get_or_create(
            instagram_conversation_id=conversation_id,
            defaults={
                "company": company_instagram_account.company,
                "source_type": "instagram_dm",
                "instagram_username": str(data["sender"]),
                "qualification_status": "initiated",
                "status": "active",
                "last_customer_message": str(data["message"]),
                "last_interaction_at": timezone.now(),
            }
        )

        # Update only if lead already existed
        if not created:
            lead.last_customer_message = str(data["message"])
            lead.last_interaction_at = timezone.now()
            # Don't update source_type - keep original
            lead.save(update_fields=['last_customer_message', 'last_interaction_at', 'status'])

        
        if created:
            # Increment leads_used count
            subscription.leads_used += 1
            subscription.save()
            print("New lead created from Instagram DM:", lead.id)
        self.lead = lead
        if self.lead.human_agent_assigned:
            print("Human agent assigned so ignoring ai reply")
            return {}
        if (
            not subscription
            or not subscription.is_active()
            or subscription.has_permission("instagram_dm_ai_reply") is False
        ):
            # Check if we've already sent the static first DM
            if not self.lead.tags or self.lead.tags.get("static_first_dm") != "done":
                response_to_user = self.reply_to_message(
                    recipient_ig_id=data["sender"],
                    company_business_ig_id=data["recipient"],
                    message=self.company.detail.get("static_dm_reply", "Thanks for reaching out to us, we will contact you shortly."),
                    access_token=company_instagram_account.instagram_data["access_token"],
                )
                
                # Mark that static DM has been sent
                if self.lead.tags is None:
                    self.lead.tags = {}
                self.lead.tags["static_first_dm"] = "done"
                self.lead.save(update_fields=['tags'])
                
                print("Static DM reply sent to user for company", self.company.id)
            else:
                print("Static DM already sent to this lead, skipping", self.lead.id)
            
            print("Inactive or invalid subscription for company to generate ai reply", self.company.id)
            return {}

        # Prevent automatic reply a new lead when quota is 0
        if subscription.leads_used >= subscription.lead_quota:
            print(f"Lead quota exhausted for company {self.company.id}")
            return {}

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

    async def get_reply_from_llm_async_for_cmments(
        self, user_message, property_context
    ):
        """Uses OpenAI Agent to get a contextual LLM reply."""
        print("Generating comment reply for message:", user_message, property_context)
        agent = Agent(
            name="Instagram Real Estate Assistant",
            model="gpt-4-turbo",
            instructions=AGENT_2.format(property_context=property_context),
        )
        result = await Runner.run(agent, input=user_message)
        return result.final_output
        # return """{
        #     "comment_reply" : "Please check message",
        #     "first_dm" : "Thanks for message us", 
        #     "context_for_dm_handler" : "user commented"}"""

    def reply_to_instagram_comment(self, comment_id, message, access_token):
        """Reply to an Instagram comment using the Graph API."""
        url = f"https://graph.instagram.com/v24.0/{comment_id}/replies"

        headers = {"Content-Type": "application/json"}

        payload = {"message": message, "access_token": access_token}

        try:
            response = requests.post(url, headers=headers, json=payload)
            response_data = response.json()

            if response.status_code == 200:
                print(f"Successfully replied to comment {comment_id}")
                return response_data
            else:
                print(f"Failed to reply to comment: {response_data}")
                return None

        except Exception as e:
            print(f"Error replying to comment: {str(e)}")
            return None

    def send_dm_to_commenter(
        self, comment_id, message, ig_business_account_id, access_token
    ):
        """
        Send a DM to the person who commented.
        Uses comment_id to identify the recipient.
        """
        url = f"https://graph.instagram.com/v24.0/{ig_business_account_id}/messages"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": message},
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response_data = response.json()

            if response.status_code == 200:
                print(f"✅ Successfully sent DM via comment {comment_id}")
                return response_data
            else:
                print(f"❌ Failed to send DM: {response_data}")
                return None

        except Exception as e:
            print(f"❌ Error sending DM: {str(e)}")
            return None

    def handle_comments(self, data: dict):
        print("Comment data", data)
        post_id = data.get("post_id", "")
        comment_id = data["comment_id"]
        parent_id = data.get("parent_id", "")
        if parent_id:
            return {}
        if not comment_id:
            return {}
        event = EventRegister.objects.filter(event_id=comment_id).first()
        if event:
            print("Comment event already processed", comment_id)
            return {}
        EventRegister.objects.create(
            event_id=comment_id, event_type="instagram_comment", payload=data
        )
        if not post_id:
            return {}
        try:
            company_instagram_account = InstagramAccount.objects.get(
                fb_data__instagram_business_account_id=data["recipient"]
            )
        except InstagramAccount.DoesNotExist:
            return {}
        self.company = company_instagram_account.company
        if not self.company.detail.get('enable_comment_reply', True): 
            print("Comment auto response feature not enabled for company", self.company.id)
            return {}

        conversation_id = str(data["recipient"]) + "_" + str(data["sender"])
        self.company = company_instagram_account.company
        existing_lead = Lead.objects.filter(
            instagram_conversation_id=conversation_id
        ).first()
        new_lead = None
        subscription = Subscription.objects.filter(company=self.company).first()
        if (
            not subscription
            or not subscription.is_active()
            or subscription.has_permission("instagram_comment_auto_response") is False
        ):
            print("Comment auto response feature not enabled")
            return {}
        if not existing_lead:
            new_lead = Lead.objects.create(
                instagram_conversation_id=conversation_id,
                company=self.company,
                source_type="instagram_comment",
                instagram_username=str(data["sender_username"]),
                qualification_status="initiated",
                status="active",
                last_customer_message=str(data["comment_text"]),
                last_interaction_at=timezone.now(),
            )
        
        if new_lead:
            # Increment leads_used count
            subscription.leads_used += 1
            subscription.save()
            print("New lead created from Instagram comment:", new_lead.id)

        if (
            not subscription
            or not subscription.is_active()
            or subscription.has_permission("instagram_comment_ai_response") is False
        ):
            print("Inactive or invalid subscription for company", self.company.id)
            comment_reply_response = self.reply_to_instagram_comment(
            comment_id=data["comment_id"],
            message=self.company.detail.get("static_comment_reply", "Please check your DM"),
            access_token=company_instagram_account.instagram_data["access_token"],
        )
            send_dm_response = self.send_dm_to_commenter(
            comment_id=comment_id,
            message=self.company.detail.get("static_comment_followup_dm_reply", "Hi, Thanks for commenting on our post. How can we assit you further on your property searchinh journey?"),
            ig_business_account_id=company_instagram_account.fb_data[
                "instagram_business_account_id"
            ],
            access_token=company_instagram_account.instagram_data["access_token"],
        )
            return {}
        lead = existing_lead or new_lead
        company_listing_of_post_id = None
        property_context = ""
        try:
            company_listing_of_post_id = PropertyListing.objects.get(
                instagram_post_id=post_id
            )
            property_context = company_listing_of_post_id.summarize_property()
        except PropertyListing.DoesNotExist:
            property_context = ""
        response = async_to_sync(self.get_reply_from_llm_async_for_cmments)(
            data["comment_text"], property_context
        )
        print("LLM comment reply response", response)
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            print("❌ Failed to parse LLM comment reply response as JSON:", response)
            return {}
        comment_reply = response.get("comment_reply", "Please check your DM")
        comment_reply_response = self.reply_to_instagram_comment(
            comment_id=data["comment_id"],
            message=comment_reply,
            access_token=company_instagram_account.instagram_data["access_token"],
        )
        print("Comment reply response", comment_reply_response)
        dm_message : str = response.get(
                "first_dm",
                "Hi, Thanks for commenting on our post. How can we assit you further on your property searchinh journey?",
            )
        send_dm_response = self.send_dm_to_commenter(
            comment_id=comment_id,
            message=dm_message,
            ig_business_account_id=company_instagram_account.fb_data[
                "instagram_business_account_id"
            ],
            access_token=company_instagram_account.instagram_data["access_token"],
        )
        if new_lead:
            ConversationMessage.objects.create(
                lead=lead,
                conversation_id=conversation_id,
                sender_type="assistant",
                message_text="Context for chat : "
                + str(
                    response.get(
                        "context_for_dm_handler",
                        "This conversation is initiated via Instagram comment",
                    )
                ),
                message_type="initial_inquiry"
            )
            ConversationMessage.objects.create(
                lead=lead,
                conversation_id=conversation_id,
                sender_type="assistant",
                message_text=dm_message,
                message_type="initial_inquiry"
            )
        print("First dm response", send_dm_response)
        return {}

    def post(self, request):
        print("Webhook data", request.body)
        data = parse_instagram_payload(json.loads(request.body))
        if data["webhook_type"] == "message":
            response = self.handle_message(data=data)
        if data["webhook_type"] == "comment":
            response = self.handle_comments(data=data)
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


def get_long_lived_toke(short_token):
    url = f"https://graph.facebook.com/v24.0/oauth/access_token"
    configs = Configuration.objects.filter(
            key__in=["fb_app_id", "fb_app_secret"]
        )
    config_data = {conf.key: conf.value for conf in configs}
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": config_data['fb_app_id'],
        "client_secret": config_data['fb_app_secret'],
        "fb_exchange_token": short_token,
    }

    response = requests.get(url, params=params)

    if response.ok:
        data = response.json()
        print("Long-lived token:", data.get("access_token"))
        print("Expires in (seconds):", data.get("expires_in"))
        return data
    else:
        print("Error:", response.status_code, response.text)
        return {}
        
@csrf_exempt
def instagram_save_token(request):
    try:
        payload = json.loads(request.body.decode())
        short_token = payload.get("access_token")
        token_expires_at = datetime.now() + timedelta(seconds=5184000)
        company_id = payload.get("company_id")
        url = "https://graph.facebook.com/v24.0/me/accounts"
        params = {
            "fields": "id,name,access_token,instagram_business_account",
            "access_token": short_token,
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
            "access_token": response_data[0].get("access_token",""),
            "token_expires_at": str(token_expires_at),
            "is_active": True,
            "page_data": response_data[0],
        }
        instagram_account, created = InstagramAccount.objects.update_or_create(
            company=company,
            instagram_business_account_id=str(fb_data.get("instagram_business_account_id", "")),
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
