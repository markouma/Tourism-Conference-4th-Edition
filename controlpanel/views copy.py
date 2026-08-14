from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from events.models import Event, Ticket, Order, StaffApplication, BoothVisit, BoothReview
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from decimal import Decimal
from django.db.models import Count, F, ExpressionWrapper, DecimalField, Max
from django.views.decorators.csrf import csrf_exempt
import csv, weasyprint
from events.models import Booth, Ticket, PaidApplication
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Case, When, Value, CharField
from django.core.paginator import Paginator

from reportlab.pdfgen import canvas
from io import BytesIO
from reportlab.lib.pagesizes import letter
from collections import defaultdict

from .models import SiteVisit

from weasyprint import HTML
import tempfile

from django.contrib.admin.views.decorators import staff_member_required




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



# Add this new view for deleting tickets
@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def delete_ticket(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, pk=ticket_id)
        event_id = ticket.category.event.id
        
        # Delete the ticket
        ticket.delete()
        
        # Add a success message
        messages.success(request, f'Ticket #{ticket.ticket_number} has been deleted successfully.')
        
        # Redirect back to the event detail page
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

    # Country statistics
    tickets_per_country = []
    for ticket in tickets:
        country = None
        
        # Try ticket.user first
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        # Then try ticket directly
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        # Finally try the order
        elif ticket.order and ticket.order.country:
            country = ticket.order.country
        
        if country and country.lower() != 'none':
            # Check if country already exists in list
            found = False
            for item in tickets_per_country:
                if item['country'] == country:
                    item['count'] += 1
                    found = True
                    break
            if not found:
                tickets_per_country.append({'country': country, 'count': 1})
    
    # Sort by count (highest first)
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

        # Safe revenue calculation
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
        request.session.modified = True  # extends the session expiry
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

    weasyprint.HTML(string=html_string).write_pdf(response)
    return response



def booth_sales_view(request):
    booths = Booth.objects.select_related('booked_by', 'order', 'event').all()
    events = Event.objects.all()  # for event filter dropdown

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
    users = User.objects.all().order_by('email')
    return render(request, 'controlpanel/manage_users.html', {'users': users})



@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def payment_gateway_report_view(request):
    # Annotate payment_method based on fields:
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


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def manage_users_view(request):
    event_id = request.GET.get('event')
    user_type = request.GET.get('type')  # 'orders', 'staff', or None for all
    status = request.GET.get('status')   # 'paid', 'unpaid', 'pending', 'approved', etc.

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

    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="tag_applicants.pdf"'

    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        HTML(string=html_string).write_pdf(target=response)

    return response




@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def booth_visits_report(request):
    booths = Booth.objects.annotate(visit_count=Count('boothvisit')).all()  # or Count('visits') if related_name set
    max_visits = booths.aggregate(max_visit=Max('visit_count'))['max_visit'] or 1

    visits = BoothVisit.objects.select_related('booth', 'visitor').order_by('booth__name', '-scanned_at')[:500]
    visits_by_booth = defaultdict(list)
    for visit in visits:
        visits_by_booth[visit.booth].append(visit)
    context = {
        'booths': booths,
        'max_visits': max_visits,
        'visits': visits,
        'visits_by_booth': dict(visits_by_booth),

    }
    return render(request, 'controlpanel/booth_visits_report.html', context)

@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def booth_reviews_report(request):
    reviews = BoothReview.objects.select_related('booth', 'reviewer').order_by('-created_at')
    return render(request, 'controlpanel/booth_reviews_report.html', {'reviews': reviews})





