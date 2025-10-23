#pylint:disable=all
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from openai import OpenAI
from .models import PropertyListing
import threading
client = OpenAI()


def build_embedding_text(instance: PropertyListing) -> str:
    """Combine key fields into a single text block for embedding."""
    parts = [
        f"Title: {instance.title}",
        f"Type: {instance.property_type}",
        f"Status: {instance.status}",
        f"Location: {instance.location}",
        f"Price: {instance.price} {instance.currency} ({instance.price_type})",
        f"Bedrooms: {instance.bedrooms or '-'}",
        f"Bathrooms: {instance.bathrooms or '-'}",
        f"Area: {instance.area_sqft or '-'} sqft",
        f"Amenities: {instance.amenities or '-'}",
        f"Description: {instance.description or '-'}",
    ]
    return "\n".join(parts)

def generate_embedding_async(instance_id, text):
    """Run embedding generation in background thread."""
    try:
        embedding = client.embeddings.create(
            model="text-embedding-3-large",
            input=text
        ).data[0].embedding
        PropertyListing.objects.filter(id=instance_id).update(embedding=embedding)
        print(f"✅ Embedding updated for property {instance_id}")
    except Exception as e:
        print(f"❌ Embedding failed for property {instance_id}: {e}")

@receiver(post_save, sender=PropertyListing)
def create_embedding(sender, instance, **kwargs):
    if not instance.title and not instance.description:
        return
    text = build_embedding_text(instance)
    threading.Thread(
        target=generate_embedding_async,
        args=(instance.id, text),
        daemon=True,
    ).start()