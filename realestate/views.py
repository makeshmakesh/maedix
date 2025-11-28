# pylint:disable=all
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET
from users.models import CustomUser
from .models import Membership, Company, PropertyListing, Lead, ConversationMessage, CompanyInvitation,LeadListing, LeadShare
from core.models import Subscription
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.contrib import messages
import requests
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from instagram.models import InstagramAccount


from django.utils import timezone
from datetime import timedelta


def calculate_lead_score(lead: Lead) -> int:
    """
    Calculate lead quality score (0-100) based on multiple factors.
    
    Scoring breakdown:
    - Budget alignment: 25 points
    - Timeline urgency: 20 points
    - Contact information: 20 points
    - Engagement quality: 20 points
    - Intent level: 10 points
    - Payment method clarity: 5 points
    """
    score = 0
    
    # ============================================
    # 1. BUDGET ALIGNMENT (max 25 points)
    # ============================================
    if lead.budget_max:
        # Exact match with listing (best case)
        if lead.listing and lead.budget_max >= lead.listing.price:
            score += 25
        # High budget signals strong buying power
        elif lead.budget_max >= 10000000:  # 1 crore+
            score += 25
        elif lead.budget_max >= 5000000:  # 50L+
            score += 20
        elif lead.budget_max >= 2000000:  # 20L+
            score += 12
        else:
            score += 5  # Some budget provided
    elif lead.budget_min:
        # At least minimum provided
        if lead.budget_min >= 5000000:
            score += 15
        else:
            score += 5
    
    # ============================================
    # 2. TIMELINE URGENCY (max 20 points)
    # ============================================
    if lead.timeline == 'immediate':
        score += 20  # Buying ASAP
    elif lead.timeline == 'short':
        score += 15  # 1-3 months
    elif lead.timeline == 'medium':
        score += 8   # 3-6 months
    elif lead.timeline == 'long':
        score += 3   # 6+ months
    elif lead.timeline == 'just_browsing':
        score += 1   # Very low priority
    
    # ============================================
    # 3. CONTACT INFORMATION (max 20 points)
    # ============================================
    contact_score = 0
    if lead.phone_number:
        contact_score += 15  # Phone = most important for follow-up
    if lead.email:
        contact_score += 5   # Email = secondary contact
    
    # Bonus: Both provided = maximum follow-up potential
    if lead.phone_number and lead.email:
        contact_score = 20
    
    score += contact_score
    
    # ============================================
    # 4. ENGAGEMENT QUALITY (max 20 points)
    # ============================================
    engagement_score = 0
    
    # Message count indicates interaction
    if lead.total_messages >= 10:
        engagement_score += 15
    elif lead.total_messages >= 6:
        engagement_score += 12
    elif lead.total_messages >= 3:
        engagement_score += 8
    elif lead.total_messages >= 1:
        engagement_score += 3
    
    # Recency bonus: Fresh conversations are more likely to convert
    if lead.last_interaction_at:
        time_since_last = timezone.now() - lead.last_interaction_at
        if time_since_last < timedelta(hours=1):
            engagement_score += 5  # Hot conversation
        elif time_since_last < timedelta(days=1):
            engagement_score += 3  # Recent
        elif time_since_last > timedelta(days=7):
            engagement_score -= 3  # Stale lead
    
    score += min(engagement_score, 20)  # Cap at 20
    
    # ============================================
    # 5. INTENT LEVEL (max 10 points)
    # ============================================
    if lead.intent_level == 'hot':
        score += 10
    elif lead.intent_level == 'high':
        score += 8
    elif lead.intent_level == 'medium':
        score += 4
    elif lead.intent_level == 'low':
        score += 1
    
    # ============================================
    # 6. PAYMENT METHOD CLARITY (max 5 points)
    # ============================================
    if lead.payment_method == 'cash':
        score += 5  # Cash = fastest, most reliable
    elif lead.payment_method == 'both':
        score += 4  # Open to options
    elif lead.payment_method == 'loan':
        score += 3  # Requires financing (more steps)
    
    # ============================================
    # 7. PROPERTY REQUIREMENTS SPECIFICITY (bonus +5 max)
    # ============================================
    if lead.property_requirements:
        requirements = lead.property_requirements
        specificity_count = 0
        
        # Count how specific they are
        if requirements.get('bedrooms'):
            specificity_count += 1
        if requirements.get('bathrooms'):
            specificity_count += 1
        if requirements.get('area_sqft'):
            specificity_count += 1
        if requirements.get('property_type'):
            specificity_count += 1
        if requirements.get('amenities'):
            specificity_count += 1
        
        # More specific = higher intent
        if specificity_count >= 4:
            score += 5
        elif specificity_count >= 2:
            score += 3
        elif specificity_count >= 1:
            score += 1
    
    # ============================================
    # 8. LOCATION SPECIFICITY (bonus +3 max)
    # ============================================
    if lead.preferred_location:
        # Specific location = higher intent
        location = lead.preferred_location.lower()
        
        # Very specific (includes area/neighborhood)
        if any(keyword in location for keyword in ['sector', 'lane', 'street', 'avenue', 'road', "street"]):
            score += 3
        # City mentioned
        elif len(location) > 10:  # Not just "Delhi" or "Mumbai"
            score += 2
        else:
            score += 1
    
    # ============================================
    # 9. BUYER TYPE SIGNALS (bonus +2 max)
    # ============================================
    buyer_signal = 0
    
    if lead.is_first_time_buyer is False:
        buyer_signal += 1  # Experienced buyer = faster decision
    
    if lead.has_property_to_sell is False:
        buyer_signal += 1  # No complications, ready to move
    
    score += buyer_signal
    
    # ============================================
    # 10. QUALIFICATION STATUS MULTIPLIER
    # ============================================
    # Boost score based on how far through qualification they are
    if lead.qualification_status == 'ready_for_agent':
        score = min(score + 10, 100)  # Boost if ready for agent
    elif lead.qualification_status == 'qualified':
        score = min(score + 5, 100)   # Already qualified
    elif lead.qualification_status == 'unqualified':
        score = max(score - 20, 0)    # Penalize unqualified
    
    # ============================================
    # FINAL SCORE CALCULATION
    # ============================================
    final_score = min(score, 100)
    
    return final_score

