from django.contrib import admin, messages
from .models import Event, TicketCategory, Order, Ticket, StaffApplication, PaidApplication, BoothApplication, BoothRepresentative, PaidBoothApplication, ScanInstance, TicketScanLog, Speaker
from .utils import generate_qr_code, generate_ticket_pdf, send_ticket_email, send_reject_email1, send_boothrep_ticket_email, send_boothrep_reject_email, image_to_base64
from django.urls import reverse, path
from django.utils.html import format_html, mark_safe
from django.conf import settings
import os
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponseRedirect
 


class TicketCategoryInline(admin.TabularInline):
    model = TicketCategory
    extra = 1
    readonly_fields = ('remaining_tickets_display',)  # Read-only display
    fields = ('name', 'price', 'available_tickets', 'remaining_tickets_display')

    def remaining_tickets_display(self, obj):
        return obj.remaining_tickets()
    remaining_tickets_display.short_description = 'Remaining Tickets'

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    inlines = [TicketCategoryInline]
    list_display = ('name', 'date', 'location', 'event_type')
    actions = ['create_default_scan_instances']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'user_email', 'total_amount', 'is_paid', 'created_at', 'order_photo')
    def order_photo(self, obj):
        if obj.attendee_photo:
            return format_html('<img src="{}" width="80" height="80" style="object-fit:cover;border-radius:6px;" />', obj.attendee_photo.url)
        return "No photo"
    order_photo.short_description = "Attendee Photo"


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number', 'guest_name', 'guest_email', 'category',
        'order', 'booth' , 'kra_pin', 'staff_application', 'is_used'
    )
    list_filter = ('is_used', 'category', 'tshirt_size', 'country', 'city')
    search_fields = (
        'guest_name', 'guest_email', 'company_name' , 'kra_pin', 'designation',
        'industry', 'sector', 'ticket_number'
    )

    readonly_fields = (
        'ticket_number', 'ticket_id', 'verification_hash',
        'qr_code', 'pdf_ticket', 'first_scanned_at'
    )

    fieldsets = (
        ('Ticket Basics', {
            'fields': ('user', 'order', 'category', 'booth', 'staff_application')
        }),

        ('Guest Info', {
            'fields': (
                'guest_name', 'guest_email', 'guest_phone',
                'attendee_photo', 'company_name' , 'kra_pin',  'designation'
            )
        }),

        ('Industry Info', {
            'fields': ('industry', 'industry_description')
        }),

        ('Demographics & Preferences', {
    'fields': (
        'country', 'city', 'age_range',
        'tshirt_size', 'sector', 'heard_about', 'consent_given'
    )
}),


        ('Verification', {
            'fields': (
                'ticket_number', 'ticket_id', 'verification_hash',
                'qr_code', 'pdf_ticket', 'is_used', 'first_scanned_at'
            )
        }),
    )



 

