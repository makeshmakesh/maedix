"""Handle views for core"""
#pylint:disable=all
from django.shortcuts import render
from django.views import View
# Create your views here.
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
        india_plans = [
    {
        "id": "starter",
        "name": "Starter",
        "description": "For individual real estate agents getting started with AI automation.",
        "price": 1999,
        "display_price": "1,999",
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 50,
        "leads_count_display": "50",
        "featured": False,
        "button_class": "btn-outline-primary",
        "features": [
            "Automated DM replies",
            "Lead capture & CRM sync",
            "AI pre-qualification chat flow",
            "Basic property listing integration",
            "Performance dashboard",
            "Email support",
        ],
    },
    {
        "id": "growth",
        "name": "Growth",
        "description": "Ideal for growing brokerages managing multiple listings and agents.",
        "price": 4999,
        "display_price": "4,999",
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 200,
        "leads_count_display": "200",
        "featured": True,
        "button_class": "btn-primary",
        "features": [
            "Everything in Starter",
            "Comment auto-response",
            "Advanced analytics & funnel tracking",
            "Multi-agent collaboration",
            "Priority email & chat support",
        ],
    },
    {
        "id": "pro",
        "name": "Pro",
        "description": "For high-volume agencies and developers handling hundreds of inquiries.",
        "price": 9999,
        "display_price": "9,999",
        "duration_period": "month",
        "currency_symbol": "₹",
        "currency": "INR",
        "leads_count": 500,
        "leads_count_display": "500",
        "featured": False,
        "button_class": "btn-secondary",
        "features": [
            "Everything in Growth",
            "Dedicated account manager",
            "Custom AI flow design",
            "Human takeover support (hybrid automation)",
            "Priority phone support",
        ],
    },
]

        
        context = {
            'plans': india_plans
        }
        
        return render(request, 'core/plans.html', context)


