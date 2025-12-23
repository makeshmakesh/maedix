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
        "company/<int:company_id>/instagram/posts/",
        views.get_instagram_posts,
        name="get_instagram_posts",
    ),
    path('company/<int:company_id>/listing/<int:listing_id>/delete/', views.ListingDeleteView.as_view(), name='delete_listing'),
    
    path(
        "company/<int:company_id>/leads/",
        views.LeadsView.as_view(),
        name="leads",
    ),
    path(
        "company/<int:company_id>/reports/",
        views.ReportsView.as_view(),
        name="reports",
    ),
    path(
        "company/<int:company_id>/inbox/",
        views.InboxView.as_view(),
        name="inbox",
    ),
    path(
        "company/<int:company_id>/chat/<int:lead_id>/",
        views.ChatView.as_view(),
        name="chat",
    ),
    path(
        "company/<int:company_id>/chat/<int:lead_id>/send/",
        views.SendMessageView.as_view(),
        name="send-message",
    ),
    path(
        "company/<int:company_id>/lead/<int:lead_id>/assign-agent/",
        views.AssignAgentView.as_view(),
        name="assign-agent",
    ),
    path(
        "company/<int:company_id>/lead-detail/<int:lead_id>",
        views.LeadDetailView.as_view(),
        name="lead-detail",
    ),
    path(
        "company/<int:company_id>/invitations/",
        views.InvitationsView.as_view(),
        name="invitations",
    ),
    path(
        "my-invitations/",
        views.MyInvitationsView.as_view(),
        name="my-invitations",
    ),
    path(
        "accept-invitation/<int:invitation_id>",
        views.AcceptInvitationView.as_view(),
        name="accept-invitation",
    ),
    path("company-manage/<int:company_id>/", views.CompanyManageView.as_view(), name="company-manage"),
    path('api/instagram/posts/<int:company_id>/', views.get_instagram_posts, name='get_instagram_posts'),
    path('create-company/', views.create_company, name='create-company'),
    path('/<int:company_id>/listing/<int:listing_id>/add-lead/', views.add_lead_to_listing, name='add_lead_to_listing'),
    path('/<int:company_id>/listing/<int:listing_id>/remove-lead/', views.remove_lead_from_listing, name='remove_lead_from_listing'),
    
    
    path(
        '/<int:company_id>/listing/<int:listing_id>/share/create/',
        views.create_lead_share,
        name='create_lead_share'
    ),
    path(
        '/<int:company_id>/listing/<int:listing_id>/shares/',
        views.list_lead_shares,
        name='list_lead_shares'
    ),
    path(
        '/<int:company_id>/share/<int:share_id>/revoke/',
        views.revoke_lead_share,
        name='revoke_lead_share'
    ),
    
    # Public share view (no login)
    path(
        'shared/<str:token>/',
        views.PublicLeadShareView.as_view(),
        name='public_lead_share'
    ),
    path('/<int:company_id>/leads/create/', views.CreateLeadView.as_view(), name='create-lead'),
        
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