@admin.register(StaffApplication)
class StaffApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'email', 'role', 'status', 'tag_sent', 
        'submitted_at', 'country', 'sector', 'age_range', 'consent', 'approve_link'
    )
    list_filter = ('status', 'role', 'tag_sent', 'country', 'sector', 'age_range')
    search_fields = ('full_name', 'email', 'sector', 'country')

    actions = ['approve_and_send_ticket', 'reject_and_send_email'] 

    def approve_link(self, obj):
        if obj.status == 'pending':
            approve_url = reverse('approve_staff', args=[obj.id])  
            reject_url = reverse('reject_staff', args=[obj.id])  

            return format_html(
                '<a class="button" href="{}" style="margin-right:8px;">Approve</a>'
                '<a class="button" style="color:red;" href="{}">Reject</a>',
                approve_url,
                reject_url
            )
        elif obj.status == 'approved':
            return mark_safe('<span style="color: green;">Approved</span>')
        elif obj.status == 'rejected':
            return mark_safe('<span style="color: red;">Rejected</span>')
        return ''
    approve_link.short_description = 'Quick Actions'

    def approve_and_send_ticket(self, request, queryset):
        """Bulk approve & generate/send tickets"""
        approved_count = 0
        for app in queryset.filter(status='pending'):
            # Mark as approved
            app.status = 'approved'        
            app.save()

            # Get or create category
            category, created = TicketCategory.objects.get_or_create(
            name="Paid Booth Representative", 
            event_id=1,
            defaults={'price': 0}
)

            # Create ticket
            ticket = Ticket.objects.create(
                guest_name=app.full_name,
                guest_email=app.email,
                guest_phone=app.phone,
                company_name=app.company,
                designation=app.designation,
                country=app.country,
                city=app.city,
                age_range=app.age_range,
                tshirt_size=app.tshirt_size,
                consent_given=app.consent,
                sector=app.sector,
                heard_about=app.referral_source,
                staff_application=app,
                attendee_photo=app.photo,
            )

            # Generate QR
            generate_qr_code(ticket)

            # Create user_details dict
            user_details = {
                'name': app.full_name,
                'company': 'STAFF',
                'designation': app.role.upper(),
                'role': app.role.capitalize(),
            }

            # PDF badge
            pdf_rel_path = generate_ticket_pdf(
                request=None,  # works fine
                ticket=ticket,
                user_details=user_details,
                qr_code_path=str(ticket.qr_code),
                attendee_photo_path=None
            )

            # Email ticket
            full_pdf_path = os.path.join(settings.MEDIA_ROOT, pdf_rel_path)
            send_ticket_email(app.email, app.full_name, full_pdf_path)

            app.tag_sent = True
            app.save()
            approved_count += 1

        self.message_user(request, f"{approved_count} staff approved and tickets sent.")
    approve_and_send_ticket.short_description = "✅ Approve and Send Ticket(s)"

    def reject_and_send_email(self, request, queryset):
        """Bulk reject & notify applicants"""
          # import here to avoid circular import

        rejected_count = 0
        for app in queryset.filter(status='pending'):
            app.status = 'rejected'
            app.save()

            send_reject_email1(app.email, app.full_name)
            rejected_count += 1

        self.message_user(request, f"{rejected_count} staff rejected and notified.")




    reject_and_send_email.short_description = "❌ Reject and Send Email(s)"


@admin.register(PaidApplication)
class PaidApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'email', 'role', 'status', 'mpesa_code',
        'tag_sent', 'submitted_at', 'approve_link'
    )
    list_filter = ('status', 'role', 'tag_sent')
    search_fields = ('full_name', 'email', 'mpesa_code')

    actions = ['approve_and_send_ticket', 'reject_and_notify']

    def approve_link(self, obj):
        if obj.status == 'pending':
            approve_url = reverse('approve_paid', args=[obj.id])
            reject_url = reverse('reject_paid', args=[obj.id])
            return format_html(
                '<a class="button" href="{}" style="margin-right:8px;">Approve</a>'
                '<a class="button" href="{}" style="color:red;">Reject</a>',
                approve_url,
                reject_url,
            )
        elif obj.status == 'approved':
            return mark_safe('<span style="color: green;">Approved</span>')
        elif obj.status == 'rejected':
            return mark_safe('<span style="color: red;">Rejected</span>')
        return ''
    approve_link.short_description = 'Quick Action'

    def approve_and_send_ticket(self, request, queryset):
        approved_count = 0
        for app in queryset.filter(status='pending'):
            app.status = 'approved'
            app.save()

            ticket = Ticket.objects.create(
                guest_name=app.full_name,
                guest_email=app.email,
                guest_phone=app.phone,
                company_name=app.company,
                designation=app.designation,
                country=app.country,
                city=app.city,
                age_range=app.age_range,
                tshirt_size=app.tshirt_size,
                consent_given=app.consent,
                sector=app.sector,
                heard_about=app.referral_source,
                staff_application=None,
                attendee_photo=app.photo,
            )

            generate_qr_code(ticket)

            user_details = {
                'name': app.full_name,
                'company': app.company or "Guest",
                'designation': app.role.upper(),
                'role': app.role.capitalize(),
            }

            pdf_rel_path = generate_ticket_pdf(
                request=None,
                ticket=ticket,
                user_details=user_details,
                qr_code_path=str(ticket.qr_code),
                attendee_photo_path=None
            )

            full_pdf_path = os.path.join(settings.MEDIA_ROOT, pdf_rel_path)
            send_ticket_email(app.email, app.full_name, full_pdf_path)

            app.tag_sent = True
            app.save()
            approved_count += 1

        self.message_user(request, f"{approved_count} paid applications approved and tickets sent.")
    approve_and_send_ticket.short_description = "✅ Approve and Send Ticket(s)"

    def reject_and_notify(self, request, queryset):
        from .views import send_reject_email1
        rejected_count = 0
        for app in queryset.filter(status='pending'):
            app.status = 'rejected'
            app.save()
            send_reject_email1(app.email, app.full_name)
            rejected_count += 1
        self.message_user(request, f"{rejected_count} paid applications rejected and notified.")
    reject_and_notify.short_description = "❌ Reject and Send Email(s)"
    

