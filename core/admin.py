#pylint:disable=all
from django.contrib import admin
from .models import Configuration, Subscription
# Register your models here.

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    pass

@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    pass