"""Handle views for core"""

# pylint:disable=all
from django.views import View
import os
import razorpay
import hmac
import hashlib
import json
import logging
from decimal import Decimal
from django.http import JsonResponse
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Transaction, Subscription
from django.utils import timezone
from realestate.models import Company, Membership
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)
# Create your views here.


PLANS = [
    {
        "id": "lite",
        "name": "Lite",
        "description": "Perfect for exploring our AI tools and getting a taste of automation.",
        "price": 149,
        "display_price": "149",
        "duration": 1,
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 0,
        "leads_count_display": "0",
        "featured": False,
        "button_class": "btn-outline-primary",
        "features_allowed": [
            {"name": "instagram_dm"},
            {"name": "property_listing_integration"},
        ],
        "features": [
            "Automated static DM responses",
            "Automated static comment replies with first DM follow-up",
            "Automatic lead capture from all incoming DMs",
            "Unlimited property listings",
        ],
    },
    {
        "id": "starter",
        "name": "Starter",
        "description": "For individual real estate agents getting started with AI automation.",
        "price": 1999,
        "display_price": "1,999",
        "duration": 1,
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 50,
        "leads_count_display": "50",
        "featured": False,
        "button_class": "btn-outline-primary",
        "features_allowed": [
            {"name": "instagram_dm"},
            {"name": "property_listing_integration"},
            {"name": "instagram_dm_ai_reply"}
        ],
        "features": [
            "All features from Lite",
            "AI-powered automated DM replies",
            "AI prequalification for up to 50 leads per month",
        ],
    },
    {
        "id": "growth",
        "name": "Growth",
        "description": "Ideal for growing brokerages managing multiple listings and agents.",
        "price": 4999,
        "display_price": "4,499",
        "duration": 1,
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 200,
        "leads_count_display": "200",
        "featured": True,
        "button_class": "btn-primary",
        "features_allowed": [
            {"name": "instagram_dm"},
            {"name": "instagram_comment_auto_response"},
            {"name": "multi_agent_collaboration"},
            {"name": "property_listing_integration"},
            {"name": "instagram_dm_ai_reply"},
            {"name": "instagram_comment_ai_response"},
        ],
        "features": [
            "All features from Starter",
            "AI prequalification for up to 200 leads per month",
            "AI-powered comment auto-responses",
            "Multi-agent collaboration tools",
            "Priority email and chat support",
        ],
    },
    {
        "id": "pro",
        "name": "Pro",
        "description": "For high-volume agencies and developers handling hundreds of inquiries.",
        "price": 9999,
        "display_price": "9,999",
        "duration": 1,
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 500,
        "leads_count_display": "500",
        "featured": False,
        "button_class": "btn-secondary",
        "features_allowed": [
            {"name": "instagram_dm"},
            {"name": "instagram_comment_auto_response"},
            {"name": "multi_agent_collaboration"},
            {"name": "human_takeover_support"},
            {"name": "property_listing_integration"},
            {"name": "instagram_dm_ai_reply"},
            {"name": "instagram_comment_ai_response"},
        ],
        "features": [
            "All features from Growth",
            "AI prequalification for up to 500 leads per month",
            "Dedicated account manager for personalized support",
            "Priority phone support",
        ],
    },
]



def get_plan(plan_id):
    """Retrieve plan details by ID"""
    for plan in PLANS:
        if plan["id"] == plan_id:
            return plan
    return None


class HomePage(View):
    """Renders the landing page."""

    def get(self, request):

        return render(request, "core/landing-page.html")


class TermsPage(View):
    """Renders the landing page."""

    def get(self, request):

        return render(request, "core/terms.html")


class PrivacyPolicyPage(View):
    """Renders the landing page."""

    def get(self, request):

        return render(request, "core/privacy-policy.html")


class ContactPage(View):
    """Renders the landing page."""

    def get(self, request):

        return render(request, "core/contact.html")


class PlansPage(View):
    """Display pricing plans page"""

    def get(self, request):
        india_plans = PLANS

        context = {"plans": india_plans}

        return render(request, "core/plans.html", context)


class PlansPageCompany(View):
    """Display pricing plans page"""

    def get(self, request, company_id):
        india_plans = PLANS
        company = Company.objects.get(id=company_id)
        membership = get_object_or_404(Membership, user=request.user, company=company)
        if membership is None or membership.role not in ["admin", "owner"]:
            messages.error(
                request, "You do not have permission to manage this company's plan."
            )
            return redirect("company-manage", company_id=company_id)
        context = {"plans": india_plans, "company": company}

        return render(request, "core/plan-company.html", context)


