#pylint:disable=all
from django.contrib import admin
from .models import Configuration
# Register your models here.
@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    pass