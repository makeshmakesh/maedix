#pylint:disable=all
from django.db import models

# Create your models here.
class InstagramAccount(models.Model):
    company = models.OneToOneField("realestate.Company", on_delete=models.CASCADE, related_name='instagram_account')
    
    # Instagram Business Account Details
    instagram_data = models.JSONField(null=True, blank=True)
    fb_data = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company.name}"

    class Meta:
        verbose_name = "Instagram Account"
        verbose_name_plural = "Instagram Accounts"