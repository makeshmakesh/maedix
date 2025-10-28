# pylint:disable=all
from django.urls import path
from core import views
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [ 
    path("", views.HomePage.as_view(), name="entry"),
    path("terms", views.TermsPage.as_view(), name="terms"),
    path("privacy-policy", views.PrivacyPolicyPage.as_view(), name="privacy-policy"),
    path("contact", views.ContactPage.as_view(), name="contact"),
    path("plans/", views.PlansPage.as_view(), name="plans")
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
