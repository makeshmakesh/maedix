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
from pgvector.django import VectorField
from django.utils import timezone
from django.core.exceptions import ValidationError
import secrets
from datetime import timedelta

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
    embedding = VectorField(dimensions=3072, null=True)
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
    
    
    def summarize_property(self) -> str:
        """Create a concise but complete text summary for LLM context."""
        summary = (
            f"🏡 {self.title}\n"
            f"Type: {self.get_property_type_display()} | Status: {self.get_status_display()}\n"
            f"Location: {self.location}\n"
            f"Company: {self.company.name if self.company_id and self.company else '-'}\n"
            f"Price: {self.price or '-'} {self.currency} ({self.get_price_type_display()})\n"
            f"Bedrooms: {self.bedrooms or '-'} | Bathrooms: {self.bathrooms or '-'}\n"
            f"Area: {self.area_sqft or '-'} sqft\n"
            f"Land Area: {self.land_area or '-'} {self.get_land_unit_display() if self.land_unit else '-'}\n"
            f"Amenities: {self.amenities or '-'}\n"
            f"Description: {(self.description[:400] + '...') if self.description and len(self.description) > 400 else (self.description or '-')}\n"
            f"Additional Info: {self.ai_context_notes or '-'}\n"
            f"Created: {self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '-'} | "
            f"Updated: {self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '-'}"
        )
        return summary



# Create your models here.
class Company(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True)
    detail = models.JSONField(default=dict, blank=True)
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


class Membership(models.Model):
    ROLE_CHOICES = [
    ("admin", "Admin"),
    ("manager", "Manager"),
    ("agent", "Agent"),
]

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
    metadata = JSONField(default=dict)

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
            ("user", "User"),
            ("assistant", "AI Assistant"),
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
        return "Unknown"

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



class CompanyInvitation(models.Model):
    """Invitation requests for users to join a company"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    
    # Invitation details
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='invitations')
    invited_email = models.EmailField(help_text="Email of the user being invited")
    
    # Who invited
    invited_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='invitations_sent')
    
    # Role to assign when accepted
    role = models.CharField(
        max_length=20,
        choices=Membership.ROLE_CHOICES,
        default='agent',
        help_text="Role that will be assigned when invitation is accepted"
    )
    
    # Invitation message/notes
    message = models.TextField(blank=True, help_text="Custom message for the invited user")
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # If invitation is accepted, link to the membership
    accepted_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invitations_accepted'
    )
    membership = models.OneToOneField(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invitation'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(help_text="Invitation expiry date")
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('company', 'invited_email', 'status')  # One active invitation per email per company
        verbose_name_plural = 'Company Invitations'
    
    def __str__(self):
        return f"Invitation to {self.invited_email} for {self.company.name} ({self.status})"
    
    def is_expired(self):
        """Check if invitation has expired"""
        return timezone.now() > self.expires_at
    
    def can_accept(self):
        """Check if invitation can be accepted"""
        return (
            self.status == 'pending' and
            not self.is_expired()
        )
    
    def accept_invitation(self, user):
        """Accept invitation and create membership"""
        if not self.can_accept():
            raise ValidationError("This invitation cannot be accepted")
        
        if user.email != self.invited_email:
            raise ValidationError("Invitation email does not match user email")
        
        # Create membership
        membership, created = Membership.objects.get_or_create(
            user=user,
            company=self.company,
            defaults={'role': self.role}
        )
        
        # Update invitation
        self.status = 'accepted'
        self.accepted_by = user
        self.accepted_at = timezone.now()
        self.membership = membership
        self.save()
        
        return membership
    
    def reject_invitation(self):
        """Reject invitation"""
        if self.status != 'pending':
            raise ValidationError("Only pending invitations can be rejected")
        
        self.status = 'rejected'
        self.save()
        
        



class LeadListing(models.Model):
    """Associates leads with property listings they're interested in."""

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="lead_listings"
    )
    listing = models.ForeignKey(
        PropertyListing,
        on_delete=models.CASCADE,
        related_name="lead_listings"
    )
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("lead", "listing")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lead.instagram_username} → {self.listing.title}"
    
    
    




def generate_share_token():
    return secrets.token_urlsafe(24)


def default_expiry():
    return timezone.now() + timedelta(days=30)


class LeadShare(models.Model):
    """Shareable link for property owners to view leads."""
    
    token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_share_token,
        editable=False
    )
    company = models.ForeignKey(
        'Company',
        on_delete=models.CASCADE,
        related_name='lead_shares'
    )
    listing = models.ForeignKey(
        'PropertyListing',
        on_delete=models.CASCADE,
        related_name='lead_shares'
    )
    created_by = models.ForeignKey(
        'users.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='lead_shares_created'
    )
    
    # Owner info
    owner_name = models.CharField(max_length=255)
    
    # Privacy settings
    show_contact_info = models.BooleanField(
        default=False,
        help_text="If True, owner can see lead phone/email"
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(default=default_expiry)
    
    # Tracking
    view_count = models.IntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lead Share"
        verbose_name_plural = "Lead Shares"

    def __str__(self):
        return f"Share for {self.listing.title} → {self.owner_name}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    def record_view(self):
        """Call this when owner views the shared page."""
        self.view_count += 1
        self.last_viewed_at = timezone.now()
        self.save(update_fields=['view_count', 'last_viewed_at'])

    def get_leads(self):
        """Get all leads associated with this listing."""
        from core.models import LeadListing
        lead_listings = LeadListing.objects.filter(
            listing=self.listing
        ).select_related('lead')
        return [ll.lead for ll in lead_listings]