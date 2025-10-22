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