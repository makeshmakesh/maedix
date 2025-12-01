#pylint:disable=all
from django.db import models
from realestate.models import Company
from users.models import CustomUser
from django.utils import timezone
# Create your models here.
class Configuration(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.key} = {self.value}"

    @staticmethod
    def get_value(key, default=None):
        try:
            return Configuration.objects.get(key=key).value
        except Configuration.DoesNotExist:
            return default

    @staticmethod
    def set_value(key, value):
        obj, created = Configuration.objects.update_or_create(
            key=key, defaults={"value": value}
        )
        return obj
    


class Subscription(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    plan_id = models.CharField(max_length=50)
    plan_name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")
    billing_cycle = models.CharField(max_length=10, default="month")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    renewal_date = models.DateTimeField()
    data = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="active")
    is_auto_renew = models.BooleanField(default=True)
    lead_quota = models.IntegerField(default=0)
    leads_used = models.IntegerField(default=0)
    messages_used = models.IntegerField(default=0)
    last_reset_date = models.DateTimeField()
    next_reset_date = models.DateTimeField()
    payment_reference = models.CharField(max_length=255, null=True)
    support_tier = models.CharField(max_length=50, default="standard")
    integration_channels = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    def is_active(self):
        return self.status == "active" and self.end_date > timezone.now()
    
    def lead_quota_exceeded(self):
        return (self.leads_used >= self.lead_quota)
    
    def has_permission(self, feature_name):
        features_allowed = self.data.get("features_allowed", [])
        for feature in features_allowed:
            if feature.get("name") == feature_name:
                return True
        return False
    
    def get_feature(self, feature_name):
        features_allowed = self.data.get("features_allowed", [])
        for feature in features_allowed:
            if feature.get("name") == feature_name:
                return feature
        return None


class Transaction(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("card", "Credit Card"),
        ("paypal", "PayPal"),
        ("gpay", "Google Pay"),
        ("razorpay", "Razorpay"),
    ]

    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    order_id = models.CharField(max_length=100, blank=True, null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    plan_id = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.transaction_id} - {self.status}"
    
    
class EventRegister(models.Model):
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=50)
    payload = models.JSONField()
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='processed')
    
    class Meta:
        indexes = [
            models.Index(fields=['event_id', 'processed_at']),
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.event_id}"