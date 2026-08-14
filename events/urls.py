from django.urls import path
from . import views   
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views
from .views import SpeakerListView, SpeakerDetailView, BlogListView, BlogDetailView

urlpatterns = [

    path('index/', views.homepage, name='home'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),
    path('checkout/', views.checkout_router, name='checkout_router'),
    path('checkout/regular/', views.regular_checkout, name='regular_checkout'),
    path('checkout/conference/', views.conference_checkout, name='conference_checkout'),
    path('add-to-cart/<int:event_id>/', views.add_to_cart, name='add_to_cart'),
    path('update_cart/<int:category_id>/', views.update_cart, name='update_cart'),
    path('remove_from_cart/<int:category_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('payment_callback/', views.payment_callback, name='payment_callback'),
    path('payment_success/', views.payment_success, name='payment_success'),   
    path('payment_failed/', views.payment_failed, name='payment_failed'),
    path('not_found/', views.not_found, name='not_found'),
    path('payment_complete/', TemplateView.as_view(template_name='events/payment_complete.html'), name='payment_complete'),
    path('download_ticket/<int:ticket_id>/', views.download_ticket, name='download_ticket'),
    path('signup/', views.signup, name='signup'),
    path('all_tickets/', views.all_tickets, name='all_tickets'),
    path('api/validate-ticket/', views.validate_ticket, name='validate_ticket'),  
    # path('login/', auth_views.LoginView.as_view(template_name='events/login.html'), name='login'), 
    path('login/', views.login_view, name='login'),

    path('logout/', views.logout_view, name='logout'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('delete-event/<int:event_id>/', views.delete_event, name='delete_event'),
    path('edit-event/<int:event_id>/', views.edit_event, name='edit_event'), 
    
    path('scanner/events/', views.scanner_event_list, name='scanner_event_list'),
    path('scanner/login/', views.scanner_login, name='scanner_login'),

    path('scan/<int:event_id>/', views.scan_ticket, name='scan_ticket'),


# new scanner paths
path('scanner/', views.scanner_event_list, name='scanner_event_list'),
    path('scanner/event/<int:event_id>/', views.scan_ticket, name='scan_ticket'),
    path('api/validate-ticket/', views.validate_ticket, name='validate_ticket'),

    # path('event/<int:event_id>/scan-instances/', views.scan_instances_view, name='scan_instances'),


    path('events/<int:event_id>/booths/', views.booths_list, name='booth_list'),
    path('booth/<int:booth_id>/checkout/', views.booth_checkout, name='booth_checkout'),

    # path('booth/order/<uuid:order_id>/pay/', views.start_pesapal_booth_payment, name='start_pesapal_booth_payment'),
    # path('pesapal/booth/callback/', views.pesapal_booth_callback, name='pesapal_booth_callback'),

    path('events/<int:event_id>/booths/checkout/', views.booth_checkout, name='booth_checkout'),




    path('', views.index, name='index'),
    path('conference/', views.conference, name='conference'),
    path('exhibitors/', views.exhibitors, name='exhibitors'),
    path('gallery/', views.gallery, name='gallery'),
    path('golf/', views.golf, name='golf'),
    path('stay/', views.stay, name='stay'),
    path('Forewords/', views.Forewords, name='Forewords'),


    path('api/daraja/callback/', views.daraja_callback, name='daraja_callback'),
    path('mpesa_callback/', views.daraja_callback, name='mpesa_callback'),
    path('payment_status/<uuid:order_id>/', views.payment_status_view, name='payment_status'),
    path('retry_stk/<uuid:order_id>/', views.retry_stk_push, name='retry_stk'),



# staff application
    # path('staff/apply/', views.staff_application_view, name='staff_application'),
    path('staff/approve/<int:app_id>/', views.approve_staff_application, name='approve_staff'),
    path('staff/reject/<int:pk>/', views.reject_staff, name='reject_staff'),

    path('staff_application/success/', views.staff_application_success, name='staff_application_success'),
    path('contact/submit/', views.contact_form_submit, name='contact_submit'),
    path('application-denied/', views.staff_application_denied, name='staff_application_denied'),


    path('staff/apply/<int:event_id>/', views.staff_application_view, name='staff_application'),

# paid application
path('paid/apply/<int:event_id>/', views.paid_application_view, name='paid_application'),
path('paid/approve/<int:app_id>/', views.approve_paid_application, name='approve_paid'),
path('paid/reject/<int:app_id>/', views.reject_paid_application, name='reject_paid'),
path('paid_application/success/', views.paid_application_success, name='paid_application_success'),
path('paid_application/denied/', views.paid_application_denied, name='paid_application_denied'),


    # Cart management
    path('clear_cart/', views.clear_cart_view, name='clear_cart'),

# fo dashboards
 path('dashboard/user/', views.user_dashboard, name='user_dashboard'),
  path('dashboard/exhibitor/', views.exhibitor_dashboard, name='exhibitor_dashboard'),

path('api/universal-scan/', views.universal_scan_api, name='universal_scan_api'),
    path('api/submit-booth-review/', views.submit_booth_review, name='submit_booth_review'),

path('dashboard/review/booth/<int:booth_id>/', views.leave_review, name='leave_review'),
    path('api/user_visits/', views.user_visits_api, name='user_visits_api'),

    path("payment_pending/", views.payment_pending, name="payment_pending"), 

 path('booth-application/<int:event_id>/', views.booth_application_view, name='booth_application'),
    path('booth-application/success/', views.booth_application_success, name='booth_application_success'),

      # Paid Booth Application URLs
    path('paid-booth-application/', 
         views.paid_booth_application_view, 
         name='paid_booth_application'),
    
    path('paid-booth-application/success/', 
         views.paid_booth_application_success, 
         name='paid_booth_application_success'),
    
    # Admin URLs (only accessible by staff)
    path('admin/paid-booth-dashboard/', 
         views.paid_booth_admin_dashboard, 
         name='paid_booth_admin_dashboard'),
    
    path('admin/paid-booth/approve/<int:application_id>/', 
         views.approve_paid_booth_application, 
         name='approve_paid_booth_application'),
    
    path('admin/paid-booth/reject/<int:application_id>/', 
         views.reject_paid_booth_application, 
         name='reject_paid_booth_application'),
         
# urls.py
path('events/<int:event_id>/booths-live/', views.booth_floor_live, name='booth_floor_live'),
path('api/booth-scan/', views.booth_scan_api, name='booth_scan_api'),
path('leave_review/<int:booth_id>/', views.leave_review, name='leave_review'),

# password reset
path('reset-password/', views.password_reset_request, name='password_reset_request'),
path('reset-password/verify/', views.password_reset_verify, name='password_reset_verify'),
path('reset-password/<str:token>/', views.password_reset_verify, name='password_reset_verify_token'),
path('api/verify-otp/', views.verify_otp_ajax, name='verify_otp_ajax'),

path('api/search-tickets/', views.search_tickets, name='search_tickets'),


path('api/checkpoint-stats/<int:event_id>/', views.checkpoint_statistics, name='checkpoint_statistics'),

path('review/booth/<uuid:token>/', views.public_booth_review, name='public_booth_review'),
    path('review/success/', views.review_success, name='review_success'),

    path('print-station/', views.print_station, name='print_station'),
    path('api/recent-scans/', views.get_recent_scans, name='get_recent_scans'),
path('download-ticket/<int:ticket_id>/', views.download_ticket, name='download_ticket'),  # Add this line

 
path('speakers/', SpeakerListView.as_view(), name='speakers'),
    path('speakers/<slug:slug>/', SpeakerDetailView.as_view(), name='speaker_detail'),
path('blog/', BlogListView.as_view(), name='blog'),
    path('blog/<slug:slug>/', BlogDetailView.as_view(), name='blog_detail'),



    ]




urlpatterns += [
    path("check_payment_status/<uuid:order_id>/", views.check_payment_status, name="check_payment_status"),
]




