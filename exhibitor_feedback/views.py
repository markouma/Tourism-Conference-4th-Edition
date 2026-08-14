from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Avg, Q
from django.utils import timezone
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
import json
import time
from datetime import timedelta

from .models import ExhibitorStand, VisitorFeedback, FeedbackAnalytics


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@require_http_methods(["GET"])
def exhibitor_feedback_main(request):
    """Main interactive floor plan page"""
    stands = ExhibitorStand.objects.filter(is_active=True).prefetch_related('visitor_feedbacks')
    
    # Prepare stand data with basic stats
    stands_data = []
    for stand in stands:
        stands_data.append({
            'id': stand.id,
            'code': stand.stand_code,
            'name': stand.stand_name,
            'x': stand.floor_plan_x,
            'y': stand.floor_plan_y,
            'total_reviews': stand.total_reviews,
            'average_rating': stand.average_rating,
        })
    
    # Get country and industry lists for dropdowns
    countries = [
        "Kenya", "Uganda", "Tanzania", "Rwanda", "Burundi", "Ethiopia", "South Sudan",
        "United States", "United Kingdom", "Germany", "France", "China", "India", 
        "South Africa", "Nigeria", "Ghana", "Egypt", "Morocco", "Other"
    ]
    
    industries = [
        "Tourism & Hospitality", "Technology", "Finance & Banking", "Agriculture",
        "Manufacturing", "Education", "Healthcare", "Real Estate", "Retail",
        "Transportation & Logistics", "Media & Entertainment", "Government",
        "NGO/Non-Profit", "Consulting", "Other"
    ]
    
    context = {
        'stands': stands,
        'stands_json': json.dumps(stands_data),
        'countries': countries,
        'industries': industries,
    }
    
    return render(request, 'exhibitor_feedback/main.html', context)