def traffic_report(request):
    visits = SiteVisit.objects.order_by('-timestamp')

    # Group visits by IP
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

    # Summary stats
    total_visits = visits.count()
    total_users = ip_groups.keys().__len__()
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
    """
    Display all paid application ticket holders with editable amount and mpesa_message fields
    """
    if request.method == 'POST':
        # Handle bulk update
        updated_count = 0
        
        for key, value in request.POST.items():
            if key.startswith('amount_'):
                app_id = key.split('_')[1]
                try:
                    app = PaidApplication.objects.get(id=app_id)
                    
                    # Update amount
                    amount_value = request.POST.get(f'amount_{app_id}', '').strip()
                    if amount_value:
                        app.amount = float(amount_value)
                    else:
                        app.amount = None
                    
                    # Update mpesa message
                    mpesa_msg = request.POST.get(f'mpesa_message_{app_id}', '').strip()
                    app.mpesa_message = mpesa_msg if mpesa_msg else None
                    
                    app.save()
                    updated_count += 1
                except (PaidApplication.DoesNotExist, ValueError):
                    continue
        
        messages.success(request, f'Successfully updated {updated_count} records!')
        return redirect('controlpanel:paid_reports')
    
    # GET request with sorting
    sort_by = request.GET.get('sort', '-approved')  # Default sort by approval date (newest first)
    
    # Fetch all approved paid applications with tickets
    tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application')
    
    # Apply sorting
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
    
    # Deduplicate by name + email + phone
    seen_combinations = set()
    unique_tickets = []
    
    for ticket in tickets:
        app = ticket.paid_application
        
        # Create unique key (normalize data for comparison)
        unique_key = (
            app.full_name.strip().lower() if app.full_name else '',
            app.email.strip().lower() if app.email else '',
            app.phone.strip() if app.phone else ''
        )
        
        # Only add if this combination hasn't been seen before
        if unique_key not in seen_combinations:
            seen_combinations.add(unique_key)
            unique_tickets.append(ticket)
    
    # Calculate total amount (only from unique entries)
    unique_app_ids = [t.paid_application.id for t in unique_tickets]
    total_amount = PaidApplication.objects.filter(
        id__in=unique_app_ids,
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Country statistics
    tickets_per_country = []
    for ticket in unique_tickets:
        app = ticket.paid_application
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        # Check if country already exists in list
        found = False
        for item in tickets_per_country:
            if item['country'] == country:
                item['count'] += 1
                found = True
                break
        if not found:
            tickets_per_country.append({'country': country, 'count': 1})
    
    # Sort by count (highest first)
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    # Prepare data for template
    report_data = []
    for ticket in unique_tickets:
        app = ticket.paid_application
        
        # Determine status
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
    """
    Generate and download a branded PDF report of paid applications
    """
    # Fetch data
    tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application').order_by('-created_at')
    
    total_amount = PaidApplication.objects.filter(
        status='approved',
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Country statistics
    tickets_per_country = []
    for ticket in tickets:
        app = ticket.paid_application
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        # Check if country already exists in list
        found = False
        for item in tickets_per_country:
            if item['country'] == country:
                item['count'] += 1
                found = True
                break
        if not found:
            tickets_per_country.append({'country': country, 'count': 1})
    
    # Sort by count (highest first)
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    # Prepare data
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
    
    # Render HTML template
    html_string = render_to_string('controlpanel/paid_reports_pdf.html', context)
    
    # Generate PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    
    # Create response
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="paid_applications_report.pdf"'
    
    return response


@login_required(login_url='/controlpanel/login/')
@user_passes_test(is_admin, login_url='/controlpanel/login/')
def download_event_detail_pdf(request, event_id):
    """
    Generate and download a branded PDF report of event ticket sales
    """
    event = get_object_or_404(Event, pk=event_id)
    tickets = Ticket.objects.filter(category__event=event).select_related('user', 'category', 'order').order_by('-created_at')

    # Calculate totals
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
    
    # Calculate grand total
    grand_total = sum(cat['total_revenue'] for cat in tickets_per_category)
    
    # Country statistics
    tickets_per_country = []
    for ticket in tickets:
        country = None
        
        # Try ticket.user first
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        # Then try ticket directly
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        # Finally try the order
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
    
    # Sort by count (highest first)
    tickets_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    # Prepare ticket data
    ticket_data = []
    for ticket in tickets:
        # Get country
        country = 'N/A'
        if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
            country = ticket.user.country
        elif hasattr(ticket, 'country') and ticket.country:
            country = ticket.country
        elif ticket.order and ticket.order.country:
            country = ticket.order.country
            
        # Get city
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
    
    # Render HTML template
    html_string = render_to_string('controlpanel/event_detail_pdf.html', context)
    
    # Generate PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    
    # Create response
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="event_ticket_report_{event.name.replace(" ", "_")}.pdf"'
    
    return response



def reports_login(request):
   
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if username == 'samora1' and password == 'samora1':
            request.session['reports_authenticated'] = True
            return redirect('controlpanel:unified_reports')
        else:
            messages.error(request, 'Invalid credentials. Please try again.')
    
    return render(request, 'controlpanel/reports_login.html')


def reports_logout(request):
    """
    Logout from reports view
    """
    if 'reports_authenticated' in request.session:
        del request.session['reports_authenticated']
    return redirect('controlpanel:reports_login')


def unified_reports_view(request):
    """
    Unified reports dashboard showing ALL data from all reports in one page
    Requires simple session authentication
    """
    # Check if user is authenticated for reports
    if not request.session.get('reports_authenticated'):
        return redirect('controlpanel:reports_login')
    
    # ==================== EVENT TICKETS DATA ====================
    events = Event.objects.all()
    all_event_data = []
    
    for event in events:
        tickets = Ticket.objects.filter(
            category__event=event
        ).select_related('user', 'category', 'order').order_by('-created_at')
        
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
        
        # Country statistics for this event
        event_countries = []
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
                for item in event_countries:
                    if item['country'] == country:
                        item['count'] += 1
                        found = True
                        break
                if not found:
                    event_countries.append({'country': country, 'count': 1})
        
        event_countries.sort(key=lambda x: x['count'], reverse=True)
        
        # Prepare ticket data for table
        ticket_list = []
        for ticket in tickets:
            # Get country
            country = 'N/A'
            if ticket.user and hasattr(ticket.user, 'country') and ticket.user.country:
                country = ticket.user.country
            elif hasattr(ticket, 'country') and ticket.country:
                country = ticket.country
            elif ticket.order and ticket.order.country:
                country = ticket.order.country
                
            # Get city
            city = 'N/A'
            if ticket.user and hasattr(ticket.user, 'city') and ticket.user.city:
                city = ticket.user.city
            elif hasattr(ticket, 'city') and ticket.city:
                city = ticket.city
            elif ticket.order and ticket.order.city:
                city = ticket.order.city
            
            ticket_list.append({
                'ticket_number': ticket.ticket_number,
                'buyer': ticket.user.username if ticket.user else (ticket.guest_name or 'Unknown'),
                'country': country,
                'city': city,
                'category': ticket.category.name if ticket.category else 'N/A',
                'price': ticket.category.price if ticket.category else 0,
                'purchase_date': ticket.created_at,
                'is_used': ticket.is_used,
                'ticket_id': ticket.id,
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
    
    # ==================== BOOTH SALES DATA ====================
    booths = Booth.objects.select_related('booked_by', 'order').order_by('name')
    
    booth_list = []
    for booth in booths:
        booth_list.append({
            'name': booth.name,
            'price': booth.price,
            'is_booked': booth.is_booked,
            'booked_by': booth.booked_by.get_full_name() if booth.booked_by and booth.booked_by.get_full_name() else (booth.booked_by.username if booth.booked_by else '—'),
            'order_id': booth.order.id if booth.order else '—',
            'booked_at': booth.booked_at,
        })
    
    # 🔥 CRITICAL FIX: Only sum BOOKED booth prices
    total_booth_revenue = booths.filter(is_booked=True).aggregate(total=Sum('price'))['total'] or 0
    total_booths_booked = booths.filter(is_booked=True).count()
    total_booths_available = booths.filter(is_booked=False).count()
    
    # ==================== PAID APPLICATIONS DATA ====================
    paid_tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application').order_by('-created_at')
    
    # Deduplicate by name + email + phone
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
    
    # Paid apps country data
    paid_per_country = []
    for ticket in unique_paid_tickets:
        app = ticket.paid_application
        country = app.country if hasattr(app, 'country') and app.country else 'Unknown'
        
        found = False
        for item in paid_per_country:
            if item['country'] == country:
                item['count'] += 1
                found = True
                break
        if not found:
            paid_per_country.append({'country': country, 'count': 1})
    
    paid_per_country.sort(key=lambda x: x['count'], reverse=True)
    
    # Prepare paid apps data for table
    paid_app_list = []
    for ticket in unique_paid_tickets:
        app = ticket.paid_application
        paid_app_list.append({
            'full_name': app.full_name,
            'email': app.email,
            'phone': app.phone or 'N/A',
            'country': app.country if hasattr(app, 'country') and app.country else 'Unknown',
            'ticket_number': ticket.ticket_number or str(ticket.ticket_id)[:8],
            'is_used': ticket.is_used,
            'status_text': 'Used' if ticket.is_used else 'Not Used',
            'approved_date': app.submitted_at,
            'amount': app.amount or 0,
            'mpesa_message': app.mpesa_message or 'N/A',
            'has_pdf': bool(ticket.pdf_ticket),
            'pdf_url': ticket.pdf_ticket.url if ticket.pdf_ticket else None,
        })
    
    unique_app_ids = [t.paid_application.id for t in unique_paid_tickets]
    total_paid_amount = PaidApplication.objects.filter(
        id__in=unique_app_ids,
        amount__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    context = {
        # Event Tickets
        'all_event_data': all_event_data,
        'total_ticket_revenue': total_ticket_revenue,
        'total_tickets_sold': total_tickets_sold,
        
        # Booth Sales
        'booth_list': booth_list,
        'total_booth_revenue': total_booth_revenue,
        'total_booths_booked': total_booths_booked,
        'total_booths_available': total_booths_available,
        'total_booths': booths.count(),
        
        # Paid Applications
        'paid_app_list': paid_app_list,
        'total_paid_apps': len(paid_app_list),
        'total_paid_amount': total_paid_amount,
        'paid_per_country': paid_per_country,
        
        # Grand Totals
        'grand_total_revenue': total_ticket_revenue + total_booth_revenue + total_paid_amount,
    }
    
    return render(request, 'controlpanel/unified_reports.html', context)