# Create your views here.
class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        memberships = Membership.objects.filter(user=request.user)
        context = {"memberships": memberships}
        return render(request, "realestate/dashboard.html", context)
from django import forms
class InviteUserForm(forms.Form):
    """Form to invite a user to company"""
    email = forms.EmailField(label="Email Address")
    role = forms.ChoiceField(
        choices=Membership.ROLE_CHOICES,
        label="Role"
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        label="Message (Optional)",
        required=False
    )


class AcceptInvitationView(LoginRequiredMixin, View):
    """User accepts an invitation"""
    
    def post(self, request, invitation_id):
        invitation = get_object_or_404(CompanyInvitation, id=invitation_id)
        
        # Verify the invitation is for this user
        if invitation.invited_email != request.user.email:
            messages.error(request, "This invitation is not for you")
            return redirect('my-invitations')
        
        try:
            membership = invitation.accept_invitation(request.user)
            messages.success(
                request,
                f"You have successfully joined {invitation.company.name} as {membership.get_role_display()}"
            )
        except Exception as e:
            messages.error(request, f"Error accepting invitation: {str(e)}")
        
        return redirect('my-invitations')
class MyInvitationsView(LoginRequiredMixin, View):
    def get(self, request):
        invitations = CompanyInvitation.objects.filter(invited_email=request.user.email, status="pending").order_by('-created_at')
        context = {
            "invitations": invitations,
        }
        return render(request, "realestate/my-invitations.html", context)