@require_POST
@csrf_exempt
def submit_feedback_api(request):
    """API endpoint to submit feedback"""
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['stand_id', 'visitor_name', 'visitor_email', 'country', 'city', 'industry', 'rating', 'review_text']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'message': f'Missing required field: {field}'
                }, status=400)
        
        # Validate rating
        try:
            rating = int(data['rating'])
            if rating < 1 or rating > 5:
                return JsonResponse({
                    'success': False,
                    'message': 'Rating must be between 1 and 5'
                }, status=400)
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'message': 'Invalid rating value'
            }, status=400)
        
        # Get stand
        try:
            stand = ExhibitorStand.objects.get(id=data['stand_id'], is_active=True)
        except ExhibitorStand.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Invalid stand selected'
            }, status=404)
        
        # Check for duplicate review (same email for same stand)
        existing = VisitorFeedback.objects.filter(
            stand=stand,
            visitor_email=data['visitor_email'].lower().strip()
        ).first()
        
        if existing:
            # Update existing review
            existing.visitor_name = data['visitor_name'].strip()
            existing.visitor_phone = data.get('visitor_phone', '').strip()
            existing.country = data['country'].strip()
            existing.city = data['city'].strip()
            existing.industry = data['industry'].strip()
            existing.rating = rating
            existing.review_text = data['review_text'].strip()
            existing.ip_address = get_client_ip(request)
            existing.submitted_at = timezone.now()
            existing.save()
            
            feedback = existing
            is_new = False
        else:
            # Create new feedback
            feedback = VisitorFeedback.objects.create(
                stand=stand,
                visitor_name=data['visitor_name'].strip(),
                visitor_email=data['visitor_email'].lower().strip(),
                visitor_phone=data.get('visitor_phone', '').strip(),
                country=data['country'].strip(),
                city=data['city'].strip(),
                industry=data['industry'].strip(),
                rating=rating,
                review_text=data['review_text'].strip(),
                ip_address=get_client_ip(request)
            )
            is_new = True
        
        return JsonResponse({
            'success': True,
            'message': 'Thank you for your feedback!' if is_new else 'Your feedback has been updated!',
            'feedback': {
                'id': feedback.id,
                'stand_code': stand.stand_code,
                'stand_name': stand.stand_name,
                'visitor_name': feedback.visitor_first_name,
                'rating': feedback.rating,
                'review_text': feedback.review_text,
                'submitted_at': feedback.submitted_at.strftime('%b %d, %Y %H:%M'),
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        print(f"Error submitting feedback: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An error occurred. Please try again.'
        }, status=500)


@require_http_methods(["GET"])
def live_feedback_stream(request):
    """Server-Sent Events endpoint for real-time updates"""
    def event_stream():
        last_id = request.GET.get('last_id', 0)
        
        while True:
            # Get new feedbacks since last check
            new_feedbacks = VisitorFeedback.objects.filter(
                id__gt=last_id,
                is_approved=True
            ).select_related('stand').order_by('id')[:10]
            
            if new_feedbacks:
                for feedback in new_feedbacks:
                    data = {
                        'id': feedback.id,
                        'stand_id': feedback.stand.id,
                        'stand_code': feedback.stand.stand_code,
                        'stand_name': feedback.stand.stand_name,
                        'visitor_name': feedback.visitor_first_name,
                        'rating': feedback.rating,
                        'review_text': feedback.review_text,
                        'submitted_at': feedback.submitted_at.strftime('%b %d, %Y %H:%M'),
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    last_id = feedback.id
            
            time.sleep(2)  # Poll every 2 seconds
    
    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["GET"])
def public_reviews_api(request):
    """API to get paginated public reviews"""
    stand_id = request.GET.get('stand_id')
    page = request.GET.get('page', 1)
    
    feedbacks = VisitorFeedback.objects.filter(is_approved=True).select_related('stand')
    
    if stand_id:
        feedbacks = feedbacks.filter(stand_id=stand_id)
    
    feedbacks = feedbacks.order_by('-submitted_at')
    
    paginator = Paginator(feedbacks, 20)
    page_obj = paginator.get_page(page)
    
    data = {
        'reviews': [{
            'id': f.id,
            'stand_code': f.stand.stand_code,
            'stand_name': f.stand.stand_name,
            'visitor_name': f.visitor_first_name,
            'rating': f.rating,
            'review_text': f.review_text,
            'submitted_at': f.submitted_at.strftime('%b %d, %Y %H:%M'),
        } for f in page_obj],
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'total_pages': paginator.num_pages,
        'current_page': page_obj.number,
    }
    
    return JsonResponse(data)


@staff_member_required
def analytics_dashboard(request):
    """Admin analytics dashboard"""
    # Get all stands with analytics
    stands = ExhibitorStand.objects.filter(is_active=True).select_related('analytics')
    
    # Overall stats
    total_reviews = VisitorFeedback.objects.filter(is_approved=True).count()
    total_stands = stands.count()
    avg_rating_overall = VisitorFeedback.objects.filter(is_approved=True).aggregate(avg=Avg('rating'))['avg'] or 0
    
    # Top stands by reviews
    top_by_reviews = stands.annotate(
        review_count=Count('visitor_feedbacks')
    ).order_by('-review_count')[:10]
    
    # Top stands by rating
    top_by_rating = stands.annotate(
        avg_rating=Avg('visitor_feedbacks__rating'),
        review_count=Count('visitor_feedbacks')
    ).filter(review_count__gte=3).order_by('-avg_rating')[:10]
    
    # Geographic breakdown
    country_stats = VisitorFeedback.objects.filter(is_approved=True).values('country').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Industry breakdown
    industry_stats = VisitorFeedback.objects.filter(is_approved=True).values('industry').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Recent activity
    recent_reviews = VisitorFeedback.objects.filter(is_approved=True).select_related('stand').order_by('-submitted_at')[:10]
    
    context = {
        'total_reviews': total_reviews,
        'total_stands': total_stands,
        'avg_rating_overall': round(avg_rating_overall, 2),
        'top_by_reviews': top_by_reviews,
        'top_by_rating': top_by_rating,
        'country_stats': country_stats,
        'industry_stats': industry_stats,
        'recent_reviews': recent_reviews,
    }
    
    return render(request, 'exhibitor_feedback/analytics.html', context)


@staff_member_required
def analytics_data_api(request):
    """API endpoint for analytics data (for charts)"""
    metric = request.GET.get('metric', 'reviews')
    
    stands = ExhibitorStand.objects.filter(is_active=True).select_related('analytics')
    
    data = []
    for stand in stands:
        if metric == 'reviews':
            value = stand.total_reviews
        elif metric == 'rating':
            value = float(stand.average_rating)
        else:
            value = 0
        
        data.append({
            'id': stand.id,
            'code': stand.stand_code,
            'name': stand.stand_name,
            'value': value,
            'x': stand.floor_plan_x,
            'y': stand.floor_plan_y,
        })
    
    return JsonResponse({'stands': data})


@staff_member_required
def export_feedback_csv(request):
    """Export all feedback data to CSV"""
    import csv
    from django.http import HttpResponse
    from django.utils import timezone
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="exhibitor_feedback_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Booth Code', 'Booth Name', 'Visitor Name', 'Visitor Email', 
        'Visitor Phone', 'Country', 'City', 'Industry', 'Rating', 
        'Review Text', 'Submitted At', 'IP Address', 'Approved'
    ])
    
    feedbacks = VisitorFeedback.objects.select_related('stand').order_by('-submitted_at')
    
    for feedback in feedbacks:
        writer.writerow([
            feedback.id,
            feedback.stand.stand_code,
            feedback.stand.stand_name,
            feedback.visitor_name,
            feedback.visitor_email,
            feedback.visitor_phone,
            feedback.country,
            feedback.city,
            feedback.industry,
            feedback.rating,
            feedback.review_text,
            feedback.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
            feedback.ip_address or '',
            'Yes' if feedback.is_approved else 'No'
        ])
    
    return response

