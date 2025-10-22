#pylint:disable=all
from django.db import models

# Create your models here.
class InstagramAccount(models.Model):
    company = models.OneToOneField("realestate.Company", on_delete=models.CASCADE, related_name='instagram_account')
    
    # Instagram Business Account Details
    instagram_business_account_id = models.CharField(max_length=255, unique=True)
    username = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True)
    profile_picture_url = models.URLField(blank=True, null=True)
    
    access_token = models.TextField()  # Long-lived user access token
    webhook_subscribed = models.BooleanField(null=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    page_data = models.JSONField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(auto_now=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"@{self.username} - {self.company.name}"

    class Meta:
        verbose_name = "Instagram Account"
        verbose_name_plural = "Instagram Accounts"