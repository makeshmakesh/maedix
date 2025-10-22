from django.contrib import admin
from instagram.models import InstagramAccount
# Register your models here.
@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    pass