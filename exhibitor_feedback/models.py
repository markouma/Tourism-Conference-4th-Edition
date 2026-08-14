from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg, Count
from django.utils import timezone


class ExhibitorStand(models.Model):
    """Individual exhibitor booth/stand"""
    stand_code = models.CharField(max_length=20, unique=True, help_text="e.g., A01, B12")
    stand_name = models.CharField(max_length=200, help_text="Exhibitor/Company name")
    
    # Floor plan positioning (for SVG/visual display)
    floor_plan_x = models.IntegerField(default=0, help_text="X coordinate on floor plan")
    floor_plan_y = models.IntegerField(default=0, help_text="Y coordinate on floor plan")
    
    # Optional: If using SVG paths
    svg_path_id = models.CharField(max_length=100, blank=True, help_text="ID of SVG element")
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['stand_code']
        verbose_name = "Exhibitor Stand"
        verbose_name_plural = "Exhibitor Stands"
    
    def __str__(self):
        return f"{self.stand_code} - {self.stand_name}"
    
    @property
    def total_reviews(self):
        """Cached property for total review count"""
        return self.visitor_feedbacks.filter(is_approved=True).count()
    
    @property
    def average_rating(self):
        """Cached property for average rating"""
        avg = self.visitor_feedbacks.filter(is_approved=True).aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0
    
    @property
    def latest_review(self):
        """Get most recent approved review"""
        return self.visitor_feedbacks.filter(is_approved=True).order_by('-submitted_at').first()


class VisitorFeedback(models.Model):
    """Visitor review and rating for a stand"""
    stand = models.ForeignKey(ExhibitorStand, on_delete=models.CASCADE, related_name='visitor_feedbacks')
    
    # Visitor information (name is public, rest is admin-only)
    visitor_name = models.CharField(max_length=150)
    visitor_email = models.EmailField(db_index=True)
    visitor_phone = models.CharField(max_length=20, blank=True)
    
    # Geographic data
    country = models.CharField(max_length=100, db_index=True)
    city = models.CharField(max_length=100)
    
    # Professional data
    industry = models.CharField(max_length=100, db_index=True)
    
    # Review content
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        db_index=True
    )
    review_text = models.TextField()
    
    # Metadata
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_approved = models.BooleanField(default=True, help_text="For moderation if needed")
    
    class Meta:
        ordering = ['-submitted_at']
        verbose_name = "Visitor Feedback"
        verbose_name_plural = "Visitor Feedbacks"
        indexes = [
            models.Index(fields=['stand', '-submitted_at']),
            models.Index(fields=['visitor_email', 'stand']),
        ]
    
    def __str__(self):
        return f"{self.visitor_name} - {self.stand.stand_code} ({self.rating}★)"
    
    @property
    def visitor_first_name(self):
        """Return only first name for public display"""
        return self.visitor_name.split()[0] if self.visitor_name else "Anonymous"


class FeedbackAnalytics(models.Model):
    """Pre-computed analytics for performance (updated via signals)"""
    stand = models.OneToOneField(ExhibitorStand, on_delete=models.CASCADE, related_name='analytics')
    
    # Aggregated data
    total_reviews = models.IntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    
    # Rating distribution
    rating_1_count = models.IntegerField(default=0)
    rating_2_count = models.IntegerField(default=0)
    rating_3_count = models.IntegerField(default=0)
    rating_4_count = models.IntegerField(default=0)
    rating_5_count = models.IntegerField(default=0)
    
    # Geographic diversity
    unique_countries = models.IntegerField(default=0)
    unique_cities = models.IntegerField(default=0)
    
    # Timestamps
    last_review_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Feedback Analytics"
        verbose_name_plural = "Feedback Analytics"
    
    def __str__(self):
        return f"Analytics for {self.stand.stand_code}"
    
    def recalculate(self):
        """Recalculate all analytics for this stand"""
        reviews = VisitorFeedback.objects.filter(stand=self.stand, is_approved=True)
        
        self.total_reviews = reviews.count()
        
        if self.total_reviews > 0:
            self.average_rating = reviews.aggregate(avg=Avg('rating'))['avg']
            
            # Rating distribution
            self.rating_1_count = reviews.filter(rating=1).count()
            self.rating_2_count = reviews.filter(rating=2).count()
            self.rating_3_count = reviews.filter(rating=3).count()
            self.rating_4_count = reviews.filter(rating=4).count()
            self.rating_5_count = reviews.filter(rating=5).count()
            
            # Geographic diversity
            self.unique_countries = reviews.values('country').distinct().count()
            self.unique_cities = reviews.values('city').distinct().count()
            
            # Last review timestamp
            last_review = reviews.order_by('-submitted_at').first()
            self.last_review_at = last_review.submitted_at if last_review else None
        else:
            self.average_rating = 0
            self.rating_1_count = 0
            self.rating_2_count = 0
            self.rating_3_count = 0
            self.rating_4_count = 0
            self.rating_5_count = 0
            self.unique_countries = 0
            self.unique_cities = 0
            self.last_review_at = None
        
        self.save()


# Signal to update analytics when feedback is created/updated
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=VisitorFeedback)
def update_analytics_on_save(sender, instance, created, **kwargs):
    """Update analytics when a new review is submitted"""
    analytics, _ = FeedbackAnalytics.objects.get_or_create(stand=instance.stand)
    analytics.recalculate()

@receiver(post_delete, sender=VisitorFeedback)
def update_analytics_on_delete(sender, instance, **kwargs):
    """Update analytics when a review is deleted"""
    try:
        analytics = FeedbackAnalytics.objects.get(stand=instance.stand)
        analytics.recalculate()
    except FeedbackAnalytics.DoesNotExist:
        pass