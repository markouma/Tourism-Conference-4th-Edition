from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Case, When, Value, CharField, F, ExpressionWrapper, DecimalField
from django.core.paginator import Paginator
from reportlab.pdfgen import canvas
from io import BytesIO
from reportlab.lib.pagesizes import letter
from collections import defaultdict
from weasyprint import HTML
import tempfile
import csv
from decimal import Decimal

from events.models import Event, Ticket, Order, StaffApplication, Booth, BoothReview, PaidApplication, ScanInstance, TicketCategory, TicketScanLog
from .models import SiteVisit, SentInvoice
from django.db.models import Q


def is_admin(user):
    return user.is_superuser or (user.is_staff and user.groups.filter(name='Admin').exists())


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def dashboard_home(request):
    return render(request, 'controlpanel/dashboard_home.html')


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def event_list(request):
    events = Event.objects.all().order_by('-date')
    return render(request, 'controlpanel/event_list.html', {'events': events})


def controlpanel_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None and (user.is_superuser or (user.is_staff and user.groups.filter(name='Admin').exists())):
            login(request, user)
            next_url = request.GET.get('next') or '/controlpanel/'
            return redirect(next_url)
        else:
            return render(request, 'controlpanel/login.html', {
                'error': 'Invalid credentials or not an admin'
            })

    return render(request, 'controlpanel/login.html')


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def delete_ticket(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, pk=ticket_id)
        event_id = ticket.category.event.id
        
        ticket.delete()
        
        messages.success(request, f'Ticket #{ticket.ticket_number} has been deleted successfully.')
        
        return redirect('controlpanel:event_detail_view', event_id=event_id)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def event_detail_view(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    tickets = Ticket.objects.filter(category__event=event).select_related('user', 'category', 'order').order_by('-created_at')

    tickets_per_category = (
        tickets
        .values('category__name', 'category__price')
        .annotate(
            total_sold=Count('id'),
            total_revenue=ExpressionWrapper(
                F('category__price') * Count('id'),
                output_field=DecimalField()
            )
        )
        .order_by('category__name')
    )

    tickets_per_country = []
    for ticket in tickets:
        country = None
        
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        elif ticket.order and ticket.order.country:
            country = ticket.order.country
        
        if country and country.lower() != 'none':
            found = False
            for item in tickets_per_country:
                if item['country'] == country:
                    item['count'] += 1
                    found = True
                    break
            if not found:
                tickets_per_country.append({'country': country, 'count': 1})
    
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)

    return render(request, 'controlpanel/event_detail.html', {
        'event': event,
        'tickets': tickets,
        'tickets_per_category': tickets_per_category,
        'tickets_per_country': tickets_per_country,
    })


def events_dashboard_view(request):
    events = Event.objects.all()

    event_data = []
    for event in events:
        tickets = Ticket.objects.filter(category__event=event)

        total_revenue = Decimal('0.00')
        for t in tickets:
            if t.category and t.category.price:
                total_revenue += t.category.price
        print(f"{event.name} → Tickets: {tickets.count()} | Revenue: {total_revenue}")

        event_data.append({
            'event': event,
            'tickets_sold': tickets.count(),
            'total_revenue': total_revenue,
        })

    return render(request, 'controlpanel/event_list.html', {'events': event_data})


def controlpanel_logout(request):
    logout(request)
    return redirect('controlpanel:logged_out')


def logged_out(request):
    return render(request, 'controlpanel/logged_out.html')


@csrf_exempt
@login_required
def keep_alive(request):
    if request.method == 'POST':
        request.session.modified = True
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'invalid request'}, status=400)


def export_booth_sales_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="booth_sales.csv"'

    writer = csv.writer(response)
    writer.writerow(["Booth", "Event", "Price (KES)", "Status", "Booked By", "Order ID", "Booked At"])

    for booth in Booth.objects.select_related('booked_by', 'order', 'event').all():
        writer.writerow([
            booth.name,
            booth.event.name,
            booth.price,
            "Booked" if booth.is_booked else "Available",
            booth.booked_by.email if booth.booked_by else "Anonymous",
            booth.order.id if booth.order else "—",
            booth.booked_at.strftime('%Y-%m-%d %H:%M') if booth.booked_at else "—",
        ])

    return response


def export_booth_sales_pdf(request):
    booths = Booth.objects.select_related('booked_by', 'order', 'event').all()

    total_sales = booths.filter(is_booked=True).aggregate(total=Sum('price'))['total'] or 0
    total_booked = booths.filter(is_booked=True).count()
    total_not_booked = booths.filter(is_booked=False).count()

    context = {
        'booths': booths,
        'now': timezone.localtime(timezone.now()),
        'company_logo_url': request.build_absolute_uri('/static/assets/img/logosi.png'),
        'total_sales': total_sales,
        'total_booked': total_booked,
        'total_not_booked': total_not_booked,
    }
    html_string = render_to_string('controlpanel/booth_sales_pdf.html', context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="booth_sales.pdf"'

    HTML(string=html_string).write_pdf(response)
    return response


def booth_sales_view(request):
    booths = Booth.objects.select_related('booked_by', 'order', 'event').all()
    events = Event.objects.all()

    total_sales = booths.filter(is_booked=True).aggregate(total=Sum('price'))['total'] or 0
    total_booked = booths.filter(is_booked=True).count()
    total_not_booked = booths.filter(is_booked=False).count()

    context = {
        'booths': booths,
        'events': events,
        'total_sales': total_sales,
        'total_booked': total_booked,
        'total_not_booked': total_not_booked,
        'now': timezone.localtime(timezone.now()),
    }
    return render(request, 'controlpanel/booth_sales.html', context)


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def manage_users_view(request):
    event_id = request.GET.get('event')
    user_type = request.GET.get('type')
    status = request.GET.get('status')

    events = Event.objects.all()

    orders = Order.objects.select_related('event', 'user')
    staff_apps = StaffApplication.objects.select_related('event')

    if event_id:
        orders = orders.filter(event__id=event_id)
        staff_apps = staff_apps.filter(event__id=event_id)

    if user_type == 'orders':
        staff_apps = staff_apps.none()
    elif user_type == 'staff':
        orders = orders.none()

    if status:
        if status == 'paid':
            orders = orders.filter(is_paid=True)
        elif status == 'unpaid':
            orders = orders.filter(is_paid=False)
        elif status in ['pending', 'approved', 'rejected']:
            staff_apps = staff_apps.filter(status=status)

    context = {
        'orders': orders,
        'staff_apps': staff_apps,
        'events': events,
        'selected_event': event_id,
        'selected_type': user_type,
        'selected_status': status,
    }

    return render(request, 'controlpanel/manage_users.html', context)


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def payment_gateway_report_view(request):
    orders = Order.objects.annotate(
        payment_method=Case(
            When(pesapal_tracking_id__isnull=False, pesapal_tracking_id__gt='', then=Value('Pesapal')),
            When(checkout_request_id__isnull=False, checkout_request_id__gt='', then=Value('M-Pesa')),
            default=Value('Unknown'),
            output_field=CharField(),
        )
    )

    data = (
        orders.values('payment_method')
        .annotate(
            total_sales=Count('id'),
            total_revenue=Sum('total_amount')
        )
        .order_by('payment_method')
    )

    return render(request, 'controlpanel/payment_gateway_report.html', {'data': data})


def export_users_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="all_users.csv"'

    writer = csv.writer(response)
    writer.writerow(['Type', 'Name', 'Email', 'Company', 'Designation/Role', 'Event', 'Payment/Status', 'Date'])

    orders = Order.objects.select_related('event').all()
    for o in orders:
        writer.writerow([
            'Order',
            o.user_name or (o.user.get_full_name() if o.user else 'N/A'),
            o.user_email,
            o.company or '—',
            o.designation or '—',
            o.event.name if o.event else '—',
            'Paid' if o.is_paid else 'Pending',
            o.created_at.strftime("%Y-%m-%d %H:%M")
        ])

    apps = StaffApplication.objects.select_related('event').all()
    for a in apps:
        writer.writerow([
            'StaffApp',
            a.full_name,
            a.email,
            a.company or '—',
            a.get_role_display(),
            a.event.name if a.event else '—',
            a.status.title(),
            a.submitted_at.strftime("%Y-%m-%d %H:%M")
        ])

    return response


def export_users_pdf(request):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="all_users.pdf"'

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "All Users: Orders + Tag Applicants")
    y -= 30

    p.setFont("Helvetica", 10)

    orders = Order.objects.select_related('event').all()
    for o in orders:
        line = f"[Order] {o.user_name or (o.user.get_full_name() if o.user else 'N/A')} | {o.user_email} | {o.company or '—'} | {o.designation or '—'} | {o.event.name if o.event else '—'} | {'Paid' if o.is_paid else 'Pending'} | {o.created_at.strftime('%Y-%m-%d %H:%M')}"
        p.drawString(40, y, line)
        y -= 14
        if y < 40:
            p.showPage()
            y = height - 40

    apps = StaffApplication.objects.select_related('event').all()
    for a in apps:
        line = f"[Staff] {a.full_name} | {a.email} | {a.company or '—'} | {a.get_role_display()} | {a.event.name if a.event else '—'} | {a.status.title()} | {a.submitted_at.strftime('%Y-%m-%d %H:%M')}"
        p.drawString(40, y, line)
        y -= 14
        if y < 40:
            p.showPage()
            y = height - 40

    p.save()
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response