# Replace the recent_updates_api function in your views.py with this fixed version

from django.utils import timezone
from datetime import datetime, timedelta

@require_http_methods(["GET"])
def recent_updates_api(request):
    """
    Get recent feedback updates since a given timestamp
    Used for AJAX polling - completely safe, no dependencies
    """
    try:
        # Get timestamp from query parameter (milliseconds)
        since_timestamp = request.GET.get('since', 0)
        
        # Convert milliseconds to seconds and create datetime
        since_seconds = int(since_timestamp) / 1000
        since_datetime = datetime.fromtimestamp(since_seconds)
        
        # Make it timezone-aware (your settings use 'Africa/Nairobi')
        if timezone.is_naive(since_datetime):
            since_datetime = timezone.make_aware(since_datetime)
        
        print(f"🔍 Checking for feedbacks since: {since_datetime}")
        
        # Get new approved feedbacks since that time
        new_feedbacks = VisitorFeedback.objects.filter(
            submitted_at__gt=since_datetime,
            is_approved=True
        ).select_related('stand').order_by('submitted_at')[:20]
        
        print(f"📊 Found {new_feedbacks.count()} new feedbacks")
        
        # Prepare response data
        feedbacks_data = []
        for feedback in new_feedbacks:
            feedbacks_data.append({
                'id': feedback.id,
                'stand_id': feedback.stand.id,
                'stand_code': feedback.stand.stand_code,
                'stand_name': feedback.stand.stand_name,
                'visitor_name': feedback.visitor_first_name,
                'rating': feedback.rating,
                'review_text': feedback.review_text[:100],  # First 100 chars for toast
                'submitted_at': feedback.submitted_at.strftime('%b %d, %Y %H:%M'),
                'stand_stats': {
                    'total_reviews': feedback.stand.total_reviews,
                    'average_rating': float(feedback.stand.average_rating),
                }
            })
        
        return JsonResponse({
            'success': True,
            'new_feedbacks': feedbacks_data,
            'count': len(feedbacks_data),
            'server_time': int(timezone.now().timestamp() * 1000)
        })
        
    except Exception as e:
        # Log the actual error so we can see what's wrong
        print(f"❌ Error in recent_updates_api: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Return error but don't break the page
        return JsonResponse({
            'success': False,
            'new_feedbacks': [],
            'count': 0,
            'error': str(e)  # Include error for debugging
        })