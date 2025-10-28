#pylint:disable=all
from django.urls import path
from . import views

urlpatterns = [
    # ... other patterns
    path('company/<int:company_id>/instagram/connect/', views.InstagramConnectView.as_view(), name='instagram_connect'),
    path('company/<int:company_id>/fb/oauth/', views.FBOAuthRedirectView.as_view(), name='fb_oauth'),
    path('company/<int:company_id>/instagram/oauth/', views.InstagramOAuthRedirectView.as_view(), name='instagram_oauth'),
    path('callback/fb/', views.FBCallbackView.as_view(), name='fb_callback'),
    path('callback/instagram/', views.InstagramCallbackView.as_view(), name='instagram_callback'),
    path('webhook/', views.InstagramWebHookView.as_view(), name='instagram_webhook'),
    path('facebook/', views.InstagramWebHookView.as_view(), name='facebook'),
    path('save-token/', views.instagram_save_token, name='instagram_save_token'),
    path('event-subscribe/<int:company_id>/', views.InstagramWebHookSubscribe.as_view(), name="event-subscribe"),
    path('company/<int:company_id>/instagram/disconnect/', views.InstagramDisconnectView.as_view(), name='instagram_disconnect'),
    path('company/<int:company_id>/fb/disconnect/', views.FBDisconnectView.as_view(), name='fb_disconnect'),
]