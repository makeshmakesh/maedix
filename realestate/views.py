# pylint:disable=all
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from .models import Membership, Company, PropertyListing
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.contrib import messages
import requests
from django.contrib.auth.decorators import login_required



def calculate_lead_score(lead):
    score = 0
    
    # Budget signals (max 30 points)
    if lead.budget_max:
        if lead.listing and lead.budget_max >= lead.listing.price:
            score += 30
        elif lead.budget_max >= 5000000:  # High budget
            score += 20
    
    # Timeline urgency (max 25 points)
    if lead.timeline == 'immediate':
        score += 25
    elif lead.timeline == 'short':
        score += 15
    
    # Contact info provided (max 20 points)
    if lead.phone_number:
        score += 15
    if lead.email:
        score += 5
    
    # Engagement quality (max 15 points)
    if lead.total_messages >= 5:
        score += 15
    elif lead.total_messages >= 3:
        score += 10
    
    # Requirements match (max 10 points)
    if lead.property_requirements:
        score += 10
    
    return min(score, 100)
# Create your views here.
class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        memberships = Membership.objects.filter(user=request.user)
        context = {"memberships": memberships}
        return render(request, "realestate/dashboard.html", context)


class CompanyDetailView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        memberships = Membership.objects.filter(user=request.user)
        for membership in memberships:
            if company_id == membership.company.id:
                company = Company.objects.get(id=company_id)
                context = {"company": company, "membership" : membership}
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


class ListingCreateView(LoginRequiredMixin, View):
    def post(self, request, company_id):
        company = get_object_or_404(Company, id=company_id)
        
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
        context = {
            'company': company,
            'listing': listing,
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
    
    
    # Check if Instagram is connected
    if not hasattr(company, 'instagram_account') or not company.instagram_account.is_active:
        return JsonResponse({
            'success': False,
            'error': 'Instagram account not connected. Please connect your Instagram account first.'
        })
    
    instagram_account = company.instagram_account
    try:
        # Fetch media from Instagram Graph API
        media_url = f"https://graph.instagram.com/v24.0/{instagram_account.instagram_business_account_id}/media"
        params = {
            'fields': 'id,media_type,media_url,thumbnail_url,timestamp,caption',
            'access_token': instagram_account.access_token,
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