@admin.register(BoothApplication)
class BoothApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'company', 'booth_number', 'primary_rep_name', 'primary_rep_email', 
        'primary_rep_country', 'tag_sent', 'status', 'submitted_at', 'action_buttons'
    )
    list_filter = ('status', 'event')
    search_fields = ['company', 'booth_number', 'representatives__name', 'representatives__email']
    actions = ['approve_and_send_tickets', 'reject_applications']

    # -----------------
    # Custom Display Methods
    # -----------------
    def primary_rep_name(self, obj):
        rep = obj.representatives.first()
        return rep.name if rep else "-"
    primary_rep_name.short_description = "Rep Name"

    def primary_rep_email(self, obj):
        rep = obj.representatives.first()
        return rep.email if rep else "-"
    primary_rep_email.short_description = "Rep Email"

    def primary_rep_country(self, obj):
        rep = obj.representatives.first()
        return rep.country if rep else "-"
    primary_rep_country.short_description = "Country"

    # -----------------
    # Bulk Actions
    # -----------------
    def approve_and_send_tickets(self, request, queryset):
        for app in queryset:
            self._approve_single_app(request, app)
        self.message_user(request, "✅ Selected applications approved and tickets sent!")

    approve_and_send_tickets.short_description = "Approve Booth Reps + Send Tickets"

    def reject_applications(self, request, queryset):
        for app in queryset:
            self._reject_single_app(request, app)
        self.message_user(request, "❌ Selected applications rejected.", level=messages.ERROR)

    reject_applications.short_description = "Reject Booth Reps (Send Email)"

    # -----------------
    # Row Buttons
    # -----------------
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:app_id>/approve/', self.admin_site.admin_view(self.approve_single), name="boothapp_approve"),
            path('<int:app_id>/reject/', self.admin_site.admin_view(self.reject_single), name="boothapp_reject"),
        ]
        return custom_urls + urls

    def action_buttons(self, obj):
        if obj.status == 'pending':
            return format_html(
                '<a class="button" href="{}">✅ Approve</a>&nbsp;'
                '<a class="button" style="color:red;" href="{}">❌ Reject</a>',
                f"{obj.id}/approve/",
                f"{obj.id}/reject/"
            )
        elif obj.status == 'approved':
            return format_html('<span style="color:green;">✅ Approved</span>')
        elif obj.status == 'rejected':
            return format_html('<span style="color:red;">❌ Rejected</span>')
        return "-"

    action_buttons.short_description = "Actions"
    action_buttons.allow_tags = True

    def approve_single(self, request, app_id):
        app = BoothApplication.objects.get(pk=app_id)
        self._approve_single_app(request, app)
        self.message_user(request, f"✅ {app.company} approved + tickets sent!")
        return redirect("..")

    def reject_single(self, request, app_id):
        app = BoothApplication.objects.get(pk=app_id)
        self._reject_single_app(request, app)
        self.message_user(request, f"❌ {app.company} rejected.", level=messages.ERROR)
        return redirect("..")

    # -----------------
    # Helper funcs
    # -----------------
    def _approve_single_app(self, request, app: BoothApplication):
        # Approve the application
        app.status = "approved"
        app.save()
        boothrep_category, _ = TicketCategory.objects.get_or_create(
            name="Booth Representative",
            defaults={"event": app.event, "price": 0}
        )

        # Loop through all representatives
        for rep in app.representatives.all():
            # 1️⃣ Create ticket for this representative - NOW WITH COUNTRY & CITY!
            ticket = Ticket.objects.create(
                guest_email=rep.email,
                guest_name=rep.name,
                company_name=app.company,
                guest_phone=rep.phone,
                attendee_photo=rep.photo,
                country=rep.country,  # ✅ ADDED
                city=rep.city,        # ✅ ADDED
                category=boothrep_category,
            )

            # 2️⃣ Generate QR code
            qr_code_path = generate_qr_code(ticket)
            if not qr_code_path:
                print(f"❌ QR not generated for Ticket {ticket.id}")
                continue

            # 3️⃣ Prepare user details
            user_details = {
                "company": app.company,
                "email": rep.email,
                "contact": rep.name,
            }

            # 4️⃣ Generate PDF
            context = {
                'company': app.company,
                'booth_number': app.booth_number,
                'rep_name': rep.name,
                'rep_email': rep.email,
                'attendee_photo': rep.photo,
                'qr_code': image_to_base64(qr_code_path),
                'logo': image_to_base64(os.path.join(settings.STATIC_ROOT, 'assets/img/logo.jpg')),
            }
            pdf_rel_path = generate_ticket_pdf(
                request,
                ticket,
                user_details,
                qr_code_path,
                attendee_photo_path=rep.photo.path,
                extra_context={
                    'company': app.company,
                    'booth_number': app.booth_number,
                    'rep_name': rep.name,
                    'rep_email': rep.email,
                }
            )

            pdf_full_path = os.path.join(settings.MEDIA_ROOT, pdf_rel_path)

            # 5️⃣ Send ticket email
            send_ticket_email(rep.email, rep.name, pdf_full_path)

        # ✅ Mark that tags/tickets have been sent
        app.tag_sent = True
        app.save()

    def _reject_single_app(self, request, app):
        app.status = 'rejected'
        app.save()

        for rep in app.representatives.all():
            send_boothrep_reject_email(rep.email, rep.name)
            


