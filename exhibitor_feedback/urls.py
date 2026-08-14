from django.urls import path
from . import views

# Use a unique URL prefix to avoid conflicts
app_name = 'exhibitor_feedback'

urlpatterns = [
    # Main interactive floor plan page
    path('exhibitor-feedback/', views.exhibitor_feedback_main, name='main'),
    
    # API endpoints
    path('exhibitor-feedback/api/submit/', views.submit_feedback_api, name='submit_api'),
    path('exhibitor-feedback/api/reviews/', views.public_reviews_api, name='reviews_api'),
    path('exhibitor-feedback/api/live-stream/', views.live_feedback_stream, name='live_stream'),
    path('exhibitor-feedback/api/analytics-data/', views.analytics_data_api, name='analytics_data_api'),
    path('exhibitor-feedback/api/export/', views.export_feedback_csv, name='export_csv'),
    
    # Admin analytics dashboard
    path('exhibitor-feedback/analytics-hub/', views.analytics_dashboard, name='analytics'),

    path('exhibitor-feedback/api/recent-updates/', views.recent_updates_api, name='recent_updates'),

]