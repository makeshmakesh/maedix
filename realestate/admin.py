#pylint:disable=all
from django.contrib import admin

from .models import Company, Membership, PropertyListing, Lead, ConversationMessage
@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    pass
@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    pass
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    pass


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    pass


@admin.register(PropertyListing)
class PropertyListingAdmin(admin.ModelAdmin):
    pass