@admin.register(PaidBoothApplication)
class PaidBoothApplicationAdmin(admin.ModelAdmin):
    """
    Simple Django admin for PaidBoothApplication with approve/reject buttons
    """
    
    # Fields to show in list view
    list_display = [
        'id',
        'name', 
        'company',
        'booth_number',
        'email',
        'phone_number',
        'status_badge',
        'applied_at',
        'action_buttons',
        'receipt_info',  
    ]
    
    # Filters in sidebar
    list_filter = ['status', 'applied_at', 'country', 'industry']
    
    # Search fields
    search_fields = ['name', 'email', 'company', 'booth_number']
    
    # Default ordering
    ordering = ['-applied_at']
    
    # Read-only fields
    readonly_fields = ['applied_at', 'reviewed_at', 'ticket']
    
    def status_badge(self, obj):
        """Show colored status badge"""
        if obj.status == 'pending':
            color = 'orange'
        elif obj.status == 'approved':
            color = 'green'
        else:
            color = 'red'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def action_buttons(self, obj):
        """Show approve/reject buttons for pending applications"""
        if obj.status == 'pending':
            return format_html(
                '<a href="{}" style="background: green; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; margin-right: 5px;">✓ APPROVE</a>'
                '<a href="{}" style="background: red; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;">✗ REJECT</a>',
                reverse('admin:approve_application', args=[obj.id]),
                reverse('admin:reject_application', args=[obj.id])
            )
        else:
            return format_html('<span style="color: gray;">Action completed</span>')
    
    action_buttons.short_description = 'Actions'
    
    # Add custom URLs for approve/reject
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('approve/<int:app_id>/', self.admin_site.admin_view(self.approve_application), name='approve_application'),
            path('reject/<int:app_id>/', self.admin_site.admin_view(self.reject_application), name='reject_application'),
        ]
        return custom_urls + urls
    
    def approve_application(self, request, app_id):
        """Handle approve button click - UPDATED for dual email sending"""
        application = get_object_or_404(PaidBoothApplication, id=app_id)
        
        if application.status != 'pending':
            messages.error(request, f"Application {app_id} is already {application.status}")
            return HttpResponseRedirect(reverse('admin:events_paidboothapplication_changelist'))
        
        try:
            # Approve the application
            application.approve(request.user, "Your application has been approved!")
            
            # Create ticket
            ticket = self.create_ticket_from_application(request, application)
            
            # 🆕 SEND RECEIPT EMAIL FIRST
            from .views import send_paid_booth_receipt_email
            receipt_sent = send_paid_booth_receipt_email(application)
            
            # 🆕 SEND TICKET EMAIL SECOND  
            from .views import send_paid_booth_approval_email
            send_paid_booth_approval_email(application, ticket)
            
            # Success message
            if receipt_sent:
                messages.success(
                    request, 
                    f"✅ Approved application for {application.name}! "
                    f"Receipt and ticket emails sent to {application.email} "
                    f"(CC: accounts@buzzafrique.co.ke, coasttourismconference@gmail.com)"
                )
            else:
                messages.warning(
                    request,
                    f"⚠️ Application approved and ticket sent, but receipt email failed. "
                    f"Please check logs and resend receipt manually."
                )
            
        except Exception as e:
            messages.error(request, f"❌ Error approving application: {str(e)}")
        
        return HttpResponseRedirect(reverse('admin:events_paidboothapplication_changelist'))

    def receipt_info(self, obj):
        """Show receipt information in admin list"""
        if obj.paid_booth_receipt_number:
            return format_html(
                '<span style="font-size: 11px; color: #666;">{}<br>Generated: {}</span>',
                obj.paid_booth_receipt_number,
                obj.paid_booth_receipt_generated_at.strftime('%d/%m/%Y %H:%M') if obj.paid_booth_receipt_generated_at else 'N/A'
            )
        return format_html('<span style="color: #999; font-size: 11px;">No receipt</span>')

    receipt_info.short_description = 'Receipt Info'

    
    def reject_application(self, request, app_id):
        """Handle reject button click"""
        application = get_object_or_404(PaidBoothApplication, id=app_id)
        
        if application.status != 'pending':
            messages.error(request, f"Application {app_id} is already {application.status}")
            return HttpResponseRedirect(reverse('admin:events_paidboothapplication_changelist'))
        
        try:
            # Reject the application
            application.reject(request.user, "We're sorry, but your application was not approved at this time.")
            
            # Send rejection email
            from .views import PaidBooth_rejection_email
            PaidBooth_rejection_email(application)
            
            messages.success(request, f"❌ Rejected application for {application.name}. Email sent to {application.email}")
            
        except Exception as e:
            messages.error(request, f"❌ Error rejecting application: {str(e)}")
        
        return HttpResponseRedirect(reverse('admin:events_paidboothapplication_changelist'))
    
    def create_ticket_from_application(self, request, application):
        """Create ticket when application is approved"""
        # Get or create category
        # Get or create category
        category, _ = TicketCategory.objects.get_or_create(
            name="Paid Booth Representative",
            event_id=1,
            defaults={'price': 0}
        )
        
        # Create ticket
        # event = Event.objects.get(id=1)
        ticket = Ticket.objects.create(
            category=category,
            # event=event,
            guest_email=application.email,
            guest_name=application.name,
            guest_phone=application.phone_number,
            company_name=application.company,
            designation=application.title_designation,
            industry=application.industry,
            country=application.country,
            city=application.city,
            booth_number=application.booth_number,
            consent_given=application.consent_given,
            attendee_photo=application.profile_image,
        )
        
        # Link ticket to application
        application.ticket = ticket
        application.save()
        
        # Generate QR and PDF
        from .utils import generate_qr_code, generate_ticket_pdf
        
        qr_code_path = generate_qr_code(ticket)
        
        if qr_code_path:
            user_details = {
                'name': application.name,
                'email': application.email,
                'phone': application.phone_number,
                'company': application.company,
                'designation': application.title_designation,
            }
            
            pdf_path = generate_ticket_pdf(
                request=request,
                ticket=ticket,
                user_details=user_details,
                qr_code_path=qr_code_path,
                attendee_photo_path=application.profile_image.path if application.profile_image else None
            )
            
            ticket.pdf_ticket = pdf_path
            ticket.save()
        
        return ticket







