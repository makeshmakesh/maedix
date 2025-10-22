# pylint:disable=all
from django.urls import path
from realestate import views
from django.conf import settings
from django.conf.urls.static import static
from users.views import LoginView

urlpatterns = [
    path("dashboard", views.DashboardView.as_view(), name="dashboard"),
    path(
        "company/<int:company_id>/listings/",
        views.ListingsView.as_view(),
        name="listings",
    ),
    path(
        "company/<int:company_id>/listings/create/",
        views.ListingCreateView.as_view(),
        name="create_listing",
    ),
    path(
        "company/<int:company_id>/listings/<int:listing_id>/edit/",
        views.ListingEditView.as_view(),
        name="edit_listing",
    ),
    path(
        "company-detail/<int:company_id>/",
        views.CompanyDetailView.as_view(),
        name="company-detail",
    ),
    path(
        "connect-instagram/<int:company_id>/",
        views.CompanyDetailView.as_view(),
        name="connect-instagram",
    ),
    path(
        "company/<int:company_id>/instagram/posts/",
        views.get_instagram_posts,
        name="get_instagram_posts",
    ),
    path('company/<int:company_id>/listing/<int:listing_id>/delete/', views.ListingDeleteView.as_view(), name='delete_listing'),
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