def export_staff_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="tag_applicants.csv"'

    writer = csv.writer(response)
    writer.writerow(['Name', 'Email', 'Company', 'Designation', 'Role', 'Event', 'Status', 'Submitted At'])

    for a in StaffApplication.objects.select_related('event').all():
        writer.writerow([
            a.full_name,
            a.email,
            a.company or '—',
            a.designation or '—',
            a.get_role_display(),
            a.event.name if a.event else '—',
            a.status.title(),
            a.submitted_at.strftime("%Y-%m-%d %H:%M")
        ])
    
    return response


def export_staff_pdf(request):
    staff_apps = StaffApplication.objects.select_related('event').all()

    html_string = render_to_string('controlpanel/staff_pdf.html', {
        'staff_apps': staff_apps
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="tag_applicants.pdf"'

    HTML(string=html_string).write_pdf(response)
    return response


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def booth_visits_report(request):
    booths = Booth.objects.all()
    
    visits_by_booth = {}
    for booth in booths:
        reviews = BoothReview.objects.filter(booth=booth)
        visits_by_booth[booth] = reviews
        booth.visit_count = reviews.count()
    
    max_visits = max((booth.visit_count for booth in booths), default=0)
    
    return render(request, 'controlpanel/booth_visits_report.html', {
        'visits_by_booth': visits_by_booth,
        'booths': booths,
        'max_visits': max_visits,
    })


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def booth_reviews_report(request):
    reviews = BoothReview.objects.select_related('booth', 'reviewer').order_by('-created_at')
    return render(request, 'controlpanel/booth_reviews_report.html', {'reviews': reviews})


def traffic_report(request):
    visits = SiteVisit.objects.order_by('-timestamp')

    ip_groups = {}
    for v in visits:
        if v.ip_address not in ip_groups:
            ip_groups[v.ip_address] = {
                'country': v.country,
                'city': v.city,
                'user_agent': v.user_agent,
                'visits': []
            }
        ip_groups[v.ip_address]['visits'].append(v)

    total_visits = visits.count()
    total_users = len(ip_groups.keys())
    visits_per_country = SiteVisit.objects.values('country').annotate(count=Count('id')).order_by('-count')
    visits_per_city = SiteVisit.objects.values('city').annotate(count=Count('id')).order_by('-count')

    context = {
        'ip_groups': ip_groups,
        'total_visits': total_visits,
        'total_users': total_users,
        'visits_per_country': visits_per_country,
        'visits_per_city': visits_per_city,
    }
    return render(request, 'controlpanel/traffic_report.html', context)


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def paid_reports_view(request):
    if request.method == 'POST':
        updated_count = 0
        
        for key, value in request.POST.items():
            if key.startswith('amount_'):
                app_id = key.split('_')[1]
                try:
                    app = PaidApplication.objects.get(id=app_id)
                    
                    amount_value = request.POST.get(f'amount_{app_id}', '').strip()
                    if amount_value:
                        app.amount = float(amount_value)
                    else:
                        app.amount = None
                    
                    mpesa_msg = request.POST.get(f'mpesa_message_{app_id}', '').strip()
                    app.mpesa_message = mpesa_msg if mpesa_msg else None
                    
                    app.save()
                    updated_count += 1
                except (PaidApplication.DoesNotExist, ValueError):
                    continue
        
        messages.success(request, f'Successfully updated {updated_count} records!')
        return redirect('controlpanel:paid_reports')
    
    sort_by = request.GET.get('sort', '-approved')
    
    tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application')
    
    valid_sort_fields = {
        'name': 'paid_application__full_name',
        '-name': '-paid_application__full_name',
        'email': 'paid_application__email',
        '-email': '-paid_application__email',
        'phone': 'paid_application__phone',
        '-phone': '-paid_application__phone',
        'country': 'paid_application__country',
        '-country': '-paid_application__country',
        'status': 'is_used',
        '-status': '-is_used',
        'approved': 'paid_application__submitted_at',
        '-approved': '-paid_application__submitted_at',
        'amount': 'paid_application__amount',
        '-amount': '-paid_application__amount',
        'created_at': 'created_at',
        '-created_at': '-created_at',
        'mpesa_message': 'paid_application__mpesa_message',
        '-mpesa_message': '-paid_application__mpesa_message',
    }
    
    if sort_by in valid_sort_fields:
        tickets = tickets.order_by(valid_sort_fields[sort_by])
    else:
        tickets = tickets.order_by('-paid_application__submitted_at')
    
    seen_combinations = set()
    unique_tickets = []
    
    for ticket in tickets:
        app = ticket.paid_application
        
        unique_key = (
            app.full_name.strip().lower() if app.full_name else '',
            app.email.strip().lower() if app.email else '',
            app.phone.strip() if app.phone else ''
        )
        
        if unique_key not in seen_combinations:
            seen_combinations.add(unique_key)
            unique_tickets.append(ticket)
    
    unique_app_ids = [t.paid_application.id for t in unique_tickets]
    total_amount = PaidApplication.objects.filter(
        id__in=unique_app_ids,
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    tickets_per_country = []
    for ticket in unique_tickets:
        app = ticket.paid_application
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        found = False
        for item in tickets_per_country:
            if item['country'] == country:
                item['count'] += 1
                found = True
                break
        if not found:
            tickets_per_country.append({'country': country, 'count': 1})
    
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    report_data = []
    for ticket in unique_tickets:
        app = ticket.paid_application
        
        status_text = "Used" if ticket.is_used else "Not Used"
        approved_date = app.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if app.submitted_at else None
        
        report_data.append({
            'app': app,
            'ticket': ticket,
            'status_text': status_text,
            'approved_date': approved_date,
        })
    
    context = {
        'report_data': report_data,
        'total_amount': total_amount,
        'total_records': len(report_data),
        'current_sort': sort_by,
        'tickets_per_country': tickets_per_country,
    }
    
    return render(request, 'controlpanel/paid_reports.html', context)


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def download_paid_reports_pdf(request):
    tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application').order_by('-created_at')
    
    total_amount = PaidApplication.objects.filter(
        status='approved',
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    tickets_per_country = []
    for ticket in tickets:
        app = ticket.paid_application
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        found = False
        for item in tickets_per_country:
            if item['country'] == country:
                item['count'] += 1
                found = True
                break
        if not found:
            tickets_per_country.append({'country': country, 'count': 1})
    
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    report_data = []
    for ticket in tickets:
        app = ticket.paid_application
        status_text = "Used" if ticket.is_used else "Not Used"
        scan_time = ticket.first_scanned_at.strftime('%Y-%m-%d %H:%M:%S') if ticket.first_scanned_at else 'N/A'
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        report_data.append({
            'name': app.full_name,
            'email': app.email,
            'phone': app.phone or 'N/A',
            'country': country,
            'ticket_number': ticket.ticket_number or str(ticket.ticket_id)[:8],
            'status': status_text,
            'scan_time': scan_time,
            'amount': f"{app.amount:.2f}" if app.amount else 'N/A',
            'mpesa_message': app.mpesa_message or 'N/A',
        })
    
    context = {
        'report_data': report_data,
        'total_amount': total_amount,
        'total_records': len(report_data),
        'generated_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'company_logo_url': request.build_absolute_uri('/static/assets/img/logosi.png'),
        'tickets_per_country': tickets_per_country,
    }
    
    html_string = render_to_string('controlpanel/paid_reports_pdf.html', context)
    
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="paid_applications_report.pdf"'
    
    return response


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def download_event_detail_pdf(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    tickets = Ticket.objects.filter(category__event=event).select_related('user', 'category', 'order').order_by('-created_at')

    tickets_per_category = (
        tickets
        .values('category__name', 'category__price')
        .annotate(
            total_sold=Count('id'),
            total_revenue=ExpressionWrapper(
                F('category__price') * Count('id'),
                output_field=DecimalField()
            )
        )
        .order_by('category__name')
    )
    
    grand_total = sum(cat['total_revenue'] for cat in tickets_per_category)
    
    tickets_per_country = []
    for ticket in tickets:
        country = None
        
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        elif ticket.order and ticket.order.country:
            country = ticket.order.country
        
        if country and country.lower() != 'none':
            found = False
            for item in tickets_per_country:
                if item['country'] == country:
                    item['count'] += 1
                    found = True
                    break
            if not found:
                tickets_per_country.append({'country': country, 'count': 1})
    
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    ticket_data = []
    for ticket in tickets:
        country = 'N/A'
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        elif ticket.order and ticket.order.country:
            country = ticket.order.country
            
        city = 'N/A'
        if ticket.user and hasattr(ticket.user, 'city') and ticket.user.city:
            city = ticket.user.city
        elif hasattr(ticket, 'city') and ticket.city:
            city = ticket.city
        elif ticket.order and ticket.order.city:
            city = ticket.order.city
        
        ticket_data.append({
            'ticket_number': ticket.ticket_number or 'N/A',
            'buyer': ticket.user.username if ticket.user else (ticket.guest_name or 'Unknown'),
            'category': ticket.category.name if ticket.category else 'N/A',
            'price': f"{ticket.category.price:.2f}" if ticket.category and ticket.category.price else '0.00',
            'purchase_date': ticket.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'Used' if ticket.is_used else 'Not Used',
            'country': country,
            'city': city,
        })
    
    context = {
        'event': event,
        'tickets': ticket_data,
        'tickets_per_category': list(tickets_per_category),
        'tickets_per_country': tickets_per_country,
        'grand_total': grand_total,
        'total_tickets': tickets.count(),
        'generated_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'company_logo_url': request.build_absolute_uri('/static/assets/img/logosi.png'),
    }
    
    html_string = render_to_string('controlpanel/event_detail_pdf.html', context)
    
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="event_ticket_report_{event.name.replace(" ", "_")}.pdf"'
    
    return response


def reports_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if username == 'samoraa' and password == 'samoraa':
            request.session['reports_authenticated'] = True
            return redirect('controlpanel:unified_reports')
        else:
            messages.error(request, 'Invalid credentials. Please try again.')
    
    return render(request, 'controlpanel/reports_login.html')


def reports_logout(request):
    if 'reports_authenticated' in request.session:
        del request.session['reports_authenticated']
    return redirect('controlpanel:reports_login')


# controlpanel/views.py
import csv
import logging
from collections import defaultdict
from decimal import Decimal
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Count, Sum, F, ExpressionWrapper, DecimalField
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET

# === MODELS ===

logger = logging.getLogger(__name__)

# ==================== MAIN REPORTS VIEW ====================
# views.py
import os
from decimal import Decimal
from collections import defaultdict
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.core.files.base import ContentFile
from django.utils import timezone
from weasyprint import HTML

def unified_reports_view(request):
    if not request.session.get('reports_authenticated'):
        return redirect('controlpanel:reports_login')

    EXCLUDED_CATS = ["Booth Representative", "Paid Booth Representative"]
    all_event_data = []

    # === 1. AUTO-PAID TICKETS ===
    for event in Event.objects.all():
        tickets = Ticket.objects.filter(
            category__event=event
        ).exclude(category__name__in=EXCLUDED_CATS).select_related('user', 'category', 'order').order_by('-created_at')

        tickets_per_category = (
            tickets.values('category__name', 'category__price')
            .annotate(
                total_sold=Count('id'),
                total_revenue=ExpressionWrapper(F('category__price') * Count('id'), output_field=DecimalField())
            )
            .order_by('category__name')
        )

        event_country_counts = defaultdict(int)
        for ticket in tickets:
            country = 'N/A'
            if ticket.user and getattr(ticket.user, 'country', None):
                country = ticket.user.country.strip().title()
            elif getattr(ticket, 'country', None):
                country = ticket.country.strip().title()
            elif ticket.order and getattr(ticket.order, 'country', None):
                country = ticket.order.country.strip().title()
            if country.lower() != 'none':
                event_country_counts[country] += 1

        event_countries = [{'country': c, 'count': count} for c, count in event_country_counts.items()]
        event_countries.sort(key=lambda x: x['count'], reverse=True)

        ticket_list = []
        for ticket in tickets:
            name = ticket.guest_name or (ticket.user.get_full_name() if ticket.user else 'Unknown')
            email = ticket.guest_email or (ticket.user.email if ticket.user else '')
            phone = ticket.guest_phone or (getattr(ticket.user, 'phone', '') if ticket.user else '')
            if ticket.order:
                if not email:
                    email = getattr(ticket.order, 'billing_email', None) or getattr(ticket.order, 'email', None) or ''
                if not phone:
                    phone = getattr(ticket.order, 'billing_phone', None) or getattr(ticket.order, 'phone', None) or ''

            country = 'N/A'
            if ticket.user and getattr(ticket.user, 'country', None):
                country = ticket.user.country.strip().title()
            elif getattr(ticket, 'country', None):
                country = ticket.country.strip().title()
            elif ticket.order and getattr(ticket.order, 'country', None):
                country = ticket.order.country.strip().title()

            city = 'N/A'
            if ticket.user and getattr(ticket.user, 'city', None):
                city = ticket.user.city
            elif getattr(ticket, 'city', None):
                city = ticket.city
            elif ticket.order and getattr(ticket.order, 'city', None):
                city = ticket.order.city

            ticket_list.append({
                'ticket_number': ticket.ticket_number,
                'buyer': name,
                'country': country,
                'city': city,
                'category': ticket.category.name if ticket.category else 'N/A',
                'price': ticket.category.price if ticket.category else 0,
                'purchase_date': ticket.created_at,
                'is_used': ticket.is_used,
                'ticket_id': ticket.id,
                'email': email.strip(),
                'phone': phone.strip(),
                'company': ticket.company_name.strip() if ticket.company_name else '—',  # AUTO COMPANY
            })

        event_total = sum(cat['total_revenue'] for cat in tickets_per_category)
        all_event_data.append({
            'event': event,
            'tickets': ticket_list,
            'tickets_per_category': list(tickets_per_category),
            'event_countries': event_countries,
            'event_total': event_total,
            'ticket_count': tickets.count(),
        })

    total_ticket_revenue = sum(evt['event_total'] for evt in all_event_data)
    total_tickets_sold = sum(evt['ticket_count'] for evt in all_event_data)

    # === 2. BOOTHS ===
    booths = Booth.objects.select_related('booked_by', 'order').order_by('name')
    booth_list = []
    for booth in booths:
        booked_by_display = '—'
        if booth.booked_by:
            booked_by_display = booth.booked_by.get_full_name() or booth.booked_by.username
        elif booth.order and booth.order.user_name:
            booked_by_display = booth.order.user_name
        booth_list.append({
            'name': booth.name,
            'price': booth.price,
            'is_booked': booth.is_booked,
            'booked_by': booked_by_display,
            'order_id': booth.order.id if booth.order else '—',
            'booked_at': booth.booked_at,
        })

    total_booth_revenue = booths.filter(is_booked=True).aggregate(total=Sum('price'))['total'] or 0
    total_booths_booked = booths.filter(is_booked=True).count()
    total_booths_available = booths.filter(is_booked=False).count()
    total_booth_revenue_with_vat = (Decimal(str(total_booth_revenue)) * Decimal('1.16')) - Decimal('16000')

    # === 3. MANUALLY APPROVED ===
    paid_tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application').order_by('-created_at')

    seen_combinations = set()
    unique_paid_tickets = []
    for ticket in paid_tickets:
        app = ticket.paid_application
        key = (app.full_name.strip().lower() if app.full_name else '',
               app.email.strip().lower() if app.email else '',
               app.phone.strip() if app.phone else '')
        if key not in seen_combinations:
            seen_combinations.add(key)
            unique_paid_tickets.append(ticket)

    paid_country_counts = defaultdict(int)
    for ticket in unique_paid_tickets:
        app = ticket.paid_application
        country = app.country.strip().title() if getattr(app, 'country', None) else 'Unknown'
        paid_country_counts[country] += 1

    paid_per_country = [{'country': c, 'count': count} for c, count in paid_country_counts.items()]
    paid_per_country.sort(key=lambda x: x['count'], reverse=True)

    paid_app_list = []
    for ticket in unique_paid_tickets:
        app = ticket.paid_application
        country = app.country.strip().title() if getattr(app, 'country', None) else 'Unknown'
        paid_app_list.append({
            'full_name': app.full_name or 'Unknown',
            'email': app.email or '',
            'phone': app.phone or 'N/A',
            'country': country,
            'ticket_number': ticket.ticket_number or str(ticket.id)[:8],
            'is_used': ticket.is_used,
            'status_text': 'Used' if ticket.is_used else 'Not Used',
            'approved_date': app.submitted_at,
            'amount': app.amount or 0,
            'mpesa_message': app.mpesa_message or 'N/A',
            'ticket': ticket,  # Needed to access paid_application later
        })

    total_paid_amount = PaidApplication.objects.filter(
        id__in=[t.paid_application.id for t in unique_paid_tickets],
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0

    # === 4. ALL TICKET HOLDERS - CLEAN & FINAL ===
    # === 4. ALL TICKET HOLDERS - CLEAN & FINAL ===
    auto_delegates = []
    manual_delegates = []
    holder_counter = 1

    # AUTO TICKETS
    for evt in all_event_data:
        for t in evt['tickets']:
            auto_delegates.append({
                'holder_id': f"A{holder_counter:06d}",
                'invoice_number': f"DEL-{holder_counter:06d}",
                'name': t['buyer'],
                'email': t['email'],
                'phone': t['phone'],
                'country': t['country'],
                'source': 'auto',
                'date': t['purchase_date'],
                'amount': t['price'],
                'category': t['category'],
                'company': t['company'],
            })
            holder_counter += 1

    # MANUAL TICKETS
    for app in paid_app_list:
        company = '—'
        paid_app_obj = app['ticket'].paid_application
        if paid_app_obj and getattr(paid_app_obj, 'company', None):
            company = paid_app_obj.company.strip()

        manual_delegates.append({
            'holder_id': f"M{holder_counter:06d}",
            'invoice_number': f"MAN-{holder_counter:06d}",
            'name': app['full_name'],
            'email': app['email'],
            'phone': app['phone'],
            'country': app['country'],
            'source': 'manual',
            'date': app['approved_date'],
            'amount': app['amount'],
            'category': 'Manual Approval',
            'company': company if company and company.strip() else '—',
        })
        holder_counter += 1

    # DEDUPE
    seen = set()
    all_ticket_holders = []
    for d in auto_delegates + manual_delegates:
        key = (d['name'].strip().lower(), d['email'].strip().lower(), d['phone'])
        if key not in seen:
            seen.add(key)
            all_ticket_holders.append(d)

    # Session-safe
    session_holders = [
        {
            **h,
            'date': h['date'].strftime('%Y-%m-%d %H:%M:%S') if h['date'] else None,
            'amount': float(h['amount']) if h['amount'] else 0
        }
        for h in all_ticket_holders
    ]
    request.session['all_ticket_holders'] = session_holders

    # === TOTAL SCANNABLE TICKETS: ALL TICKET OBJECTS IN DB ===
    total_scannable_tickets = Ticket.objects.count()

    # Keep grand_total_items for revenue card only
    grand_total_items = total_tickets_sold + total_booths_booked + len(paid_app_list)
    
    delegated_country_counts = defaultdict(int)
    delegated_total_count = 0
    for evt in all_event_data:
        for cd in evt['event_countries']:
            delegated_country_counts[cd['country']] += cd['count']
            delegated_total_count += cd['count']
    for cd in paid_per_country:
        delegated_country_counts[cd['country']] += cd['count']
        delegated_total_count += cd['count']
    delegated_country_counts = dict(sorted(delegated_country_counts.items(), key=lambda x: x[0].lower()))
    
    event_id = request.GET.get('event')
    scan_instances = ScanInstance.objects.filter(event_id=event_id) if event_id else ScanInstance.objects.all()

    checkpoint_stats = []
    for instance in scan_instances:
        scanned = Ticket.objects.filter(scan_logs__scan_instance=instance).distinct().count()
        checkpoint_stats.append({
            'id': instance.id,
            'name': instance.name,
            'event': instance.event.name if instance.event else 'All Events',
            'scanned': scanned,
            'remaining': total_scannable_tickets - scanned,
            'total': total_scannable_tickets,  # ← Now correct
            'sort_key': get_sort_key(instance.name),
        })
    checkpoint_stats.sort(key=lambda x: x['name'])

    context = {
        'all_event_data': all_event_data,
        'total_ticket_revenue': total_ticket_revenue,
        'total_tickets_sold': total_tickets_sold,
        'booth_list': booth_list,
        'total_booth_revenue': total_booth_revenue,
        'total_booths_booked': total_booths_booked,
        'total_booth_revenue_with_vat': total_booth_revenue_with_vat,
        'total_booths_available': total_booths_available,
        'total_booths': booths.count(),
        'paid_app_list': paid_app_list,
        'total_paid_apps': len(paid_app_list),
        'total_paid_amount': total_paid_amount,
        'paid_per_country': paid_per_country,
        'grand_total_revenue': total_ticket_revenue + total_booth_revenue + total_paid_amount,
        'grand_total_revenue_with_vat': total_ticket_revenue + total_booth_revenue_with_vat + total_paid_amount,
        'grand_total_tickets': grand_total_items,  # For revenue card
        'total_scannable_tickets': total_scannable_tickets,  # For checkpoints
        'checkpoint_stats': checkpoint_stats,
        'delegated_country_counts': delegated_country_counts,
        'delegated_total_count': delegated_total_count,
        'all_ticket_holders': all_ticket_holders,
    }

    return render(request, 'controlpanel/unified_reports.html', context)


from datetime import datetime
# === SEND INVOICE VIEW ===
@csrf_exempt
def send_delegate_invoice(request, holder_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    holders = request.session.get('all_ticket_holders', [])
    holder = next((h for h in holders if h['holder_id'] == holder_id), None)
    if not holder or not holder.get('email') or holder['email'] in ['', '—']:
        return JsonResponse({'error': 'No email'}, status=400)

    # === COPY FOR TEMPLATE ===
    context_holder = holder.copy()
    if context_holder.get('date'):
        try:
            context_holder['date_obj'] = datetime.strptime(context_holder['date'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            context_holder['date_obj'] = None
    else:
        context_holder['date_obj'] = None

    # === CHECK IF ALREADY SENT ===
    already_sent = SentInvoice.objects.filter(holder_id=holder_id).exists()

    # === GENERATE PDF (ONLY IF NOT SENT OR RESEND) ===
    if not already_sent:
        html_string = render_to_string('controlpanel/invoice_delegate.html', {'h': context_holder})
        pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()

        # Save new record
        sent = SentInvoice.objects.create(
            holder_id=holder['holder_id'],
            invoice_number=holder['invoice_number'],
            name=holder['name'],
            email=holder['email'],
            amount=holder['amount'],
        )
        sent.pdf_file.save(f"{holder['invoice_number']}.pdf", ContentFile(pdf_file))
        sent.save()
    else:
        # Resend: fetch existing PDF
        sent = SentInvoice.objects.filter(holder_id=holder_id).first()
        pdf_file = sent.pdf_file.read() if sent.pdf_file else None

    # === SEND EMAIL ===
    email = EmailMessage(
        subject=f"Invoice - {holder['name']}",
        body=f"Dear {holder['name']},\n\nAttached is your invoice for The 4th UG-KE Coast Tourism Conference.\n\nThank you!",
        from_email="accounts@buzzafrique.co.ke",
        to=[holder['email']],
        cc=["accounts@buzzafrique.co.ke"],
        bcc=["coasttourismconference@gmail.com"]
    )
    if pdf_file:
        email.attach(f"Invoice_{holder['invoice_number']}_4th_UG_KE_Coast_Tourism_Conference.pdf", pdf_file, 'application/pdf')
    email.send()

    return JsonResponse({
        'success': True,
        'already_sent': already_sent
    })



@require_GET
def download_all_holders_csv(request):
    if not request.session.get('reports_authenticated'):
        return HttpResponse(status=403)

    holders = request.session.get('all_ticket_holders', [])
    if not holders:
        return HttpResponse("No data", status=400)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="all_ticket_holders.csv"'

    writer = csv.writer(response)
    
    # Header with Company
    writer.writerow(['#', 'Name', 'Company', 'Country', 'Email', 'Phone', 'Date', 'Amount (KES)', 'Holder ID', 'Source'])

    for idx, h in enumerate(holders, start=1):
        # Safely format date — works whether it's string or datetime
        date_str = '—'
        if h.get('date'):
            if isinstance(h['date'], str):
                # Already a string from session
                date_str = h['date']
            else:
                # It's a datetime object
                date_str = h['date'].strftime('%b %d, %Y %H:%M')

        writer.writerow([
            idx,
            h['name'],
            h.get('company', '') or '—',
            h['country'],
            h['email'] or '',
            h['phone'] or '',
            date_str,
            f"{float(h['amount']):,.2f}" if h['amount'] else '0.00',
            h['holder_id'],
            h.get('source', '').title(),
        ])

    return response


def all_persons_view(request):
    """
    Unified view for listing all persons from Delegates (Auto), Delegates (Manual), and Booths.
    Requires simple session authentication.
    """
    # Check if user is authenticated for reports
    if not request.session.get('reports_authenticated'):
        return redirect('controlpanel:reports_login')

    # ==================== EVENT TICKETS DATA (DELEGATES AUTO) ====================
    events = Event.objects.all()
    all_event_data = []

    for event in events:
        tickets = Ticket.objects.filter(
            category__event=event
        ).select_related('user', 'category', 'order').order_by('-created_at')

        # Prepare ticket data for table - NORMALIZED
        ticket_list = []
        for ticket in tickets:
            # Get buyer
            buyer = 'Unknown'
            if ticket.user:
                buyer = ticket.user.username
            elif ticket.guest_name:
                buyer = ticket.guest_name

            # Get country
            country = 'N/A'
            if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
                country = ticket.user.country.strip().title()
            elif hasattr(ticket, 'country') and ticket.country:
                country = ticket.country.strip().title()
            elif ticket.order and hasattr(ticket.order, 'country') and ticket.order.country:
                country = ticket.order.country.strip().title()

            # Get city
            city = 'N/A'
            if ticket.user and hasattr(ticket.user, 'city') and ticket.user.city:
                city = ticket.user.city.strip().title()
            elif hasattr(ticket, 'city') and ticket.city:
                city = ticket.city.strip().title()
            elif ticket.order and hasattr(ticket.order, 'city') and ticket.order.city:
                city = ticket.order.city.strip().title()

            # Get email
            email = 'N/A'
            if ticket.user and hasattr(ticket.user, 'email') and ticket.user.email:
                email = ticket.user.email.strip()
            elif ticket.order and hasattr(ticket.order, 'email') and ticket.order.email:
                email = ticket.order.email.strip()

            phone = 'N/A'
            if ticket.user and hasattr(ticket.user, 'phone') and ticket.user.phone:
                phone = ticket.user.phone.strip()
            elif ticket.order and hasattr(ticket.order, 'phone') and ticket.order.phone:
                phone = ticket.order.phone.strip()

            ticket_list.append({
                'ticket_number': ticket.ticket_number,
                'buyer': buyer,
                'email': ticket.guest_email,
                'phone': ticket.guest_phone,
                'country': country,
                'city': city,
                'category': ticket.category.name if ticket.category else 'N/A',
                'price': ticket.category.price if ticket.category else 0,
                'purchase_date': ticket.created_at,
                'is_used': ticket.is_used,
            })

        all_event_data.append({
            'event': event,
            'tickets': ticket_list,
        })

    # ==================== BOOTH SALES DATA ====================
    booths = Booth.objects.select_related('booked_by', 'order').order_by('name')

    booth_list = []
    for booth in booths:
        booked_by_display = '—'
        if booth.booked_by:
            booked_by_display = booth.booked_by.get_full_name() or booth.booked_by.username
        elif booth.order and booth.order.user_name:
            booked_by_display = booth.order.user_name

        booth_list.append({
            'name': booth.name,
            'price': booth.price,
            'is_booked': booth.is_booked,
            'booked_by': booked_by_display,
            'order_id': booth.order.id if booth.order else '—',
            'booked_at': booth.booked_at,
        })

    # ==================== PAID APPLICATIONS DATA (DELEGATES MANUAL) ====================
    paid_tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application').order_by('-created_at')

    seen_combinations = set()
    unique_paid_tickets = []

    for ticket in paid_tickets:
        app = ticket.paid_application
        unique_key = (
            app.full_name.strip().lower() if app.full_name else '',
            app.email.strip().lower() if app.email else '',
            app.phone.strip() if app.phone else ''
        )

        if unique_key not in seen_combinations:
            seen_combinations.add(unique_key)
            unique_paid_tickets.append(ticket)

    paid_app_list = []
    for ticket in unique_paid_tickets:
        app = ticket.paid_application
        country = app.country.strip().title() if hasattr(app, 'country') and app.country else 'Unknown'
        paid_app_list.append({
            'full_name': app.full_name,
            'email': app.email or ticket.guest_email,
            'phone': app.phone or 'N/A',
            'country': country,
            'ticket_number': ticket.ticket_number or str(ticket.ticket_id)[:8],
            'is_used': ticket.is_used,
            'status_text': 'Used' if ticket.is_used else 'Not Used',
            'approved_date': app.submitted_at,
            'amount': app.amount or 0,
            'mpesa_message': app.mpesa_message or 'N/A',
        })

    # ==================== CONTEXT ====================
    context = {
        'event_data': {'tickets': [ticket for event in all_event_data for ticket in event['tickets']]},
        'paid_app_list': paid_app_list,
        'booth_list': booth_list,
    }

    return render(request, 'controlpanel/all_persons.html', context)

def get_recent_scans(request):
    try:
        print_instance = ScanInstance.objects.get(name='Print', is_active=True)
        
        recent_scans = TicketScanLog.objects.filter(
            scan_instance=print_instance
        ).select_related(
            'ticket__user',
            'ticket__category',
            'scanned_by'
        ).order_by('-scanned_at')
        
        scans_data = []
        for scan_log in recent_scans:
            ticket = scan_log.ticket
            
            holder_name = ticket.user.get_full_name() if ticket.user else ticket.guest_name or "Guest"
            holder_email = ticket.user.email if ticket.user else ticket.guest_email or "N/A"
            holder_phone = getattr(ticket.user, 'phone', None) if ticket.user else ticket.guest_phone or "N/A"
            
            scans_data.append({
                'id': scan_log.id,
                'ticket_id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'holder_name': holder_name,
                'holder_email': holder_email,
                'holder_phone': holder_phone,
                'scanned_at': scan_log.scanned_at.strftime("%Y-%m-%d %H:%M:%S"),
                'scanned_by': scan_log.scanned_by.username if scan_log.scanned_by else "Unknown"
            })
        
        return JsonResponse({
            'success': True,
            'scans': scans_data
        })
        
    except ScanInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Print checkpoint not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


def print_station(request):
    return render(request, 'events/print_station.html')



from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from events.models import Ticket
import base64
from django.conf import settings
import os

def print_badge(request, ticket_id):
    """
    Renders a single badge in exact 102mm x 152mm print format
    """
    ticket = get_object_or_404(Ticket, id=ticket_id)
    
    # Determine the holder name (user or guest)
    if ticket.user:
        holder_name = f"{ticket.user.first_name} {ticket.user.last_name}".strip()
        if not holder_name:
            holder_name = ticket.user.username
    else:
        holder_name = ticket.guest_name or "Guest"
    
    # Determine ticket type and styling
    if ticket.staff_application:
        ticket_type = 'staff'
        role_display = ticket.staff_application.role if hasattr(ticket.staff_application, 'role') else 'Staff'
        header_color = '#a04ee2'  # Purple
        role_color = '#a04ee2'
    elif ticket.booth_number or ticket.booth:
        ticket_type = 'exhibitor'
        role_display = f'Booth {ticket.booth_number}' if ticket.booth_number else 'Exhibitor'
        header_color = '#3a9c3f'  # Green
        role_color = '#3a9c3f'
    else:
        ticket_type = 'delegate'
        role_display = 'Delegate'
        header_color = '#d4ab08'  # Gold
        role_color = '#d4ab08'
    
    # Get photo as base64 if exists
    attendee_photo_base64 = None
    if ticket.attendee_photo:
        try:
            with open(ticket.attendee_photo.path, 'rb') as img_file:
                attendee_photo_base64 = f"data:image/jpeg;base64,{base64.b64encode(img_file.read()).decode()}"
        except:
            pass
    
    # Get QR code as base64 if exists
    qr_code_base64 = None
    if ticket.qr_code:
        try:
            with open(ticket.qr_code.path, 'rb') as qr_file:
                qr_code_base64 = f"data:image/png;base64,{base64.b64encode(qr_file.read()).decode()}"
        except:
            pass
    
    # Load logo
    logo_base64 = None
    try:
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'assets', 'img', 'logosi.png')
        with open(logo_path, 'rb') as logo_file:
            logo_base64 = f"data:image/png;base64,{base64.b64encode(logo_file.read()).decode()}"
    except Exception as e:
        print(f"Could not load logo: {e}")
    
    context = {
        'user_details': {
            'name': holder_name,
            'company': ticket.company_name or 'N/A',
            'designation': ticket.designation or 'N/A',
            'role': role_display,
        },
        'ticket_type': ticket_type,
        'header_color': header_color,
        'role_color': role_color,
        'attendee_photo': attendee_photo_base64,
        'qr_code': qr_code_base64,
        'logo_nobg': logo_base64,
        'tag': '',
        'ticket': ticket,  # Pass the whole ticket for additional info
    }
    
    return render(request, 'events/badge_print.html', context)



def ticket_management_view(request):
    # if not request.session.get('reports_authenticated'):
    #     return redirect('controlpanel:reports_login')
    
    # Get ALL tickets - we filter on frontend for instant search
    tickets = Ticket.objects.select_related(
        'category', 'user', 'order', 'booth'
    ).order_by('-created_at')
    
    categories = TicketCategory.objects.all()
    
    # Calculate stats
    total_tickets = tickets.count()
    used_count = tickets.filter(is_used=True).count()
    not_used_count = tickets.filter(is_used=False).count()
    
    context = {
        'tickets': tickets,
        'categories': categories,
        'total_tickets': total_tickets,
        'used_count': used_count,
        'not_used_count': not_used_count,
    }
    
    return render(request, 'controlpanel/ticket_management.html', context)


from django.contrib import messages
from django.shortcuts import redirect
import uuid
from events.utils import generate_qr_code, generate_ticket_pdf, send_ticket_email
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os

def create_ticket_view(request):
    if request.method == 'POST':
        try:
            # Get form data
            category_id = request.POST.get('category')
            category = TicketCategory.objects.get(id=category_id)
            
            guest_name = request.POST.get('guest_name')
            guest_email = request.POST.get('guest_email')
            
            # Create the ticket
            ticket = Ticket.objects.create(
                category=category,
                guest_name=guest_name,
                guest_email=guest_email,
                guest_phone=request.POST.get('guest_phone', ''),
                company_name=request.POST.get('company_name', ''),
                designation=request.POST.get('designation', ''),
                country=request.POST.get('country', ''),
                city=request.POST.get('city', ''),
                kra_pin=request.POST.get('kra_pin', ''),
                tshirt_size=request.POST.get('tshirt_size', ''),
                ticket_number=f"TKT-{uuid.uuid4().hex[:8].upper()}",
                ticket_id=uuid.uuid4(),
                is_used=False,
                consent_given=True,
            )
            
            # 🖼️ Handle attendee photo if uploaded
            attendee_photo_path = None
            if 'attendee_photo' in request.FILES and request.FILES['attendee_photo']:
                photo = request.FILES['attendee_photo']
                photo_filename = f"{ticket.ticket_id}_{photo.name}"
                photo_path = f"attendee_photos/{photo_filename}"
                
                # Save using Django's storage system
                saved_path = default_storage.save(photo_path, photo)
                ticket.attendee_photo = saved_path
                ticket.save()
                
                # Get full path for PDF generation
                attendee_photo_path = os.path.join(settings.MEDIA_ROOT, saved_path)
            
            # 🎯 Handle QR Code (Custom or Auto-generate)
            qr_code_path = None
            has_custom_qr = 'custom_qr' in request.FILES and request.FILES['custom_qr']
            
            if has_custom_qr:
                # User uploaded custom QR
                qr_file = request.FILES['custom_qr']
                qr_filename = f"{ticket.ticket_id}_custom.png"
                qr_path = f'qr_codes/{qr_filename}'
                
                # Save using Django's storage
                saved_qr_path = default_storage.save(qr_path, qr_file)
                ticket.qr_code = saved_qr_path
                ticket.save()
                qr_code_path = saved_qr_path
                print(f"✅ Custom QR uploaded: {saved_qr_path}")
            else:
                # Auto-generate QR
                qr_code_path = generate_qr_code(ticket)
                if not qr_code_path:
                    raise ValueError("Failed to generate QR code")
                print(f"✅ QR auto-generated: {qr_code_path}")
            
            # 📄 Handle PDF (Custom or Auto-generate)
            pdf_relative_path = None
            has_custom_pdf = 'custom_pdf' in request.FILES and request.FILES['custom_pdf']
            
            if has_custom_pdf:
                # User uploaded custom PDF
                pdf_file = request.FILES['custom_pdf']
                pdf_filename = f"ticket_{ticket.id}_custom.pdf"
                pdf_path = f'tickets/{pdf_filename}'
                
                # Save using Django's storage
                saved_pdf_path = default_storage.save(pdf_path, pdf_file)
                ticket.pdf_ticket = saved_pdf_path
                ticket.save()
                pdf_relative_path = saved_pdf_path
                print(f"✅ Custom PDF uploaded: {saved_pdf_path}")
            else:
                # Auto-generate PDF
                user_details = {
                    'name': guest_name,
                    'email': guest_email,
                    'phone': request.POST.get('guest_phone', 'N/A'),
                    'company': request.POST.get('company_name', 'N/A'),
                    'designation': request.POST.get('designation', 'N/A'),
                    'country': request.POST.get('country', 'N/A'),
                    'city': request.POST.get('city', 'N/A'),
                }
                
                pdf_relative_path = generate_ticket_pdf(
                    request=request,
                    ticket=ticket,
                    user_details=user_details,
                    qr_code_path=qr_code_path,
                    attendee_photo_path=attendee_photo_path
                )
                
                ticket.pdf_ticket = pdf_relative_path
                ticket.save()
                print(f"✅ PDF auto-generated: {pdf_relative_path}")
            
            # 📧 Send email with ticket
            pdf_full_path = os.path.join(settings.MEDIA_ROOT, pdf_relative_path)
            
            try:
                send_ticket_email(guest_email, guest_name, pdf_full_path)
                
                # Success message with details
                upload_info = []
                if has_custom_qr:
                    upload_info.append("custom QR")
                if has_custom_pdf:
                    upload_info.append("custom PDF")
                
                if upload_info:
                    msg = f'✅ Ticket {ticket.ticket_number} created with {" & ".join(upload_info)} and emailed to {guest_email}!'
                else:
                    msg = f'✅ Ticket {ticket.ticket_number} created and emailed to {guest_email}!'
                
                messages.success(request, msg)
                
            except Exception as email_error:
                messages.warning(request, f'✅ Ticket {ticket.ticket_number} created, but email failed: {str(email_error)}')
            
            return redirect('controlpanel:ticket_management')
            
        except TicketCategory.DoesNotExist:
            messages.error(request, '❌ Invalid ticket category selected')
            return redirect('controlpanel:ticket_management')
        except Exception as e:
            messages.error(request, f'❌ Error creating ticket: {str(e)}')
            print(f"🔥 Ticket creation error: {str(e)}")
            import traceback
            traceback.print_exc()
            return redirect('controlpanel:ticket_management')
    
    return redirect('controlpanel:ticket_management')
    if request.method == 'POST':
        try:
            # Get form data
            category_id = request.POST.get('category')
            category = TicketCategory.objects.get(id=category_id)
            
            guest_name = request.POST.get('guest_name')
            guest_email = request.POST.get('guest_email')
            
            # Create the ticket
            ticket = Ticket.objects.create(
                category=category,
                guest_name=guest_name,
                guest_email=guest_email,
                guest_phone=request.POST.get('guest_phone', ''),
                company_name=request.POST.get('company_name', ''),
                designation=request.POST.get('designation', ''),
                country=request.POST.get('country', ''),
                city=request.POST.get('city', ''),
                kra_pin=request.POST.get('kra_pin', ''),
                tshirt_size=request.POST.get('tshirt_size', ''),
                ticket_number=f"TKT-{uuid.uuid4().hex[:8].upper()}",
                ticket_id=uuid.uuid4(),
                is_used=False,
                consent_given=True,
            )
            
            # 🖼️ Handle attendee photo if uploaded
            attendee_photo_path = None
            if 'attendee_photo' in request.FILES:
                photo = request.FILES['attendee_photo']
                photo_dir = os.path.join(settings.MEDIA_ROOT, 'attendee_photos')
                os.makedirs(photo_dir, exist_ok=True)
                
                photo_filename = f"{ticket.ticket_id}_{photo.name}"
                photo_path = os.path.join(photo_dir, photo_filename)
                
                with open(photo_path, 'wb+') as destination:
                    for chunk in photo.file.chunks():
                        destination.write(chunk)
                
                ticket.attendee_photo = f"attendee_photos/{photo_filename}"
                ticket.save()
                attendee_photo_path = photo_path
            
            # 🎯 Handle QR Code (Custom or Auto-generate)
            qr_code_path = None
            has_custom_qr = 'custom_qr' in request.FILES
            
            if has_custom_qr:
                # User uploaded custom QR
                qr_file = request.FILES['custom_qr']
                qr_dir = os.path.join(settings.MEDIA_ROOT, 'qr_codes')
                os.makedirs(qr_dir, exist_ok=True)
                
                qr_filename = f"{ticket.ticket_id}_custom.png"
                qr_path = default_storage.save(
                    f'qr_codes/{qr_filename}',
                    ContentFile(qr_file.read())
                )
                
                ticket.qr_code = qr_path
                ticket.save()
                qr_code_path = qr_path
                print(f"✅ Custom QR uploaded: {qr_path}")
            else:
                # Auto-generate QR
                qr_code_path = generate_qr_code(ticket)
                if not qr_code_path:
                    raise ValueError("Failed to generate QR code")
                print(f"✅ QR auto-generated: {qr_code_path}")
            
            # 📄 Handle PDF (Custom or Auto-generate)
            pdf_relative_path = None
            has_custom_pdf = 'custom_pdf' in request.FILES
            
            if has_custom_pdf:
                # User uploaded custom PDF
                pdf_file = request.FILES['custom_pdf']
                pdf_dir = os.path.join(settings.MEDIA_ROOT, 'tickets')
                os.makedirs(pdf_dir, exist_ok=True)
                
                pdf_filename = f"ticket_{ticket.id}_custom.pdf"
                pdf_path = default_storage.save(
                    f'tickets/{pdf_filename}',
                    ContentFile(pdf_file.read())
                )
                
                ticket.pdf_ticket = pdf_path
                ticket.save()
                pdf_relative_path = pdf_path
                print(f"✅ Custom PDF uploaded: {pdf_path}")
            else:
                # Auto-generate PDF
                user_details = {
                    'name': guest_name,
                    'email': guest_email,
                    'phone': request.POST.get('guest_phone', 'N/A'),
                    'company': request.POST.get('company_name', 'N/A'),
                    'designation': request.POST.get('designation', 'N/A'),
                    'country': request.POST.get('country', 'N/A'),
                    'city': request.POST.get('city', 'N/A'),
                }
                
                pdf_relative_path = generate_ticket_pdf(
                    request=request,
                    ticket=ticket,
                    user_details=user_details,
                    qr_code_path=qr_code_path,
                    attendee_photo_path=attendee_photo_path
                )
                
                ticket.pdf_ticket = pdf_relative_path
                ticket.save()
                print(f"✅ PDF auto-generated: {pdf_relative_path}")
            
            # 📧 Send email with ticket
            pdf_full_path = os.path.join(settings.MEDIA_ROOT, pdf_relative_path)
            
            try:
                send_ticket_email(guest_email, guest_name, pdf_full_path)
                
                # Success message with details
                upload_info = []
                if has_custom_qr:
                    upload_info.append("custom QR")
                if has_custom_pdf:
                    upload_info.append("custom PDF")
                
                if upload_info:
                    msg = f'✅ Ticket {ticket.ticket_number} created with {" & ".join(upload_info)} and emailed to {guest_email}!'
                else:
                    msg = f'✅ Ticket {ticket.ticket_number} created and emailed to {guest_email}!'
                
                messages.success(request, msg)
                
            except Exception as email_error:
                messages.warning(request, f'✅ Ticket {ticket.ticket_number} created, but email failed: {str(email_error)}')
            
            return redirect('controlpanel:ticket_management')
            
        except TicketCategory.DoesNotExist:
            messages.error(request, '❌ Invalid ticket category selected')
            return redirect('controlpanel:ticket_management')
        except Exception as e:
            messages.error(request, f'❌ Error creating ticket: {str(e)}')
            print(f"🔥 Ticket creation error: {str(e)}")
            import traceback
            traceback.print_exc()
            return redirect('controlpanel:ticket_management')
    
    return redirect('controlpanel:ticket_management')


def check_invoice_sent(request, holder_id):
    sent = SentInvoice.objects.filter(holder_id=holder_id).exists()
    return JsonResponse({'sent': sent})
    
import re

def get_sort_key(name):
    match = re.search(r'\((\d+)\)', name)
    return int(match.group(1)) if match else 999  # fallback    
# scan stats only

def scan_stats_view(request):
    # === EXACT SAME LOGIC AS unified_reports_view ===
    total_scannable_tickets = Ticket.objects.count()

    event_id = request.GET.get('event')
    scan_instances = (
        ScanInstance.objects.filter(event_id=event_id) if event_id
        else ScanInstance.objects.all()
    )

    checkpoint_stats = []
    for instance in scan_instances:
        scanned = Ticket.objects.filter(scan_logs__scan_instance=instance).distinct().count()
        checkpoint_stats.append({
            'id': instance.id,
            'name': instance.name,
            'event': instance.event.name if instance.event else 'All Events',
            'scanned': scanned,
            'remaining': total_scannable_tickets - scanned,
            'total': total_scannable_tickets,
            'sort_key': get_sort_key(instance.name),
        })

    # SORT EXACTLY LIKE unified_reports
    checkpoint_stats.sort(key=lambda x: x['name'].lower())  # case-insensitive

    context = {
        'checkpoint_stats': checkpoint_stats,
        'total_scannable_tickets': total_scannable_tickets,
    }
    return render(request, 'controlpanel/scan_stats.html', context)