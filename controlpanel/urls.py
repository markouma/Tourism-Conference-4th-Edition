from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = 'controlpanel'

urlpatterns = [
    path('login/', views.controlpanel_login, name='controlpanel_login'),   
    path('logout/', views.controlpanel_logout, name='controlpanel_logout'),
    path('logged-out/', views.logged_out, name='logged_out'),

    
    path('', views.dashboard_home, name='dashboard_home'),
    
    path('reports/', views.unified_reports_view, name='unified_reports'),
    path('reports/all-holders-csv/', views.download_all_holders_csv, name='all_holders_csv'),
    path('reports/login/', views.reports_login, name='reports_login'),
    path('reports/logout/', views.reports_logout, name='reports_logout'),
    
    path('events/', views.events_dashboard_view, name='event_list'),
    path('events/<int:event_id>/', views.event_detail_view, name='event_detail_view'),
    path('delete-ticket/<int:ticket_id>/', views.delete_ticket, name='delete_ticket'),

    path('keep-alive/', views.keep_alive, name='keep_alive'),
    
    path('booth-sales/', views.booth_sales_view, name='booth_sales'),
    path('export-booths-csv/', views.export_booth_sales_csv, name='export_booths_csv'),
    path('export-booths-pdf/', views.export_booth_sales_pdf, name='export_booths_pdf'),
    path('manage-users/', views.manage_users_view, name='manage_users'),
    path('payment-gateway-report/', views.payment_gateway_report_view, name='payment_gateway_report'),
    path('manage-users/', views.manage_users_view, name='manage_users'),
    path('export-users-csv/', views.export_users_csv, name='export_users_csv'),
    path('export-users-pdf/', views.export_users_pdf, name='export_users_pdf'),

    path('export-staff-csv/', views.export_staff_csv, name='export_staff_csv'),
    path('export-staff-pdf/', views.export_staff_pdf, name='export_staff_pdf'),

    path('reports/booth-visits/', views.booth_visits_report, name='booth_visits_report'),
    path('reports/booth-reviews/', views.booth_reviews_report, name='booth_reviews_report'),
    path('traffic-report/', views.traffic_report, name='traffic_report'),
    path('paid-reports/', views.paid_reports_view, name='paid_reports'),
    path('paid-reports/download-pdf/', views.download_paid_reports_pdf, name='download_paid_reports_pdf'),

    path('events/<int:event_id>/download-pdf/', views.download_event_detail_pdf, name='download_event_detail_pdf'),

     path('print-station/', views.print_station, name='print_station'),
    path('api/recent-scans/', views.get_recent_scans, name='get_recent_scans'),
    
path('persons/', views.all_persons_view, name='all_persons'),
    path('print-badge/<int:ticket_id>/', views.print_badge, name='print_badge'),
    path('tickets/', views.ticket_management_view, name='ticket_management'),
    path('tickets/create/', views.create_ticket_view, name='create_ticket'),
    
path('reports/all-holders-csv/', views.download_all_holders_csv, name='all_holders_csv'),

path('send-invoice/<str:holder_id>/', views.send_delegate_invoice, name='send_delegate_invoice'),
path('check-sent/<str:holder_id>/', views.check_invoice_sent, name='check_invoice_sent'),

# scan stats
path('scan-stats/', views.scan_stats_view, name='scan_stats'),

]