class PaymentFailedView(View):
    """Handle payment failure (optional logging)"""

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        try:
            data = json.loads(request.body)

            # Log payment failure
            logger.warning(f"Payment failed: {data}")

            # Optional: Create failed transaction record
            if request.user.is_authenticated:
                Transaction.objects.create(
                    user=request.user,
                    transaction_id=data.get("payment_id", "N/A"),
                    credits=0,
                    amount=Decimal("0.00"),
                    payment_method="razorpay",
                    status="failed",
                    error_message=data.get("error_description", "Payment failed"),
                )

            return JsonResponse({"status": "logged"})

        except Exception as e:
            logger.error(f"Error logging payment failure: {e}")
            return JsonResponse({"status": "error"}, status=400)

    def get(self, request):
        return JsonResponse(
            {"status": "error", "message": "Invalid request method"}, status=400
        )


class PaymentSuccessPageView(LoginRequiredMixin, View):
    """Display success page after payment"""

    login_url = "/login/"

    def get(self, request):
        payment_data = request.session.get("payment_success_data")

        if not payment_data:
            messages.warning(request, "No payment information found.")
            return redirect("dashboard")

        # Clear session data after retrieving it
        del request.session["payment_success_data"]
        transaction_id = payment_data.get("transaction_id")

        if not transaction_id:
            messages.warning(request, "No transaction information found.")
            return redirect("dashboard")
        transaction = Transaction.objects.get(id=transaction_id, user=request.user)
        subscription = Subscription.objects.get(payment_reference=str(transaction.id))
        context = {
            "transaction": transaction,
            "subscription": subscription,
            "company_name": subscription.company.name,
            "company": subscription.company,
            "plan_name": subscription.plan_name,
            "leads_quota": subscription.lead_quota,
            "end_date": subscription.end_date,
            "transaction_id": transaction.id,
            "razorpay_payment_id": transaction.transaction_id,
            "razorpay_order_id": transaction.order_id,
            "amount": transaction.amount,
            "currency": subscription.currency,
        }
        return render(request, "core/payment-success.html", context)


