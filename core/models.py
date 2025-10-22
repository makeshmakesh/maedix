#pylint:disable=all
from django.db import models

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