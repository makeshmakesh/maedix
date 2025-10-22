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
from realestate.models import Company, Lead, ConversationMessage, PropertyListing
from core.models import Configuration
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
import logging
import urllib.parse

logger = logging.getLogger(__name__)
from realestate.models import Company, Lead
from django.utils import timezone


def parse_instagram_payload(data: dict):
    try:
        response = {}
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
        return {}


@method_decorator(csrf_exempt, name="dispatch")
class InstagramWebHookView(View):
    def get(self, request):
        token_sent = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if token_sent == VERIFY_TOKEN:
            return HttpResponse(challenge)
        return HttpResponse("Invalid verification token", status=403)

    def form_llm_context(self, conversation_id):
        convos = ConversationMessage.objects.filter(conversation_id=conversation_id)
        response = []
        for convo in convos:
            data = {"message": convo.message_text, "role": convo.sender_type}
            response.append(data)
        return response

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
                instagram_business_account_id=data["recipient"]
            )
            print("111111111111111", company_instagram_account, data["recipient"])
        except InstagramAccount.DoesNotExist:
            return {}
        conversation_id = str(data["recipient"]) + "_" + str(data["sender"])
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
        conversation_message = ConversationMessage.objects.create(
            lead=lead,
            conversation_id=conversation_id,
            sender_type="Customer",
            message_text=str(data["message"]),
            message_type="initial_inquiry",
            instagram_message_id=data["message_id"],
        )
        context = self.form_llm_context(conversation_id=conversation_id)

    def handle_comment_without_listing(self, data: dict):
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

            if not instagram_account.access_token:
                return JsonResponse(
                    {"success": False, "error": "No access token available"}, status=400
                )

            # Call Instagram Graph API to subscribe to messages
            page_id = instagram_account.page_data["id"]
            access_token = instagram_account.page_data["access_token"]
            if not page_id or not access_token:
                return JsonResponse(
                    {"success": False, "error": "Invalid page data"}, status=400
                )

            url = f"https://graph.facebook.com/v21.0/{page_id}/subscribed_apps"

            params = {
                "subscribed_fields": "feed,messages",
                "access_token": access_token,
            }

            logger.info(
                f"Subscribing to message events for Instagram account: {page_id}"
            )

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
                # Update the webhook_subscribed field
                instagram_account.webhook_subscribed = True
                instagram_account.save(update_fields=["webhook_subscribed"])

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

        # Check if Instagram is already connected
        instagram_connected = (
            hasattr(company, "instagram_account")
            and company.instagram_account.is_active
        )
        instagram_account = company.instagram_account if instagram_connected else None

        context = {
            "company": company,
            "instagram_connected": instagram_connected,
            "instagram_account": instagram_account,
        }

        return render(request, "instagram/connect-instagram.html", context)


class InstagramOAuthRedirectView(LoginRequiredMixin, View):

    def post(self, request, company_id):
        configs = Configuration.objects.filter(
            key__in=["app_root_url", "instagram_app_id"]
        )
        data = {conf.key: conf.value for conf in configs}

        redirect_uri = f"{data["app_root_url"]}/instagram/callback"

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

        redirect_uri = f"{data["app_root_url"]}/instagram/callback"

        scopes = [
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_comments",
            "instagram_manage_messages",
            "pages_show_list",
            "pages_read_engagement",
            "business_management",
            "pages_messaging",
            "pages_manage_metadata"
        ]

        params = {
            "client_id": data["fb_app_id"],
            "response_type": "token",
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "force_reauth": True,
            "state": company_id,
        }

        oauth_url = "https://www.facebook.com/dialog/oauth?" + urllib.parse.urlencode(
            params
        )
        return redirect(oauth_url)


VERIFY_TOKEN = "Speed#123"


@csrf_exempt
def instagram_save_token(request):
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
    instagram_account, created = InstagramAccount.objects.update_or_create(
        company=company,
        defaults={
            "instagram_business_account_id": instagram_business_account_id,
            "username": user_info.get("username", ""),
            "access_token": long_lived_token,
            "token_expires_at": token_expires_at,
            "is_active": True,
            "page_data" : response_data[0],
        },
    )
    return JsonResponse({"status": "ok"})


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

        redirect_uri = f"{config_data['app_root_url'].rstrip('/')}/instagram/callback"

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
                "https://graph.instagram.com/v21.0/me/accounts",
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
            instagram_account, created = InstagramAccount.objects.update_or_create(
                company=company,
                defaults={
                    "instagram_business_account_id": user_info.get("id", ""),
                    "username": user_info.get("username", ""),
                    "access_token": access_token,
                    "token_expires_at": token_expires_at,
                    "is_active": True,
                },
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
                instagram_account.is_active = False
                instagram_account.save(update_fields=["is_active"])

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