# multi-scan model


# admin.py - Updated admin configuration



# Inline class for showing scan logs inside ScanInstance admin
class ScanLogInline(admin.TabularInline):
    model = TicketScanLog
    extra = 1
    fields = ('ticket', 'scanned_by', 'scanned_at')
    readonly_fields = ('scanned_at',)  # Keep it visible but readonly in inline


@admin.register(ScanInstance)
class ScanInstanceAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'is_active', 'created_at', 'scan_count')
    list_filter = ('is_active', 'event', 'created_at')
    search_fields = ('name', 'event__name', 'description')
    ordering = ('event', 'name')
    inlines = [ScanLogInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'event', 'description')
        }),
        ('Settings', {
            'fields': ('is_active',)
        })
    )
    
    def scan_count(self, obj):
        """Display the number of scans for this instance"""
        return obj.scan_logs.count()
    scan_count.short_description = 'Total Scans'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('event')


@admin.register(TicketScanLog)
class TicketScanLogAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'scan_instance', 'scanned_by', 'scanned_at', 'event_name')
    list_filter = ('scan_instance', 'scanned_at', 'scan_instance__event')
    search_fields = ('ticket__ticket_number', 'ticket__guest_name', 'ticket__user__username', 'scanned_by__username')
    
    ordering = ('-scanned_at',)
    
    fieldsets = (
        ('Scan Information', {
            'fields': ('ticket', 'scan_instance', 'scanned_by', 'scanned_at')
        }),
    )
    
    # Override to make scanned_at editable
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing existing
            return []  # Everything editable
        return ['scanned_at']  # When creating new, let it auto-set
    
    def ticket_number(self, obj):
        return obj.ticket.ticket_number or str(obj.ticket.ticket_id)[:8]
    ticket_number.short_description = 'Ticket'
    
    def event_name(self, obj):
        return obj.scan_instance.event.name
    event_name.short_description = 'Event'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'ticket', 'scan_instance__event', 'scanned_by'
        )