class InvitationsView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        membership = get_object_or_404(Membership, user=request.user, company_id=company_id)
        subscription = Subscription.objects.filter(company_id=company_id).first()
        if not subscription or not subscription.is_active() or not subscription.has_permission("multi_agent_collaboration"):
            messages.warning(request, "Your company subscription is inactive or do not have permissions to manage invitations. Please renew or upgrade to manage invitations.")
            return redirect('company-detail', company_id=company_id)
        if membership.role not in ['admin', 'manager']:
            messages.warning(request, "You do not have permission to view invitations for this company.")
            return redirect('company-detail', company_id=company_id)
        company = get_object_or_404(Company, id=company_id)
        form = InviteUserForm()
        pending_invitations = CompanyInvitation.objects.filter(status='pending').order_by('-created_at')
        context = {
            "company": company,
            "form": form,
            "pending_invitations": pending_invitations,
        }
        return render(request, "realestate/invitations.html", context)
    
    def post(self, request, company_id):
        company = get_object_or_404(Company, id=company_id, created_by=request.user)
        form = InviteUserForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            role = form.cleaned_data['role']
            
            # Check if user is already a member
            if Membership.objects.filter(
                company=company,
                user__email=email
            ).exists():
                messages.warning(request, f"User {email} is already a member of {company.name}")
                return redirect('invitations', company_id=company_id)
            
            # Create invitation
            invitation, created = CompanyInvitation.objects.get_or_create(
                company=company,
                invited_email=email,
                status='pending',
                defaults={
                    'invited_by': request.user,
                    'role': role,
                    'expires_at': timezone.now() + timedelta(days=7)  # Expires in 7 days
                }
            )
            
            if created:
                messages.success(request, f"Invitation sent to {email}")
            else:
                messages.info(request, f"Invitation already exists for {email}")
            
            return redirect('invitations', company_id=company_id)
        
        context = {
            'company': company,
            'form': form,
        }
        return render(request, 'realestate/invitations.html', context)


class CompanyDetailView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        memberships = Membership.objects.filter(user=request.user)
        for membership in memberships:
            if company_id == membership.company.id:
                company = Company.objects.get(id=company_id)
                leads_count = Lead.objects.filter(company=company).count()
                listings_count = PropertyListing.objects.filter(company=company).count()
                members_count = Membership.objects.filter(company=company).count()
                context = {"company": company, "membership" : membership, "leads_count": leads_count, "listings_count": listings_count, "members_count": members_count}
                return render(request, "realestate/company-detail.html", context)
        return JsonResponse({"error": "Unauthorized"}, status=401)


class ListingsView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)

        # Get all listings for this company
        listings = PropertyListing.objects.filter(company=company).order_by(
            "-created_at"
        )

        context = {
            "company": company,
            "listings": listings,
        }

        return render(request, "realestate/listings.html", context)

class LeadsView(LoginRequiredMixin, View):
    paginate_by = 15  # Leads per page
    
    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)

        # Start with all leads for this company
        membership = get_object_or_404(Membership, user=request.user, company=company)
        if membership.role not in ['admin', 'agent', "manager"]:
            return JsonResponse({"error": "Unauthorized"}, status=401)
        if membership.role == 'agent':
            leads = Lead.objects.filter(company=company, human_agent_assigned=request.user).order_by("-created_at")
        else:
            leads = Lead.objects.filter(company=company).order_by("-created_at")

        # Apply filters
        leads = self._apply_filters(leads, request)

        # Calculate lead scores
        leads_list = list(leads)
        for lead in leads_list:
            lead.lead_score = calculate_lead_score(lead)

        # Pagination
        paginator = Paginator(leads_list, self.paginate_by)
        page = request.GET.get('page', 1)

        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # Calculate stats
        leads_count = len(leads_list)
        qualified_count = sum(
            1 for lead in leads_list 
            if lead.status in ['qualified_hot', 'qualified_warm', 'qualified_cold']
        )
        hot_count = sum(1 for lead in leads_list if lead.status == 'qualified_hot')

        context = {
            "company": company,
            "page_obj": page_obj,
            "paginator": paginator,
            "is_paginated": paginator.num_pages > 1,
            "leads_count": leads_count,
            "qualified_count": qualified_count,
            "hot_count": hot_count,
            "leads": leads_list
        }

        return render(request, "realestate/leads.html", context)

    def _apply_filters(self, queryset, request):
        """Apply filtering based on query parameters"""
        
        # Status filter
        status = request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        # Intent level filter
        intent = request.GET.get('intent')
        if intent:
            queryset = queryset.filter(intent_level=intent)

        # Source filter
        # Search filter (username or email)
        search = request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(instagram_username__icontains=search) |
                Q(email__icontains=search) |
                Q(customer_name__icontains=search)
            )
        return queryset
