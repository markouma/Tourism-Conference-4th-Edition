from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
import uuid, hashlib, qrcode
from datetime import timedelta
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError   

from io import BytesIO
from django.core.files import File

User = get_user_model()


def generate_token():
    return uuid.uuid4().hex

class Event(models.Model):
    name = models.CharField(max_length=200)
    poster = models.ImageField(upload_to='posters/')
    location = models.CharField(max_length=200)
    date = models.DateTimeField()
    description = models.TextField()

    EVENT_TYPES = (
        ('regular', 'Regular Event'),
        # ('conference', 'Conference'),
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='regular')

    def __str__(self):
        return self.name


class TicketCategory(models.Model):
    event = models.ForeignKey(Event, related_name='categories', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    available_tickets = models.PositiveIntegerField(default=0)

    def remaining_tickets(self):
        return self.available_tickets - self.tickets.count()

    def __str__(self):
        return f"{self.name} - {self.event.name}"


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    user_email = models.EmailField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    pesapal_url = models.TextField(blank=True, null=True)  
    created_at = models.DateTimeField(auto_now_add=True)
    pesapal_tracking_id = models.CharField(max_length=100, blank=True, null=True)
    checkout_request_id = models.CharField(max_length=100, null=True, blank=True)
    payment_status = models.CharField(max_length=50, default='pending')  # 'pending', 'success', 'failed'
    user_phone = models.CharField(max_length=20, blank=True, null=True)
    user_name  = models.CharField(max_length=100, blank=True, null=True)
    company    = models.CharField(max_length=100, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    age_range = models.CharField(max_length=50, blank=True, null=True)
    tshirt_size = models.CharField(max_length=50, blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    consent = models.BooleanField(default=False)
    referral_source = models.CharField(max_length=100, blank=True, null=True)
    attendee_photo = models.ImageField(upload_to='attendee_photos/', blank=True, null=True)
    kra_pin = models.CharField(max_length=20, null=True, blank=True, help_text="Customer's KRA PIN number")
    
    # Payment method field
    PAYMENT_METHOD_CHOICES = [
        ('mpesa', 'M-PESA'),
        ('pesapal', 'Pesapal (Card/Airtel)'),
        ('mtn', 'MTN Mobile Money'),
    ]
    payment_method = models.CharField(
        max_length=20, 
        choices=PAYMENT_METHOD_CHOICES, 
        null=True, 
        blank=True,
        help_text="Payment method used for this order"
    )

    def __str__(self):
        return f"Order {self.id}"


class ScanInstance(models.Model):
    """
    Represents a scanning checkpoint (like 'Main Entrance', 'VIP Gate', 'Workshop Hall').
    """
    name = models.CharField(max_length=100)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='scan_instances')
    description = models.TextField(blank=True, null=True, help_text="Optional description of this scan checkpoint")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('name', 'event')  # Same name can exist for different events
        ordering = ['event', 'name']

    def __str__(self):
        return f"{self.event.name} - {self.name}"

    @property
    def scan_count(self):
        """Get total number of scans for this instance"""
        return self.scan_logs.count()


class Ticket(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='tickets', blank=True, null=True)
    category = models.ForeignKey('TicketCategory', on_delete=models.CASCADE, null=True, blank=True, related_name='tickets')
    booth = models.ForeignKey('Booth', on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    created_at = models.DateTimeField(auto_now_add=True)

    ticket_number = models.CharField(max_length=200, unique=True, blank=True, null=True)
    guest_email = models.EmailField(null=True, blank=True)
    guest_name = models.CharField(max_length=100, null=True, blank=True)
    guest_phone = models.CharField(max_length=20, null=True, blank=True)
    attendee_photo = models.ImageField(upload_to='conference_photos/', null=True, blank=True)
    company_name = models.CharField(max_length=150, null=True, blank=True)
    designation = models.CharField(max_length=100, null=True, blank=True)
    industry = models.CharField(max_length=100, null=True, blank=True)
    industry_description = models.TextField(null=True, blank=True)
    kra_pin = models.CharField(max_length=20, null=True, blank=True, help_text="Customer's KRA PIN number")

    country = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    age_range = models.CharField(max_length=20, null=True, blank=True)
    tshirt_size = models.CharField(max_length=20, null=True, blank=True)

    consent_given = models.BooleanField(default=False)
    heard_about = models.CharField(max_length=100, null=True, blank=True)
    sector = models.CharField(max_length=100, null=True, blank=True)

    # staff + paid tags
    staff_application = models.ForeignKey('StaffApplication', on_delete=models.SET_NULL, null=True, blank=True)
    paid_application = models.ForeignKey('PaidApplication', on_delete=models.SET_NULL, null=True, blank=True)
    booth_number = models.CharField(max_length=20, null=True, blank=True)

    # Verification
    ticket_id = models.UUIDField(default=uuid.uuid4, editable=False)
    verification_hash = models.CharField(max_length=64, editable=False)
    qr_code = models.ImageField(upload_to='qrcodes/', blank=True)
    pdf_ticket = models.FileField(upload_to='tickets/', blank=True)

    # Legacy fields (still useful but less central)
    is_used = models.BooleanField(default=False)
    first_scanned_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Ticket {self.ticket_number or self.ticket_id}"

    def save(self, *args, **kwargs):
        if not self.verification_hash:
            self.generate_verification_hash()

        if not self.ticket_number:
            # Safe unique generator
            base_number = f"The 4th UG-KE Conference.#-{Ticket.objects.count() + 1:06d}"
            ticket_number = base_number
            counter = 1

            while Ticket.objects.filter(ticket_number=ticket_number).exists():
                ticket_number = f"{base_number}-{counter}"
                counter += 1

            self.ticket_number = ticket_number

        super().save(*args, **kwargs)

    def generate_verification_hash(self):
        secret_string = f"{self.ticket_id}{settings.SECRET_KEY}"
        self.verification_hash = hashlib.sha256(secret_string.encode()).hexdigest()

    # --- New scanning helpers ---
    def is_scanned_at_instance(self, scan_instance):
        """Check if ticket has been scanned at a specific instance (gate, event section, etc.)."""
        return self.scan_logs.filter(scan_instance=scan_instance).exists()

    def get_scan_log_for_instance(self, scan_instance):
        """Return scan log for a specific instance, or None."""
        return self.scan_logs.filter(scan_instance=scan_instance).first()

    def get_all_scan_history(self):
        """Get all scan logs ordered by scan time (latest first)."""
        return self.scan_logs.select_related('scan_instance', 'scanned_by').order_by('-scanned_at')

    def mark_scanned(self):
        """
        Legacy method. Updates is_used/first_scanned_at
        based on whether ANY scan exists.
        """
        if not self.first_scanned_at and self.scan_logs.exists():
            self.first_scanned_at = self.scan_logs.order_by('scanned_at').first().scanned_at
        self.is_used = self.scan_logs.exists()
        self.save()


class TicketScanLog(models.Model):
    """
    Logs each scan of a ticket at a specific instance.
    """
    ticket = models.ForeignKey(Ticket, related_name="scan_logs", on_delete=models.CASCADE)
    scan_instance = models.ForeignKey(ScanInstance, related_name="scan_logs", on_delete=models.CASCADE, null=True, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)
    scanned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('ticket', 'scan_instance')  # Prevents duplicate scans at same instance
        ordering = ['-scanned_at']
        verbose_name = 'Ticket Scan Log'
        verbose_name_plural = 'Ticket Scan Logs'

    def __str__(self):
        return f"{self.ticket} scanned at {self.scan_instance} on {self.scanned_at}"

class Booth(models.Model):
    event = models.ForeignKey('Event', related_name='booths', on_delete=models.CASCADE)
    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_booked = models.BooleanField(default=False)
    booked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    booked_at = models.DateTimeField(null=True, blank=True)
    reserved_until = models.DateTimeField(null=True, blank=True)
    pdf_ticket = models.FileField(upload_to='booth_tickets/', blank=True)
    qr_code = models.ImageField(upload_to='qrcodes/booths/', blank=True)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='booths')
    booth_qr_code = models.ImageField(upload_to='booth_qrcodes/', blank=True, null=True)
    public_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    public_qr_code = models.ImageField(upload_to='new_booth_QRs/', blank=True, null=True)
    
    @property
    def is_reserved(self):
        """Check if booth is currently reserved (has reserved_until in future)"""
        from django.utils import timezone
        if self.reserved_until:
            return self.reserved_until > timezone.now()
        return False
    
    def generate_public_qr(self):
        if not self.id or not self.public_token:
            return
        qr_data = f"{settings.SITE_URL}/review/booth/{self.public_token}/"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        qr_image.save(buffer, format='PNG')
        buffer.seek(0)
        filename = f'booth_{self.id}_public_qr.png'
        self.public_qr_code.save(filename, File(buffer), save=False)
        buffer.close()
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new or not self.public_qr_code:
            self.generate_booth_qr()  # Old QR
            self.generate_public_qr()  # New public QR
            super().save(update_fields=['public_qr_code'])
    
    # ===== MISSING METHODS - ADD THESE =====
    
    def reserve(self, user=None, order=None, minutes=10):
        """
        Reserve this booth temporarily for the specified duration.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        self.reserved_until = timezone.now() + timedelta(minutes=minutes)
        self.order = order
        if user and user.is_authenticated:
            self.booked_by = user
        self.save(update_fields=['reserved_until', 'order', 'booked_by'])
    
    def release_reservation(self):
        """
        Release the temporary reservation on this booth.
        Does NOT release permanent bookings (is_booked=True).
        """
        if not self.is_booked:
            self.reserved_until = None
            self.save(update_fields=['reserved_until'])
        
    def mark_as_booked(self, user=None):
        """
        Mark this booth as permanently booked (after successful payment).
        """
        from django.utils import timezone
        
        self.is_booked = True
        self.booked_at = timezone.now()
        self.reserved_until = None
        
        # Update booked_by if user provided
        if user and not self.booked_by:
            self.booked_by = user
        
        self.save(update_fields=['is_booked', 'booked_at', 'reserved_until', 'booked_by'])

class BoothReview(models.Model):
    booth = models.ForeignKey('Booth', on_delete=models.CASCADE)
    reviewer = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    content = models.TextField()
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    name = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['booth', 'reviewer']),
            models.Index(fields=['booth', 'ip_address']),
            models.Index(fields=['booth', 'email'], name='booth_email_idx'),
        ]

    def clean(self):
        if not self.reviewer and not self.email:
            raise ValidationError("Either a registered user or an email is required.")
        if self.reviewer and (self.name or self.email or self.phone_number):
            raise ValidationError("Registered users cannot provide guest name, email, or phone number.")
        if not self.content.strip():
            raise ValidationError("Review content cannot be empty.")

    def __str__(self):
        return f"Review for {self.booth.name} by {self.reviewer or self.email or 'Anonymous'}"

class BoothVisit(models.Model):
    booth = models.ForeignKey(Booth, on_delete=models.CASCADE)
    visitor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    guest_name = models.CharField(max_length=150, null=True, blank=True)
    guest_email = models.EmailField(null=True, blank=True)
    guest_phone = models.CharField(max_length=20, null=True, blank=True)
    guest_photo = models.ImageField(upload_to='visitor_photos/', null=True, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['booth', 'visitor']),
            models.Index(fields=['booth', 'guest_email']),
        ]

    def clean(self):
        if self.visitor:
            if BoothVisit.objects.filter(booth=self.booth, visitor=self.visitor).exclude(pk=self.pk).exists():
                raise ValidationError("This user has already visited this booth.")
        elif self.guest_email:
            if BoothVisit.objects.filter(
                booth=self.booth, visitor__isnull=True, guest_email=self.guest_email
            ).exclude(pk=self.pk).exists():
                raise ValidationError("This guest has already visited this booth.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.visitor:
            return f"{self.visitor.get_full_name() or self.visitor.username} visited {self.booth.name}"
        else:
            return f"{self.guest_name or self.guest_email} visited {self.booth.name}"

class BoothReviewHistory(models.Model):
    review = models.ForeignKey(BoothReview, on_delete=models.CASCADE, related_name='history')
    rating = models.PositiveSmallIntegerField()
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

# Signal receiver to link booth visits to user after registration
@receiver(post_save, sender=User)
def link_booth_visits_to_user(sender, instance, created, **kwargs):
    if created:
        BoothVisit.objects.filter(guest_email=instance.email, visitor__isnull=True).update(visitor=instance)

  


class StaffApplication(models.Model):
    ROLE_CHOICES = [
        ('media', 'Media'),
        ('security', 'Security'),
        ('service', 'Service Crew'),
        ('usher', 'Usher'),
        ('production', 'Production Crew'),
        ('health', 'Health Emergency'),
        ('official', 'Official'),
        ('moderator', 'Moderator'),
        ('rapporteur', 'Rapporteur'),
        ('panelist', 'Panelist'),
        ('events-agency', 'Events Agency'),
        ('organizing-committee', 'Organizing Committee')
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    AGE_RANGE_CHOICES = [
        ('18-25', '18-25'),
        ('26-30', '26-30'),
        ('31-40', '31-40'),
        ('41-50', '41-50'),
        ('51+', '51+'),
    ]

    TSHIRT_CHOICES = [
        ('Small', 'Small'),
        ('Medium', 'Medium'),
        ('Large', 'Large'),
        ('XL', 'XL'),
        ('XXL', 'XXL'),
        ('XXXL', 'XXXL'),
    ]
    
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    company = models.CharField(max_length=150, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    photo = models.ImageField(upload_to='staff_photos/', blank=True, null=True)
    media_number = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    tag_sent = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='staff_applications', default=5)   
    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    age_range = models.CharField(max_length=10, choices=AGE_RANGE_CHOICES, blank=True, null=True)
    tshirt_size = models.CharField(max_length=10, choices=TSHIRT_CHOICES, blank=True, null=True)
    referral_source = models.CharField(max_length=100, blank=True, null=True)
    consent = models.BooleanField(default=False)  # Required

    def __str__(self):
        return f"{self.full_name} - {self.role} ({self.status})"


class PaidApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    full_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=20)  # reuse same roles if relevant
    company = models.CharField(max_length=150, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    photo = models.ImageField(upload_to='paid_photos/', blank=True, null=True)

    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    age_range = models.CharField(max_length=10, choices=StaffApplication.AGE_RANGE_CHOICES, blank=True, null=True)
    tshirt_size = models.CharField(max_length=10, choices=StaffApplication.TSHIRT_CHOICES, blank=True, null=True)
    referral_source = models.CharField(max_length=100, blank=True, null=True)

    consent = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    tag_sent = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='paid_applications')
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mpesa_message = models.TextField(null=True, blank=True)

    # Payment-specific
    mpesa_code = models.CharField(max_length=20, unique=True)  # must be unique

    def __str__(self):
        return f"{self.full_name} ({self.email}) - {self.status}"


class BoothApplication(models.Model):
    booth_number = models.CharField(max_length=10)
    company = models.CharField(max_length=150)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='booth_applications')
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='pending')
    tag_sent = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('booth_number', 'company', 'event')

    def __str__(self):
        return f"{self.company} - Booth {self.booth_number} ({self.status})"


class BoothRepresentative(models.Model):
    AGE_RANGE_CHOICES = [
        ('18-25', '18-25'),
        ('26-35', '26-35'),
        ('36-45', '36-45'),
        ('46+', '46+'),
    ]
    TSHIRT_CHOICES = [
        ('S','S'),('M','M'),('L','L'),('XL','XL'),('XXL','XXL')
    ]

    application = models.ForeignKey(BoothApplication, on_delete=models.CASCADE, related_name='representatives')
    name = models.CharField(max_length=100)
    age_range = models.CharField(max_length=10, choices=AGE_RANGE_CHOICES)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    industry = models.CharField(max_length=100)
    tshirt_size = models.CharField(max_length=10, choices=TSHIRT_CHOICES)
    photo = models.ImageField(upload_to='booth_photos/')
    consent = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.application.company})"


class PaidBoothApplication(models.Model):
    """
    This model stores booth representative applications
    Think of it as a "pending ticket request" that admins need to approve
    """
    
    # Application Status Choices
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),  
        ('rejected', 'Rejected'),
    ]
    
    # Basic Info (from the form)
    booth_number = models.CharField(max_length=20)
    payment_message = models.TextField(help_text="Payment confirmation code or message")
    
    # Personal Details
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    profile_image = models.ImageField(upload_to='booth_applications/', blank=True, null=True)

    # Professional Details
    company = models.CharField(max_length=150)
    title_designation = models.CharField(max_length=100)
    kra_pin = models.CharField(max_length=20, null=True, blank=True, help_text="Customer's KRA PIN number")
    
    # Location
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    industry = models.CharField(max_length=100)
    
    # Consent
    consent_given = models.BooleanField(default=False)
    
    # Application Management
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(auto_now_add=True)  # When they applied
    reviewed_at = models.DateTimeField(null=True, blank=True)  # When admin reviewed
    
    # Admin Response
    admin_message = models.TextField(blank=True, null=True, help_text="Custom message for approval/rejection")
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications')
    
    # Link to generated ticket (only when approved)
    ticket = models.OneToOneField(Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name='booth_application')
    
    # NEW RECEIPT TRACKING FIELDS
    paid_booth_receipt_number = models.CharField(max_length=50, null=True, blank=True, unique=True)
    paid_booth_transaction_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    paid_booth_receipt_generated_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-applied_at']  # Show newest applications first
        
    def __str__(self):
        return f"Booth {self.booth_number} - {self.name} ({self.status})"
    
    def approve(self, admin_user, message=""):
        """
        Helper method to approve this application
        This will be called when admin clicks 'approve'
        """
        self.status = 'approved'
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.admin_message = message
        self.save()
        
    def reject(self, admin_user, message=""):
        """
        Helper method to reject this application  
        This will be called when admin clicks 'reject'
        """
        self.status = 'rejected'
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.admin_message = message
        self.save()
    
    def generate_paid_booth_receipt_number(self):
        """Generate unique incremental receipt number"""
        if self.paid_booth_receipt_number:
            return self.paid_booth_receipt_number
            
        # Get the last receipt number
        last_application = PaidBoothApplication.objects.filter(
            paid_booth_receipt_number__isnull=False
        ).order_by('-id').first()
        
        if last_application and last_application.paid_booth_receipt_number:
            # Extract number from format PAID-BOOTH-#XX
            import re
            match = re.search(r'PAID-BOOTH-#(\d+)', last_application.paid_booth_receipt_number)
            if match:
                last_num = int(match.group(1))
                new_num = last_num + 1
            else:
                new_num = 1
        else:
            new_num = 1
        
        receipt_number = f"PAID-BOOTH-#{new_num:02d}"
        self.paid_booth_receipt_number = receipt_number
        self.save()
        return receipt_number
    
    def generate_paid_booth_transaction_id(self):
        """Generate unique transaction ID"""
        if self.paid_booth_transaction_id:
            return self.paid_booth_transaction_id
            
        import uuid
        from datetime import datetime
        
        # Format: PB20251001-UUID-short
        date_part = datetime.now().strftime('%Y%m%d')
        uuid_part = str(uuid.uuid4()).replace('-', '')[:8].upper()
        transaction_id = f"PB{date_part}-{uuid_part}"
        
        self.paid_booth_transaction_id = transaction_id
        self.save()
        return transaction_id



class PPVEvent(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    mux_playback_id = models.CharField(max_length=100)  # from Mux
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    def __str__(self):
        return f"PPV for {self.event.name}"


class PPVAccessToken(models.Model):
    token = models.CharField(max_length=32, unique=True, default=generate_token)
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    ppv_event = models.ForeignKey(PPVEvent, on_delete=models.CASCADE)
    redeemed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return self.order.is_paid and not self.redeemed



from django.utils.text import slugify

class Speaker(models.Model):
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=300, help_text="Job title/position")
    profile_image = models.ImageField(upload_to='speakers/', blank=True, null=True)
    short_bio = models.TextField(help_text="Brief description for listing page", blank=True)
    full_bio = models.TextField(help_text="Full biography", blank=True)
    
    # Additional fields
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    publications = models.TextField(blank=True, help_text="Publications, conferences, presentations")
    
    # Meta fields
    slug = models.SlugField(unique=True, blank=True)
    order = models.IntegerField(default=0, help_text="Display order (lower numbers first)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Speaker'
        verbose_name_plural = 'Speakers'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)




class BlogCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    
    class Meta:
        verbose_name_plural = "Blog Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Blog(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(unique=True, blank=True)
    featured_image = models.ImageField(upload_to='blogs/', blank=True, null=True)
    excerpt = models.TextField(max_length=500, help_text="Brief description for listing page")
    content = models.TextField(help_text="Full blog content")
    
    # Meta info
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(BlogCategory, on_delete=models.SET_NULL, null=True, blank=True)
    tags = models.CharField(max_length=300, blank=True, help_text="Comma-separated tags")
    
    # SEO
    meta_description = models.CharField(max_length=160, blank=True)
    
    # Settings
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, help_text="Show on homepage/featured section")
    views_count = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)
    
    def get_tags_list(self):
        """Convert comma-separated tags to list"""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',')]
        return []
    
    def increment_views(self):
        """Increment view count"""
        self.views_count += 1
        self.save(update_fields=['views_count'])



from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator

class DocumentCounter(models.Model):
    """Manages sequential numbering for invoices and receipts"""
    year = models.IntegerField(unique=True)
    invoice_counter = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    receipt_counter = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    
    class Meta:
        verbose_name = "Document Counter"
        verbose_name_plural = "Document Counters"
    
    def __str__(self):
        return f"Counters for {self.year}"
    
    @classmethod
    def get_next_number(cls, document_type):
        """
        Get next sequential number for invoice or receipt
        document_type: 'invoice' or 'receipt'
        Returns: formatted string like 'INV-2025-0001' or 'REC-2025-0001'
        """
        current_year = timezone.now().year
        counter, created = cls.objects.get_or_create(year=current_year)
        
        if document_type == 'invoice':
            counter.invoice_counter += 1
            counter.save()
            number = f"INV-{current_year}-{counter.invoice_counter:04d}"
        elif document_type == 'receipt':
            counter.receipt_counter += 1
            counter.save()
            number = f"REC-{current_year}-{counter.receipt_counter:04d}"
        else:
            raise ValueError("document_type must be 'invoice' or 'receipt'")
        
        return number


class InvoiceReceipt(models.Model):
    """Stores generated invoices and receipts for tickets"""
    
    DOCUMENT_TYPES = (
        ('invoice', 'Invoice'),
        ('receipt', 'Receipt'),
    )
    
    ticket = models.ForeignKey('Ticket', on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=10, choices=DOCUMENT_TYPES)
    document_number = models.CharField(max_length=50, unique=True, db_index=True)
    
    # PDF storage
    pdf_file = models.FileField(upload_to='invoices/', blank=True, null=True)
    
    # Email tracking
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_to_email = models.EmailField()
    sent_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    last_sent_at = models.DateTimeField(null=True, blank=True)
    
    # Customer details (cached for historical record)
    company_name = models.CharField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=50)
    customer_email = models.EmailField()
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Invoice/Receipt"
        verbose_name_plural = "Invoices/Receipts"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_type', 'ticket']),
            models.Index(fields=['document_number']),
        ]
    
    def __str__(self):
        return f"{self.document_number} - {self.customer_name}"
    
    def mark_as_sent(self):
        """Mark document as sent and increment counter"""
        from django.utils import timezone
        self.sent_count += 1
        self.last_sent_at = timezone.now()
        if self.sent_count == 1:
            self.sent_at = self.last_sent_at
        self.save(update_fields=['sent_count', 'last_sent_at', 'sent_at'])