# Inline for Ticket admin
class TicketScanLogInline(admin.TabularInline):
    model = TicketScanLog
    extra = 1
    fields = ('scan_instance', 'scanned_by', 'scanned_at')
    readonly_fields = ('scanned_at',)


# Custom admin action to create default scan instances for events
def create_default_scan_instances(modeladmin, request, queryset):
    """Create default scan instances (Entrance, Meals 1, Meals 2) for selected events"""
    default_instances = [
        ('Entrance', 'Main event entrance checkpoint'),
        ('Meals 1', 'First meal service checkpoint'), 
        ('Meals 2', 'Second meal service checkpoint')
    ]
    created_count = 0
    
    for event in queryset:
        for instance_name, description in default_instances:
            scan_instance, created = ScanInstance.objects.get_or_create(
                name=instance_name,
                event=event,
                defaults={
                    'description': description,
                    'is_active': True
                }
            )
            if created:
                created_count += 1
    
    modeladmin.message_user(
        request,
        f'Successfully created {created_count} scan instances.'
    )
create_default_scan_instances.short_description = "Create default scan instances"


def receipt_info(self, obj):
    """Show receipt information in admin list"""
    if obj.paid_booth_receipt_number:
        return format_html(
            '<span style="font-size: 11px; color: #666;">{}<br>Generated: {}</span>',
            obj.paid_booth_receipt_number,
            obj.paid_booth_receipt_generated_at.strftime('%d/%m/%Y %H:%M') if obj.paid_booth_receipt_generated_at else 'N/A'
        )
    return format_html('<span style="color: #999; font-size: 11px;">No receipt</span>')

receipt_info.short_description = 'Receipt Info'



@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'order', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'title', 'short_bio']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['order', 'is_active']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'title', 'profile_image', 'slug')
        }),
        ('Biography', {
            'fields': ('short_bio', 'full_bio')
        }),
        ('Contact Information', {
            'fields': ('email', 'phone')
        }),
        ('Additional Information', {
            'fields': ('publications',)
        }),
        ('Settings', {
            'fields': ('order', 'is_active')
        }),
    )



from .models import Blog, BlogCategory

@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'author', 'is_published', 'is_featured', 'views_count', 'created_at']
    list_filter = ['is_published', 'is_featured', 'category', 'created_at']
    search_fields = ['title', 'excerpt', 'content']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['is_published', 'is_featured']
    readonly_fields = ['views_count', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'featured_image', 'excerpt')
        }),
        ('Content', {
            'fields': ('content',)
        }),
        ('Meta Information', {
            'fields': ('author', 'category', 'tags', 'meta_description')
        }),
        ('Publishing', {
            'fields': ('is_published', 'is_featured', 'published_at')
        }),
        ('Statistics', {
            'fields': ('views_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        # Auto-set author to current user if not set
        if not obj.author:
            obj.author = request.user
        super().save_model(request, obj, form, change)


from controlpanel.models import SentInvoice
from django.http import HttpResponse
from django.utils.html import format_html

@admin.register(SentInvoice)
class SentInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'name', 'email', 'amount_kes', 'sent_at', 'view_pdf']
    list_filter = ['sent_at', 'amount']
    search_fields = ['invoice_number', 'name', 'email', 'holder_id']
    readonly_fields = ['sent_at', 'pdf_file']
    ordering = ['-sent_at']

    def amount_kes(self, obj):
        return f"KES {obj.amount:,.0f}"
    amount_kes.short_description = "Amount"

    def view_pdf(self, obj):
        if obj.pdf_file:
            return format_html(
                '<a href="{}" target="_blank" class="button">View PDF</a>',
                obj.pdf_file.url
            )
        return "—"
    view_pdf.short_description = "PDF"
    view_pdf.allow_tags = True

 

# I'LL DISABLE LATER ON: ///

# admin.site.register(Order)
# admin.site.register(Ticket)
# admin.site.register(Event)

