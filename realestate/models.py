# pylint:disable=all
from django.db import models
from users.models import CustomUser
from django.db.models import (
    CharField,
    EmailField,
    DateTimeField,
    DecimalField,
    JSONField,
    TextField,
    BooleanField,
    IntegerField,
    ForeignKey,
    FloatField
)


class PropertyListing(models.Model):
    PROPERTY_TYPES = [
        ("residential", "Residential"),
        ("commercial", "Commercial"),
        ("land", "Land"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("available", "Available"),
        ("sold", "Sold"),
        ("rented", "Rented"),
        ("unavailable", "Unavailable"),
    ]

    LAND_UNIT_CHOICES = [
        ("cent", "Cent"),
        ("acre", "Acre"),
        ("sqft", "Square Feet"),
        ("sqm", "Square Meter"),
    ]

    CURRENCY_CHOICES = [
        ("INR", "Indian Rupee"),
        ("USD", "US Dollar"),
        ("EUR", "Euro"),
    ]

    PRICE_TYPE_CHOICES = [
        ("total", "Total Price"),
        ("per_unit", "Per Unit Rate"),
    ]

    company = models.ForeignKey(
        "Company", on_delete=models.CASCADE, related_name="properties"
    )

    # Core property details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    property_type = models.CharField(
        max_length=50, choices=PROPERTY_TYPES, default="residential"
    )
    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, default="available"
    )

    # Location & Pricing
    location = models.CharField(max_length=255)
    price_type = models.CharField(
        max_length=20, choices=PRICE_TYPE_CHOICES, default="total"
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=50, choices=CURRENCY_CHOICES, default="INR")

    # Residential-specific fields (optional)
    bedrooms = models.IntegerField(null=True, blank=True)
    bathrooms = models.IntegerField(null=True, blank=True)
    area_sqft = models.FloatField(null=True, blank=True)
    amenities = models.TextField(blank=True)

    land_unit = models.CharField(
        max_length=20, choices=LAND_UNIT_CHOICES, blank=True, null=True
    )
    land_area = models.FloatField(null=True, blank=True)

    # Instagram mapping
    instagram_post_id = models.CharField(
        max_length=255, blank=True, null=True, unique=True
    )

    # AI / RAG metadata (optional for context feeding)
    ai_context_notes = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.title} ({self.company.name}) - {self.property_type} - {self.status}"
        )

    class Meta:
        verbose_name = "Property Listing"
        verbose_name_plural = "Property Listings"
        ordering = ["-created_at"]

    @property
    def is_instagram_connected(self):
        """Returns True if instagram_post_id is a valid number."""
        if self.instagram_post_id:
            try:
                int(self.instagram_post_id)
                return True
            except ValueError:
                return False
        return False