class LeadDetailView(LoginRequiredMixin, View):
    def format_conversation_messages(self, messages):
        formatted_strings = []
        for msg in messages:
            formatted_strings.append(
                f"[{msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {msg.sender_type}: {msg.message_text}"
            )
        return "\n".join(formatted_strings)
    def get(self, request, company_id, lead_id):
        company = get_object_or_404(Company, id=company_id)
        lead = get_object_or_404(Lead, id=lead_id, company=company)

        # Calculate lead score
        score = calculate_lead_score(lead)
        conversations = ConversationMessage.objects.filter(lead=lead).order_by('timestamp')
        conversations_formatted = self.format_conversation_messages(conversations)
        available_agents = Membership.objects.filter(company=company)
        lead_listings = LeadListing.objects.filter(lead=lead).select_related('listing')
        context = {
            "company": company,
            "lead": lead,
            "score" :score,
            "conversations_formatted": conversations_formatted,
            "available_agents": available_agents,
            "lead_listings": lead_listings,
        }

        return render(request, "realestate/lead-detail.html", context)
    
    def post(self, request, company_id, lead_id):
        lead = get_object_or_404(Lead, id=lead_id, company_id=company_id)
        company = get_object_or_404(Company, id=company_id)
        # Update fields
        lead.customer_name = request.POST.get('customer_name', lead.customer_name)
        lead.email = request.POST.get('email', lead.email)
        lead.phone_number = request.POST.get('phone_number', lead.phone_number)
        lead.qualification_status = request.POST.get('qualification_status', lead.qualification_status)
        lead.status = request.POST.get('status', lead.status)
        lead.intent_level = request.POST.get('intent_level', lead.intent_level)
        lead.budget_min = request.POST.get('budget_min') or None
        lead.budget_max = request.POST.get('budget_max') or None
        lead.timeline = request.POST.get('timeline') or None
        lead.payment_method = request.POST.get('payment_method', lead.payment_method)
        lead.preferred_location = request.POST.get('preferred_location', lead.preferred_location)
        lead.is_first_time_buyer = 'is_first_time_buyer' in request.POST
        lead.has_property_to_sell = 'has_property_to_sell' in request.POST
        lead.agent_notes = request.POST.get('agent_notes', lead.agent_notes)
        
        
        lead.requires_human = 'requires_human' in request.POST
        
        if lead.requires_human:
            agent_id = request.POST.get('human_agent_assigned')
            if agent_id:
                try:
                    agent = CustomUser.objects.get(id=agent_id)
                    lead.human_agent_assigned = agent
                    lead.handoff_at = timezone.now()  # Set to current time
                except CustomUser.DoesNotExist:
                    pass
            
            lead.handoff_reason = request.POST.get('handoff_reason', lead.handoff_reason)
        else:
            # Clear handoff info if unchecked
            lead.human_agent_assigned = None
            lead.handoff_reason = ''
            lead.handoff_at = None
        lead.save()
        
        return redirect('lead-detail', company_id=company_id, lead_id=lead_id)
