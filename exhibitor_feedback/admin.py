from django.contrib import admin
from django.utils.html import format_html
from .models import ExhibitorStand, VisitorFeedback, FeedbackAnalytics


@admin.register(ExhibitorStand)
class ExhibitorStandAdmin(admin.ModelAdmin):
    list_display = ['stand_code', 'stand_name', 'total_reviews', 'average_rating', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['stand_code', 'stand_name']
    ordering = ['stand_code']
    
    readonly_fields = ['created_at', 'total_reviews', 'average_rating']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('stand_code', 'stand_name', 'is_active')
        }),
        ('Floor Plan Position', {
            'fields': ('floor_plan_x', 'floor_plan_y', 'svg_path_id'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('total_reviews', 'average_rating', 'created_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(VisitorFeedback)
class VisitorFeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'stand', 'visitor_name', 'rating_display', 'country', 'industry', 'submitted_at', 'is_approved']
    list_filter = ['rating', 'is_approved', 'country', 'industry', 'submitted_at']
    search_fields = ['visitor_name', 'visitor_email', 'stand__stand_code', 'stand__stand_name', 'review_text']
    ordering = ['-submitted_at']
    
    readonly_fields = ['submitted_at', 'ip_address']
    
    fieldsets = (
        ('Stand Information', {
            'fields': ('stand', 'is_approved')
        }),
        ('Visitor Information', {
            'fields': ('visitor_name', 'visitor_email', 'visitor_phone', 'country', 'city', 'industry')
        }),
        ('Feedback', {
            'fields': ('rating', 'review_text')
        }),
        ('Metadata', {
            'fields': ('submitted_at', 'ip_address'),
            'classes': ('collapse',)
        }),
    )
    
    def rating_display(self, obj):
        stars = '⭐' * obj.rating
        return format_html('<span style="font-size: 1.2em;">{}</span>', stars)
    rating_display.short_description = 'Rating'
    
    actions = ['approve_feedbacks', 'unapprove_feedbacks']
    
    def approve_feedbacks(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f'{queryset.count()} feedback(s) approved.')
    approve_feedbacks.short_description = 'Approve selected feedbacks'
    
    def unapprove_feedbacks(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f'{queryset.count()} feedback(s) unapproved.')
    unapprove_feedbacks.short_description = 'Unapprove selected feedbacks'


@admin.register(FeedbackAnalytics)
class FeedbackAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['stand', 'total_reviews', 'average_rating', 'unique_countries', 'unique_cities', 'last_review_at']
    list_filter = ['last_review_at', 'updated_at']
    search_fields = ['stand__stand_code', 'stand__stand_name']
    ordering = ['-total_reviews']
    
    readonly_fields = [
        'stand', 'total_reviews', 'average_rating', 
        'rating_1_count', 'rating_2_count', 'rating_3_count', 'rating_4_count', 'rating_5_count',
        'unique_countries', 'unique_cities', 'last_review_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Stand', {
            'fields': ('stand',)
        }),
        ('Overview', {
            'fields': ('total_reviews', 'average_rating', 'last_review_at')
        }),
        ('Rating Distribution', {
            'fields': ('rating_5_count', 'rating_4_count', 'rating_3_count', 'rating_2_count', 'rating_1_count')
        }),
        ('Geographic Diversity', {
            'fields': ('unique_countries', 'unique_cities')
        }),
        ('Metadata', {
            'fields': ('updated_at',)
        }),
    )
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['recalculate_analytics']
    
    def recalculate_analytics(self, request, queryset):
        for analytics in queryset:
            analytics.recalculate()
        self.message_user(request, f'{queryset.count()} analytics recalculated.')
    recalculate_analytics.short_description = 'Recalculate selected analytics'