# Create your models here.
class Company(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,  # keeps company even if user is deleted
        null=True,
        blank=True,
        related_name="companies_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# Role choices
ROLE_CHOICES = [
    ("admin", "Admin"),
    ("manager", "Manager"),
    ("agent", "Agent"),
]


class Membership(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="memberships"
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "company")


class Lead(models.Model):
    # Relationships
    company = models.ForeignKey(Company, on_delete=models.SET_NULL,null=True)
    listing = models.ForeignKey(PropertyListing, null=True, blank=True, on_delete=models.SET_NULL)

    # Source Tracking
    source_type = CharField(
        choices=[
            ("instagram_comment", "Instagram Comment"),
            ("instagram_dm", "Instagram DM"),
        ]
    )
    instagram_post_id = CharField()
    instagram_comment_id = CharField(null=True)
    instagram_conversation_id = CharField(null=True)

    # Customer Info (Collected by AI)
    customer_name = CharField(blank=True, null=True)
    instagram_username = CharField()
    phone_number = CharField(null=True, blank=True)
    email = EmailField(null=True, blank=True)

    # Qualification Status
    qualification_status = CharField(
        choices=[
            ("initiated", "Conversation Initiated"),
            ("in_progress", "Qualifying"),
            ("qualified", "Qualified"),
            ("unqualified", "Not Qualified"),
            ("no_response", "No Response"),
            ("ready_for_agent", "Ready for Human Agent"),
        ],
        default="initiated",
    )

    # Pre-Qualification Data (AI Collected)
    budget_min = DecimalField(null=True, blank=True, decimal_places=2,max_digits=20)
    budget_max = DecimalField(null=True, blank=True,decimal_places=2,max_digits=20)
    timeline = CharField(
        choices=[
            ("immediate", "Immediate (0-2 weeks)"),
            ("short", "Short-term (1-3 months)"),
            ("medium", "Medium-term (3-6 months)"),
            ("long", "Long-term (6+ months)"),
            ("just_browsing", "Just Browsing"),
        ],
        null=True,
        blank=True,
    )

    preferred_location = CharField(blank=True)
    property_requirements = JSONField(default=dict)  # bedrooms, sqft, etc.
    payment_method = CharField(
        choices=[
            ("cash", "Cash"),
            ("loan", "Home Loan"),
            ("both", "Both Options"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )

    is_first_time_buyer = BooleanField(null=True)
    has_property_to_sell = BooleanField(null=True)

    # AI Scoring & Analysis
    lead_score = IntegerField(default=0)  # 0-100
    intent_level = CharField(
        choices=[
            ("low", "Low Intent"),
            ("medium", "Medium Intent"),
            ("high", "High Intent"),
            ("hot", "Hot Lead - Ready to Buy"),
        ],
        default="low",
    )

    ai_conversation_summary = TextField(blank=True)
    qualification_data = JSONField(default=dict)  # Full AI analysis

    # Conversation Tracking
    total_messages = IntegerField(default=0)
    last_bot_message = TextField(blank=True)
    last_customer_message = TextField(blank=True)
    last_interaction_at = DateTimeField(null=True)
    conversation_stage = CharField(
        max_length=50, default="greeting"
    )  # greeting, budget, timeline, etc.

    # Human Agent Handoff
    requires_human = BooleanField(default=False)
    human_agent_assigned = ForeignKey(CustomUser, on_delete=models.SET_NULL,null=True, blank=True)
    handoff_reason = TextField(blank=True)
    handoff_at = DateTimeField(null=True, blank=True)

    # Status & Notes
    status = CharField(
        choices=[
            ("active", "Active Conversation"),
            ("qualified_hot", "Qualified - Hot Lead"),
            ("qualified_warm", "Qualified - Warm Lead"),
            ("qualified_cold", "Qualified - Cold Lead"),
            ("unqualified", "Unqualified"),
            ("spam", "Spam"),
            ("closed_won", "Closed - Won"),
            ("closed_lost", "Closed - Lost"),
        ],
        default="active",
    )

    agent_notes = TextField(blank=True)
    tags = JSONField(default=list)

    # Timestamps
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    qualified_at = DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return self.instagram_username


class ConversationMessage(models.Model):
    """Track every message in the qualification conversation"""

    lead = ForeignKey(Lead, related_name="messages",null=True, on_delete=models.SET_NULL)
    conversation_id = CharField(null=False, default=None)

    sender_type = CharField(
        choices=[
            ("customer", "Customer"),
            ("ai_bot", "AI Bot"),
            ("human_agent", "Human Agent"),
        ]
    )

    message_text = TextField()
    message_type = CharField(
        choices=[
            ("initial_inquiry", "Initial Inquiry"),
            ("qualification_question", "Qualification Question"),
            ("information_response", "Information Response"),
            ("follow_up", "Follow Up"),
            ("handoff", "Agent Handoff"),
        ]
    )

    # AI Context
    extracted_data = JSONField(default=dict)  # What AI learned from this message
    confidence_score = FloatField(null=True)  # AI's confidence in extraction

    # Instagram Metadata
    instagram_message_id = CharField(max_length=255, unique=True, null=True)
    is_from_instagram = BooleanField(default=True)

    timestamp = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return str(self.lead.instagram_conversation_id) if self.lead.instagram_conversation_id else "Unknown"

class QualificationQuestion(models.Model):
    """Questions AI asks to qualify leads"""

    company = ForeignKey(Company, on_delete=models.SET_NULL,null=True, blank=True)  # Company-specific or global

    question_stage = CharField(
        choices=[
            ("greeting", "Initial Greeting"),
            ("budget", "Budget Discovery"),
            ("timeline", "Timeline/Urgency"),
            ("requirements", "Property Requirements"),
            ("contact", "Contact Information"),
            ("financing", "Financing/Payment"),
            ("closing", "Closing/Next Steps"),
        ]
    )

    question_text = TextField()
    question_order = IntegerField()
    is_required = BooleanField(default=False)

    # Conditional Logic
    show_if_condition = JSONField(null=True, blank=True)  # Show only if X
    property_type = CharField(null=True, blank=True)  # residential, commercial, land

    # Response Expectations
    expected_response_type = CharField(
        choices=[
            ("text", "Free Text"),
            ("number", "Numeric"),
            ("yes_no", "Yes/No"),
            ("multiple_choice", "Multiple Choice"),
        ]
    )

    # AI Extraction
    data_field_to_extract = CharField()  # Which Lead field to populate
    extraction_patterns = JSONField(default=list)  # Regex or keywords to look for

    is_active = BooleanField(default=True)

    class Meta:
        ordering = ["question_order"]
