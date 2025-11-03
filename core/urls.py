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
    path("plans/", views.PlansPage.as_view(), name="plans"),
    path("company-plans/<str:company_id>", views.PlansPageCompany.as_view(), name="company-plans"),
    path('company/<str:company_id>/plan/<str:plan_id>/order_confirmation', views.OrderConfirmationView.as_view(), name='order_confirmation'),
    path('payment/success/', views.PaymentSuccessView.as_view(), name='payment_success'),
    path('payment/success/page/', views.PaymentSuccessPageView.as_view(), name='payment_success_page'),
    path('payment/failed/', views.PaymentFailedView.as_view(), name='payment_failed'),
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