class PaymentSuccessView(LoginRequiredMixin, View):
    """Handle successful payment and update user credits"""

    login_url = "/login/"

    def post(self, request):
        # Get payment details
        razorpay_payment_id = request.POST.get("razorpay_payment_id")
        razorpay_order_id = request.POST.get("razorpay_order_id")
        razorpay_signature = request.POST.get("razorpay_signature")

        plan_id = request.POST.get("plan")
        company_id = request.POST.get("company_id")
        if not company_id:
            messages.error(request, "Company ID is required.")
            return redirect("dashboard")
        plan = get_plan(plan_id)
        if not plan:
            messages.error(request, "Invalid plan selected.")
            return redirect("plans")
        price = float(request.POST.get("price"))

        # Verify payment signature
        try:
            # Create signature verification string
            sign_string = f"{razorpay_order_id}|{razorpay_payment_id}"

            # Generate expected signature
            expected_signature = hmac.new(
                os.getenv("RAZORPAYAPI_SECRET").encode(),
                sign_string.encode(),
                hashlib.sha256,
            ).hexdigest()

            # Verify signature
            if expected_signature != razorpay_signature:
                logger.error(
                    f"Payment signature verification failed for user {request.user.id}"
                )
                messages.error(
                    request, "Payment verification failed. Please contact support."
                )
                return redirect("plans")

            # Create transaction record
            transaction = Transaction.objects.create(
                user=request.user,
                transaction_id=razorpay_payment_id,  # Now accepts string
                order_id=razorpay_order_id,  # Store order ID
                plan_id=plan_id,
                amount=Decimal(price),
                payment_method="razorpay",
                status="success",
            )
            company = Company.objects.get(id=int(company_id))
            try:
                subscription = Subscription.objects.get(company=company)

                # Update existing subscription (renewal)
                subscription.plan_id = plan["id"]
                subscription.plan_name = plan["name"]
                subscription.price = Decimal(price)
                subscription.currency = plan["currency"]
                subscription.billing_cycle = plan["duration_period"]
                subscription.start_date = timezone.now()
                subscription.end_date = timezone.now() + relativedelta(months=1)
                subscription.renewal_date = timezone.now() + relativedelta(months=1)
                subscription.status = "active"
                subscription.data = {
                    "features_allowed": plan["features_allowed"],
                }
                subscription.is_auto_renew = False
                subscription.lead_quota = subscription.lead_quota + plan["leads_count"]
                subscription.leads_used = 0  # Reset usage on renewal
                subscription.messages_used = 0  # Reset usage on renewal
                subscription.last_reset_date = timezone.now()
                subscription.next_reset_date = timezone.now() + relativedelta(months=1)
                subscription.integration_channels = ["instagram"]
                subscription.support_tier = "standard"
                subscription.payment_reference = str(transaction.id)
                subscription.save()

                messages.success(request, "Subscription renewed successfully!")

            except Subscription.DoesNotExist:
                # Create new subscription
                subscription = Subscription.objects.create(
                    company=company,
                    plan_id=plan["id"],
                    plan_name=plan["name"],
                    price=Decimal(price),
                    currency=plan["currency"],
                    billing_cycle=plan["duration_period"],
                    start_date=timezone.now(),
                    end_date=timezone.now() + relativedelta(months=1),
                    renewal_date=timezone.now() + relativedelta(months=1),
                    data={
                        "features_allowed": plan["features_allowed"],
                    },
                    status="active",
                    is_auto_renew=False,
                    lead_quota=plan["leads_count"],
                    leads_used=0,
                    messages_used=0,
                    last_reset_date=timezone.now(),
                    next_reset_date=timezone.now() + relativedelta(months=1),
                    integration_channels=["instagram"],
                    support_tier="standard",
                    payment_reference=str(transaction.id),
                )

            messages.success(request, "Subscription activated successfully!")

            logger.info(
                f"Payment successful for user {request.user.id}: {credits} credits added"
            )
            messages.success(
                request,
                f"Payment successful!.",
            )
            request.session["payment_success_data"] = {
                "transaction_id": transaction.id,
            }
            return redirect("payment_success_page")

        except Exception as e:
            logger.error(f"Payment verification error for user {request.user.id}: {e}")
            messages.error(request, f"Payment verification error: {str(e)}")
            return redirect("plans")


class OrderConfirmationView(LoginRequiredMixin, View):
    """Display checkout page with Razorpay integration"""

    login_url = "/login/"

    def get(self, request, company_id, plan_id):
        company = get_object_or_404(Company, id=company_id)
        membership = get_object_or_404(Membership, user=request.user, company=company)
        if membership is None or membership.role not in ["admin", "owner"]:
            messages.error(
                request, "You do not have permission to manage this company's plan."
            )
            return redirect("company-manage", company_id=company_id)
        razorpay_client = razorpay.Client(
            auth=(os.getenv("RAZORPAY_API_KEY"), os.getenv("RAZORPAYAPI_SECRET"))
        )
        plan = get_plan(plan_id)
        if not plan:
            messages.error(request, "Invalid plan selected.")
            return redirect("plans")

        # Get plan details from POST
        # Set currency symbol
        currency = plan["currency"]
        currency_symbol = "₹" if currency == "INR" else "$"
        price = plan["price"]

        # Convert to smallest currency unit
        if currency == "INR":
            amount_smallest_unit = int(price * 100)  # Paise
        else:
            amount_smallest_unit = int(price * 100)  # Cents

        try:
            razorpay_order = razorpay_client.order.create(
                {
                    "amount": amount_smallest_unit,
                    "currency": plan["currency"],
                    "notes": {
                        "user_id": request.user.id,
                        "plan": plan,
                        "company_id": str(company_id),
                    },
                }
            )
            context = {
                "plan": plan,
                "plan_name": plan["name"],
                "plan_type": plan["id"],
                "plan_id": plan["id"],
                "price": price,
                "duration": plan["duration"],
                "duration_period": plan["duration_period"],
                "currency": currency,
                "currency_symbol": currency_symbol,
                "amount_smallest_unit": amount_smallest_unit,
                "order_id": razorpay_order["id"],
                "razorpay_key_id": os.getenv("RAZORPAY_API_KEY"),
                "company_id": str(company_id),
            }
            return render(request, "core/checkout.html", context)

        except Exception as e:
            logger.error(f"Error creating Razorpay order: {e}")
            messages.error(request, f"Error creating order: {str(e)}")
            return redirect("plans")