class ListingCreateView(LoginRequiredMixin, View):
    def post(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        subscription = Subscription.objects.filter(company=company).first()
        if not subscription or not subscription.is_active() or subscription.has_permission("property_listing_integration") is False:
            messages.warning(request, "Your company subscription is inactive or do not have permissions to create property listings. Please renew or upgrade to create listings.")
            return redirect('listings', company_id=company_id)
        listing_count = PropertyListing.objects.filter(company=company).count()
        feature = subscription.get_feature("property_listing_integration")
        if feature and feature.get("limit") is not None and listing_count >= feature.get("limit"):
            messages.warning(request, f"You have reached the listing limit of your current plan ({feature.get('limit')} listings). Please upgrade your plan to add more listings.")
            return redirect('listings', company_id=company_id)
        
        try:
            # Extract form data - Basic Information
            title = request.POST.get('title')
            description = request.POST.get('description', '')
            property_type = request.POST.get('property_type')
            status = request.POST.get('status')
            
            # Location & Pricing
            location = request.POST.get('location')
            price_type = request.POST.get('price_type', 'total')
            price = request.POST.get('price')
            currency = request.POST.get('currency', 'INR')
            
            # Property Details (Residential/Commercial)
            bedrooms = request.POST.get('bedrooms')
            bathrooms = request.POST.get('bathrooms')
            area_sqft = request.POST.get('area_sqft')
            amenities = request.POST.get('amenities', '')
            
            # Land-specific fields
            land_unit = request.POST.get('land_unit')
            land_area = request.POST.get('land_area')
            
            # Additional Information
            instagram_post_id = request.POST.get('instagram_post_id', '')
            ai_context_notes = request.POST.get('ai_context_notes', '')
            
            #instagram reply data
            instagram_comment_reply = request.POST.get('instagram_comment_reply', '')
            instagram_comment_dm_reply = request.POST.get('instagram_comment_dm_reply', '')
            instagram_comment_dm_reply_trigger_keyword = request.POST.get('instagram_comment_dm_reply_trigger_keyword', '')
            
            # Validate required fields
            if not all([title, property_type, status, location]):
                messages.error(request, "Please fill in all required fields.")
                return render(request, 'realestate/listing-create.html', {'company': company})
            
            # Create the listing
            listing = PropertyListing.objects.create(
                company=company,
                # Basic Information
                title=title,
                description=description,
                property_type=property_type,
                status=status,
                # Location & Pricing
                location=location,
                price_type=price_type,
                price=price if price else None,
                currency=currency,
                # Property Details
                bedrooms=bedrooms if bedrooms else None,
                bathrooms=bathrooms if bathrooms else None,
                area_sqft=area_sqft if area_sqft else None,
                amenities=amenities,
                # Land Details
                land_unit=land_unit if land_unit else None,
                land_area=land_area if land_area else None,
                # Additional Information
                instagram_post_id=instagram_post_id if instagram_post_id else None,
                ai_context_notes=ai_context_notes,
                metadata={
                    "instagram_comment_reply": instagram_comment_reply,
                    "instagram_comment_dm_reply": instagram_comment_dm_reply,
                    "instagram_comment_dm_reply_trigger_keyword": instagram_comment_dm_reply_trigger_keyword,
                }
            )
            
            messages.success(request, f"Property listing '{title}' created successfully!")
            return redirect('listings', company_id=company_id)
            
        except Exception as e:
            messages.error(request, f"Failed to create listing: {str(e)}")
            return render(request, 'realestate/listing-create.html', {'company': company})
    
    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        context = {
            'company': company,
        }
        return render(request, "realestate/listing-create.html", context)

class ListingEditView(LoginRequiredMixin, View):
    def get(self, request, company_id, listing_id):
        company = get_object_or_404(Company, id=company_id)
        listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
        lead_listings = LeadListing.objects.filter(listing=listing).select_related('lead')
        
        associated_lead_ids = lead_listings.values_list('lead_id', flat=True)
        available_leads = Lead.objects.filter(company=company).exclude(id__in=associated_lead_ids)
        context = {
            'company': company,
            'listing': listing,
            "lead_listings" :lead_listings,
            "available_leads": available_leads,
        }
        return render(request, "realestate/listing-edit.html", context)
    
    def post(self, request, company_id, listing_id):
        try:
            company = get_object_or_404(Company, id=company_id)
            listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
            
            # Update Basic Information
            listing.title = request.POST.get('title')
            listing.description = request.POST.get('description', '')
            listing.property_type = request.POST.get('property_type')
            listing.status = request.POST.get('status')
            
            # Update Location & Pricing
            listing.location = request.POST.get('location')
            listing.price_type = request.POST.get('price_type', 'total')
            listing.currency = request.POST.get('currency', 'INR')
            
            price = request.POST.get('price')
            listing.price = price if price else None
            
            # Update Property Details (Residential/Commercial)
            bedrooms = request.POST.get('bedrooms')
            listing.bedrooms = bedrooms if bedrooms else None
            
            bathrooms = request.POST.get('bathrooms')
            listing.bathrooms = bathrooms if bathrooms else None
            
            area_sqft = request.POST.get('area_sqft')
            listing.area_sqft = area_sqft if area_sqft else None
            
            listing.amenities = request.POST.get('amenities', '')
            
            # Update Land Details
            land_unit = request.POST.get('land_unit')
            listing.land_unit = land_unit if land_unit else None
            
            land_area = request.POST.get('land_area')
            listing.land_area = land_area if land_area else None
            
            # Update Additional Information
            instagram_post_id = request.POST.get('instagram_post_id', '')
            listing.instagram_post_id = instagram_post_id if instagram_post_id else None
            
            listing.ai_context_notes = request.POST.get('ai_context_notes', '')
            if listing.metadata is None:
                listing.metadata = {}
            listing.metadata["instagram_comment_reply"] = request.POST.get('instagram_comment_reply', '')
            listing.metadata["instagram_comment_dm_reply"] = request.POST.get('instagram_comment_dm_reply', '')
            listing.metadata["instagram_comment_dm_reply_trigger_keyword"] = request.POST.get('instagram_comment_dm_reply_trigger_keyword', '')
            
            # Validate required fields
            if not all([listing.title, listing.property_type, listing.status, listing.location]):
                messages.error(request, "Please fill in all required fields.")
                return render(request, 'realestate/listing-edit.html', {'company': company, 'listing': listing})
            
            listing.save()
            
            messages.success(request, f"Property listing '{listing.title}' updated successfully!")
            return redirect('listings', company_id=company_id)
            
        except Exception as e:
            messages.error(request, f"Failed to update listing: {str(e)}")
            return render(request, 'realestate/listing-edit.html', {'company': company, 'listing': listing})

class ListingDeleteView(LoginRequiredMixin, View):
    def post(self, request, company_id, listing_id):
        try:
            company = get_object_or_404(Company, id=company_id)
            membership = get_object_or_404(Membership, user=request.user, company=company)
            if membership.role not in ['admin', 'manager']:
                messages.error(request, "You do not have permission to delete listings for this company.")
                return redirect('listings', company_id=company_id)
            listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
            
            
            listing_title = listing.title
            listing.delete()
            
            messages.success(request, f"Property listing '{listing_title}' has been deleted successfully!")
            return redirect('listings', company_id=company_id)
            
        except Exception as e:
            messages.error(request, f"Failed to delete listing: {str(e)}")
            return redirect('listings', company_id=company_id)
    
    def get(self, request, company_id, listing_id):
        # Redirect GET requests to the listings page
        # (Delete should only be done via POST for safety)
        messages.warning(request, "Invalid delete request. Please use the delete button.")
        return redirect('listings', company_id=company_id)

@login_required
def get_instagram_posts(request, company_id):
    """Fetch Instagram posts for post selection"""
    company = get_object_or_404(Company, id=company_id)
    instagram_account = InstagramAccount.objects.filter(company=company).first()
    if not instagram_account:
        return JsonResponse({
            'success': False,
            'error': 'Instagram account not connected. Please connect your Instagram account first.'
        })
    
    access_token=instagram_account.instagram_data["access_token"]
    instagram_business_account_id = instagram_account.fb_data["instagram_business_account_id"]
    if not access_token or not instagram_business_account_id:
        return JsonResponse({
            'success': False,
            'error': 'Instagram account not properly configured. Please reconnect your Instagram account.'
        })
    try:
        # Fetch media from Instagram Graph API
        media_url = f"https://graph.instagram.com/v24.0/{instagram_business_account_id}/media"
        params = {
            'fields': 'id,media_type,media_url,thumbnail_url,timestamp,caption',
            'access_token': access_token,
            'limit': 50  # Get last 50 posts
        }
        
        response = requests.get(media_url, params=params)
        data = response.json()
        
        if 'error' in data:
            return JsonResponse({
                'success': False,
                'error': f"Instagram API error: {data['error'].get('message', 'Unknown error')}"
            })
        
        posts = data.get('data', [])
        
        return JsonResponse({
            'success': True,
            'posts': posts,
            'count': len(posts)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Failed to fetch Instagram posts: {str(e)}'
        })
        
class CompanyManageView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        membership = get_object_or_404(Membership, user=request.user, company=company)
        subscription = Subscription.objects.filter(company=company).first()
        if membership.role not in ['admin', 'manager']:
            messages.warning(request, "You do not have permission to manage this company.")
            return redirect('company-detail', company_id=company_id)
        context = {
            "company": company,
            "membership": membership,
            "subscription" : subscription,
        }
        return render(request, "realestate/manage-company.html", context)
    
    def post(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        membership = get_object_or_404(Membership, user=request.user, company=company)
        if membership.role not in ['admin', 'manager']:
            messages.warning(request, "You do not have permission to manage this company.")
            return redirect('company-detail', company_id=company_id)
        
        # Update company details
        company.name = request.POST.get('company_name', company.name)
        company.industry = request.POST.get('industry', company.industry)
        company.detail["static_dm_reply"] = request.POST.get('static_dm_reply', company.detail.get("static_dm_reply", ""))
        company.detail["static_comment_reply"] = request.POST.get('static_comment_reply', company.detail.get("static_comment_reply", ""))
        company.detail["static_comment_followup_dm_reply"] = request.POST.get('static_comment_followup_dm_reply', company.detail.get("static_comment_followup_dm_reply", ""))
        company.detail["enable_dm_response"] = 'enable_dm_response' in request.POST
        company.detail["enable_comment_reply"] = 'enable_comment_reply' in request.POST
        company.detail["enable_comment_reply_only_on_linked_instagram_post_on_property_listing"] = 'enable_comment_reply_only_on_linked_instagram_post_on_property_listing' in request.POST
        
        company.save()
        
        messages.success(request, f"Company '{company.name}' updated successfully!")
        return redirect('company-manage', company_id=company_id)
    

# views.py
@login_required
def create_company(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        industry = request.POST.get('industry', 'Real Estate')
        
        company = Company.objects.create(
            name=name,
            industry=industry,
            created_by=request.user,
            detail={
                "enable_dm_response": True,
                "enable_comment_reply": True,
                "static_dm_reply": "Thank you for reaching out! We'll get back to you shortly.",
                "static_comment_reply": "Thanks for your comment! We'll DM you shortly.",
                "static_comment_followup_dm_reply": "Thanks for engaging with our post! How can we assist you further?",
                "enable_comment_reply_only_on_linked_instagram_post_on_property_listing" : True,
            }
        )
        membership = Membership.objects.create(
            user=request.user,
            company=company,
            role="admin"
            
        )
        
        messages.success(request, f'Company "{company.name}" created successfully!')
        return redirect('dashboard')
    
    return render(request, 'realestate/create-company.html')



from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

@login_required
@require_POST
def add_lead_to_listing(request, company_id, listing_id):
    try:
        lead_id = request.POST.get('lead_id')
        if not lead_id:
            return JsonResponse({'success': False, 'error': 'Lead ID required'})
        
        company = get_object_or_404(Company, id=company_id)
        listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
        lead = get_object_or_404(Lead, id=lead_id, company=company)
        
        lead_listing, created = LeadListing.objects.get_or_create(
            lead=lead,
            listing=listing,
            defaults={'notes': 'Manually linked from listing page'}
        )
        
        if created:
            return JsonResponse({
                'success': True,
                'message': f'Lead @{lead.instagram_username} linked to listing',
                'lead': {
                    'id': lead.id,
                    'instagram_username': lead.instagram_username,
                    'customer_name': lead.customer_name or '',
                    'status': lead.status,
                    'status_display': lead.get_status_display(),
                    'intent_level': lead.intent_level,
                    'intent_display': lead.get_intent_level_display(),
                    'budget_max': str(lead.budget_max) if lead.budget_max else '',
                    'created_at': lead.created_at.strftime('%b %d, %Y'),
                },
                'lead_listing_id': lead_listing.id,
            })
        else:
            return JsonResponse({'success': False, 'error': 'Lead already linked'})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def remove_lead_from_listing(request, company_id, listing_id):
    try:
        lead_id = request.POST.get('lead_id')
        if not lead_id:
            return JsonResponse({'success': False, 'error': 'Lead ID required'})
        
        company = get_object_or_404(Company, id=company_id)
        listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
        
        deleted, _ = LeadListing.objects.filter(
            listing=listing,
            lead_id=lead_id
        ).delete()
        
        if deleted:
            return JsonResponse({'success': True, 'message': 'Lead unlinked from listing'})
        else:
            return JsonResponse({'success': False, 'error': 'Association not found'})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
    
    


@login_required
@require_POST
def create_lead_share(request, company_id, listing_id):
    """Create a new share link for a listing."""
    try:
        company = get_object_or_404(Company, id=company_id)
        listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
        
        owner_name = request.POST.get('owner_name', '').strip()
        if not owner_name:
            return JsonResponse({'success': False, 'error': 'Owner name is required'})
        
        show_contact_info = request.POST.get('show_contact_info') == 'true'
        
        lead_share = LeadShare.objects.create(
            company=company,
            listing=listing,
            created_by=request.user,
            owner_name=owner_name,
            show_contact_info=show_contact_info,
        )
        
        share_url = request.build_absolute_uri(f'/realestate/shared/{lead_share.token}/')
        
        return JsonResponse({
            'success': True,
            'message': 'Share link created successfully',
            'share': {
                'id': lead_share.id,
                'token': lead_share.token,
                'url': share_url,
                'owner_name': lead_share.owner_name,
                'show_contact_info': lead_share.show_contact_info,
                'expires_at': lead_share.expires_at.strftime('%b %d, %Y'),
                'created_at': lead_share.created_at.strftime('%b %d, %Y'),
                'view_count': lead_share.view_count,
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_GET
def list_lead_shares(request, company_id, listing_id):
    """List all shares for a listing."""
    try:
        company = get_object_or_404(Company, id=company_id)
        listing = get_object_or_404(PropertyListing, id=listing_id, company=company)
        
        shares = LeadShare.objects.filter(listing=listing, is_active=True)
        
        shares_data = []
        for share in shares:
            share_url = request.build_absolute_uri(f'/realestate/shared/{share.token}/')
            shares_data.append({
                'id': share.id,
                'token': share.token,
                'url': share_url,
                'owner_name': share.owner_name,
                'show_contact_info': share.show_contact_info,
                'expires_at': share.expires_at.strftime('%b %d, %Y'),
                'created_at': share.created_at.strftime('%b %d, %Y'),
                'view_count': share.view_count,
                'is_expired': share.is_expired,
                'last_viewed_at': share.last_viewed_at.strftime('%b %d, %Y %H:%M') if share.last_viewed_at else None,
            })
        
        return JsonResponse({'success': True, 'shares': shares_data})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def revoke_lead_share(request, company_id, share_id):
    """Revoke/deactivate a share link."""
    try:
        company = get_object_or_404(Company, id=company_id)
        lead_share = get_object_or_404(LeadShare, id=share_id, company=company)
        
        lead_share.is_active = False
        lead_share.save(update_fields=['is_active'])
        
        return JsonResponse({
            'success': True,
            'message': 'Share link revoked successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


class PublicLeadShareView(View):
    """Public view for property owners to see leads (no login required)."""
    
    def get(self, request, token):
        lead_share = get_object_or_404(LeadShare, token=token)
        
        # Check if valid
        if not lead_share.is_active:
            return render(request, 'realestate/shared-leads-expired.html', {
                'reason': 'revoked'
            })
        
        if lead_share.is_expired:
            return render(request, 'realestate/shared-leads-expired.html', {
                'reason': 'expired'
            })
        
        # Record the view
        lead_share.record_view()
        
        # Get leads for this listing
        lead_listings = LeadListing.objects.filter(
            listing=lead_share.listing
        ).select_related('lead')
        
        leads = [ll.lead for ll in lead_listings]
        
        context = {
            'share': lead_share,
            'company': lead_share.company,
            'listing': lead_share.listing,
            'leads': leads,
            'show_contact_info': lead_share.show_contact_info,
        }
        
        return render(request, 'realestate/shared-leads-public.html', context)