import os, qrcode, base64, hashlib
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponseForbidden, Http404
from django.contrib import messages
from io import BytesIO
from django.conf import settings
from django.core.files import File
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.urls import reverse
from django.templatetags.static import static
from pathlib import Path
from tourismconference.pdf import HTML
from django.core.files.storage import default_storage

from django.core.signing import Signer, TimestampSigner
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.models import Group
from .models import Order, Ticket, Booth
from .forms import DelegateForm, DelegateFormSet
from django.db import transaction
from django.core.signing import BadSignature, SignatureExpired
from decimal import Decimal
from datetime import datetime
from django.core.files.base import ContentFile

def generate_ticket_pdf(request, ticket, user_details, qr_code_path, attendee_photo_path=None, extra_context=None):
    try:
        # Debug output
        print(f"🔍 PDF Gen - attendee_photo_path: {attendee_photo_path}")
        print(f"🔍 PDF Gen - path exists: {os.path.exists(attendee_photo_path) if attendee_photo_path else False}")
        
        ticket_dir = os.path.join(settings.MEDIA_ROOT, 'tickets')
        os.makedirs(ticket_dir, exist_ok=True)

        pdf_filename = f"ticket_{ticket.id}_4th_UG-KE_conference.pdf"
        pdf_full_path = os.path.join(ticket_dir, pdf_filename)

        logo_path = os.path.join(settings.STATIC_ROOT, 'assets/img/logo.jpg')
        logo_nobg_path = os.path.join(settings.STATIC_ROOT, 'assets/img/logo_nobg.png')
        tag_path = os.path.join(settings.STATIC_ROOT, 'assets/img/tag.jpg')

        # ✅ Check for valid QR code path before using it
        if not qr_code_path:
            raise ValueError(f"❌ QR code path not provided for Ticket {ticket.id}")

        qr_full_path = os.path.join(settings.MEDIA_ROOT, qr_code_path)

        if not os.path.exists(qr_full_path):
            raise FileNotFoundError(f"❌ QR code image not found at {qr_full_path}")

        # 🧍‍♂️ Handle attendee photo path
        if attendee_photo_path and not attendee_photo_path.startswith(str(settings.MEDIA_ROOT)):
            attendee_photo_path = os.path.join(settings.MEDIA_ROOT, attendee_photo_path)

        # 🖼️ Get event poster - CREATE A PROPER FALLBACK
        event = ticket.category.event if ticket.category and ticket.category.event else None
        
        # Use a fallback that actually exists
        default_banner_path = os.path.join(settings.STATIC_ROOT, 'assets/img/logo.jpg')  # Use logo as fallback
        
        # Event banner
        poster_b64 = None
        if event and event.poster and os.path.exists(event.poster.path):
            poster_b64 = image_to_base64(event.poster.path)
        elif os.path.exists(default_banner_path):
            poster_b64 = image_to_base64(default_banner_path)
        else:
            print(f"⚠️ No event banner available for ticket {ticket.id}")
            poster_b64 = ""  # Empty string instead of broken image

        # Attendee photo
        attendee_b64 = None
        if attendee_photo_path and os.path.exists(attendee_photo_path):
            print(f"✅ Using attendee photo: {attendee_photo_path}")
            attendee_b64 = image_to_base64(attendee_photo_path)
        else:
            print(f"⚠️ No attendee photo available for ticket {ticket.id}")
            # Option 1: Use a default avatar if you have one
            default_avatar_path = os.path.join(settings.STATIC_ROOT, 'assets/img/default_avatar.png')
            if os.path.exists(default_avatar_path):
                attendee_b64 = image_to_base64(default_avatar_path)
            else:
                # Option 2: Use empty string (template should handle this)
                attendee_b64 = ""

        context = {
            'order': ticket.order,
            'ticket': ticket,
            'category': ticket.category,
            'event': event,
            'user_details': user_details,
            'attendee_photo': attendee_b64,
            'logo': image_to_base64(logo_path),
            'logo_nobg': image_to_base64(logo_nobg_path),
            'tag': image_to_base64(tag_path),
            'qr_code': image_to_base64(qr_full_path),
            'event_banner': poster_b64,
        }
        
        if extra_context:
            context.update(extra_context)

        html_string = render_to_string(
            'events/boothrep_ticket.html' if ticket.category and ticket.category.name == "Booth Representative"        
            else 'events/paid_exhibitor_ticket.html' if ticket.category and ticket.category.name == "Paid Booth Representative"
            else 'events/exhibitor_ticket.html' if ticket.order and ticket.order.booths.exists()
            else 'events/staff_ticket.html' if ticket.staff_application
            else 'events/ticket.html',
            context
        )

        html_temp = os.path.join(ticket_dir, f"ticket_{ticket.id}.html")
        Path(html_temp).write_text(html_string, encoding='utf-8')

        HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf(pdf_full_path)

        return os.path.join('tickets', pdf_filename)

    except Exception as e:
        print(f"🔥 WeasyPrint PDF Generation Failed: {e}")
        raise




def generate_qr_code(ticket):
    try:
        # 🔍 Get the event ID safely from either order or staff_application
        if ticket.order and ticket.order.event:
            event_id = ticket.order.event.id
        elif ticket.staff_application and ticket.staff_application.event:
            event_id = ticket.staff_application.event.id
        elif ticket.paid_application and ticket.paid_application.event:
            event_id = ticket.paid_application.event.id
        elif ticket.category and ticket.category.event:
            event_id = ticket.category.event.id
        else:
            raise ValueError(f"❌ Cannot generate QR — Ticket {ticket.id} has no attached event")


        # ⚠️ Must match scanning logic!
        verification_data = f"ticket:{ticket.id}|event:{event_id}"

        # 🧠 Create QR code
        qr = qrcode.make(verification_data)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
        buffer.seek(0)

        # 💾 Save to model
        qr_filename = f"{ticket.ticket_id}.png"
        ticket.qr_code.save(name=qr_filename, content=File(buffer), save=True)

        # ✅ Return the relative path for use in PDF generation
        return ticket.qr_code.name

    except Exception as e:
        print(f"🔥 QR Generation Error: {str(e)}")
        return None


def image_to_base64(path):
    try:
        with open(path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
            ext = os.path.splitext(path)[1][1:]  # e.g., 'png', 'jpg'
            return f"data:image/{ext};base64,{encoded}"
    except Exception as e:
        print(f"⚠️ Failed to encode image at {path}: {e}")
        return ""


def send_ticket_email(email, guest_name, pdf_path):
    signup_url = generate_signup_link(email)

    subject = "Your Tag"
    message = f"""
    Dear {guest_name},

    Hi, attached is your conference tag. See you at the 4th UG-KE Coast Tourism Conference 2025.

    🎟 Want to save your ticket and manage future ones?

     Create your free account here: {signup_url}
    """

    email_msg = EmailMessage(subject, message.strip(), to=[email],    bcc=[
            "coasttourismconference@gmail.com",
            "halloo@thetourismconference.org",
        ])
    email_msg.attach_file(pdf_path)
    email_msg.send()


def generate_payment_receipt_pdf(request, order, booths, user_details):
    """
    Generate payment receipt PDF for booth bookings
    """
    try:
        # Create receipts directory
        receipt_dir = os.path.join(settings.MEDIA_ROOT, 'receipts')
        os.makedirs(receipt_dir, exist_ok=True)

        pdf_filename = f"receipt_{order.id}_booth_booking.pdf"
        pdf_full_path = os.path.join(receipt_dir, pdf_filename)

        # Get logo
        logo_path = os.path.join(settings.STATIC_ROOT, 'assets/img/logo.jpg')
        
        # Calculate amounts
        subtotal = sum([booth.price for booth in booths])
        vat_amount = subtotal * Decimal("0.16")  # 16% VAT
        total_amount = subtotal + vat_amount

        # Payment method mapping
        payment_method_display = {
            'mpesa': 'M-PESA',
            'pesapal': 'Pesapal (Card/Airtel)',
            'mtn': 'MTN Mobile Money'
        }.get(order.payment_method, 'Unknown')

        context = {
            'order': order,
            'booths': booths,
            'user_details': user_details,
            'subtotal': subtotal,
            'vat_amount': vat_amount,
            'total_amount': total_amount,
            'payment_method': payment_method_display,
            'event': order.event,
            'logo': image_to_base64(logo_path) if os.path.exists(logo_path) else "",
        }

        html_string = render_to_string('events/payment_receipt.html', context)
        
        # Save temporary HTML file for debugging
        html_temp = os.path.join(receipt_dir, f"receipt_{order.id}.html")
        Path(html_temp).write_text(html_string, encoding='utf-8')

        # Generate PDF
        HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf(pdf_full_path)

        return os.path.join('receipts', pdf_filename)

    except Exception as e:
        print(f"Receipt PDF Generation Failed: {e}")
        raise




def send_payment_receipt_email(email, customer_name, order, pdf_path):
    """
    Send payment receipt email - separate from ticket email
    """
    try:
        # Format booth names
        booth_names = ", ".join([f"Booth {booth.name}" for booth in order.booths.all()])
        
        # Use first 8 characters of UUID for receipt number (or full UUID)
        receipt_number = str(order.id)[:8].upper()  # Short version
        # Or use full UUID: receipt_number = str(order.id)
        
        subject = f"Payment Receipt - Booth Booking #{receipt_number}"
        
        message = f"""
Dear {customer_name},

Thank you for your booth booking payment!

ORDER DETAILS:
- Receipt Number: #{receipt_number}
- Booth(s): {booth_names}
- Total Amount: Ksh {order.total_amount:,}
- Payment Date: {order.created_at.strftime('%d/%m/%Y')}

Your payment receipt is attached to this email for your records.

IMPORTANT: Your conference tickets will be sent in a separate email shortly.

For any questions about your booking, please contact:
- Email: accounts@buzzafrique.co.ke
- Phone: +254 722 274707

Thank you for participating in the 4th UG-KE Coast Tourism Conference!

Best regards,
BUZZ AFRIQUE LIMITED
"""

        email_msg = EmailMessage(
            subject=subject,
            body=message.strip(),
            to=[email],
            cc=[
                "accounts@buzzafrique.co.ke",
                "coasttourismconference@gmail.com",
            ]
        )
        
        # Attach receipt PDF
        email_msg.attach_file(os.path.join(settings.MEDIA_ROOT, pdf_path))
        email_msg.send()
        
        print(f"Payment receipt email sent to {email}")
        
    except Exception as e:
        print(f"Failed to send receipt email to {email}: {e}")
        raise



def process_booth_payment_success(order, request=None):
    """
    Handle successful booth payment - generate both receipt and tickets
    """
    try:
        # Get booth attendees from session
        booth_attendees = request.session.get('booth_attendees', []) if request else []
        
        # Get booked booths
        booths = order.booths.all()
        
        if not booths.exists():
            raise ValueError("No booths found for this order")

        # Mark booths as booked
        for booth in booths:
            booth.mark_as_booked(user=order.user if order.user else None)

        # Mark order as paid
        order.is_paid = True
        order.payment_status = 'completed'
        order.save()

        # Generate and send payment receipt
        user_details = {
            'name': order.user_name,
            'email': order.user_email,
            'phone': order.user_phone,
            'kra_pin': order.kra_pin,
        }
        
        # Generate receipt PDF
        receipt_pdf_path = generate_payment_receipt_pdf(request, order, booths, user_details)
        
        # Send receipt email
        send_payment_receipt_email(
            email=order.user_email,
            customer_name=order.user_name,
            order=order,
            pdf_path=receipt_pdf_path
        )

        # Generate tickets for each attendee
        for i, attendee_data in enumerate(booth_attendees):
            try:
                # Get the booth for this attendee
                booth_id = attendee_data.get('booth_id')
                booth = booths.filter(id=booth_id).first() if booth_id else booths.first()
                
                if not booth:
                    print(f"Warning: No booth found for attendee {i}")
                    continue

                # Create ticket
                ticket = Ticket.objects.create(
                    order=order,
                    category_id=attendee_data.get('category_id'),
                    booth=booth,
                    guest_name=attendee_data['name'],
                    guest_email=attendee_data['email'],
                    guest_phone=attendee_data.get('phone'),
                    company_name=attendee_data.get('company'),
                    designation=attendee_data.get('designation'),
                    industry=attendee_data.get('industry'),
                    industry_description=attendee_data.get('industry_description', ''),
                    country=attendee_data.get('country'),
                    city=attendee_data.get('city'),
                    age_range=attendee_data.get('age_range'),
                    tshirt_size=attendee_data.get('tshirt_size'),
                    heard_about=attendee_data.get('referral_source'),
                    consent_given=attendee_data.get('consent', False),
                    booth_number=booth.name,
                    kra_pin=attendee_data.get('kra_pin', ''),  
                )

                # Handle attendee photo
                if attendee_data.get('photo'):
                    photo_path = attendee_data['photo']
                    try:
                        with default_storage.open(photo_path, 'rb') as f:
                            ticket.attendee_photo.save(
                                os.path.basename(photo_path),
                                File(f),
                                save=False
                            )
                        ticket.save()
                    except Exception as photo_error:
                        print(f"Photo error for ticket {ticket.id}: {photo_error}")

                # Generate QR code and PDF ticket
                qr_code_path = generate_qr_code(ticket)
                
                if qr_code_path:
                    # Generate ticket PDF
                    attendee_photo_path = None
                    if ticket.attendee_photo:
                        attendee_photo_path = ticket.attendee_photo.path

                    ticket_user_details = {
                        'name': ticket.guest_name,
                        'email': ticket.guest_email,
                        'phone': ticket.guest_phone,
                        'company': ticket.company_name,
                        'designation': ticket.designation,
                        'kra_pin': ticket.kra_pin,
                    }

                    pdf_path = generate_ticket_pdf(
                        request, ticket, ticket_user_details, qr_code_path, attendee_photo_path
                    )
                    
                    if pdf_path:
                        ticket.pdf_ticket = pdf_path
                        ticket.save()

                        # Send ticket email
                        send_ticket_email(
                            ticket.guest_email,
                            ticket.guest_name,
                            os.path.join(settings.MEDIA_ROOT, pdf_path)
                        )

            except Exception as ticket_error:
                print(f"Error creating ticket for attendee {i}: {ticket_error}")
                continue

        # Clear session data
        if request:
            request.session.pop('booth_attendees', None)
            request.session.pop('order_id', None)

        print(f"Booth payment processing completed for order {order.id}")
        return True

    except Exception as e:
        print(f"Error processing booth payment success: {e}")
        raise

def send_exhibitor_ticket_email(email, guest_name, company_name, booth_number, pdf_path):
    """
    Send HTML email to Exhibitor with ticket attachment and link to register 2 reps.
    """
    register_url = f"https://shorturl.at/JpSuY"

    subject = f"Tag for Booth {booth_number} and Reps Registration"

    html_message = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #007bff;">Dear {guest_name},</h2>

       Attached is your tag (PDF) for the 4th UG-KE Coast Tourism Conference.

        <p><strong>Booth Details:</strong><br>
        Company: {company_name}<br>
        Booth Number: {booth_number}</p>

 
        <p>✅ <strong>Important:</strong> Each booth may have up to <strong>2 representatives</strong>. 
        Make sure to register your reps by clicking the button below:</p>

        <p style="text-align: center; margin: 30px 0;">
          <a href="{register_url}" target="_blank"
             style="display: inline-block; padding: 12px 20px; color: #fff; background-color: #007bff;
                    text-decoration: none; border-radius: 5px; font-weight: bold;">
             Register Your 2 Reps
          </a>
        </p>

        <p>We look forward to seeing you at the conference and showcasing your company!</p>

        <p>Regards,<br>
        Conference Secretariat</p>
      </body>
    </html>
    """

    email_msg = EmailMessage(
        subject=subject,
        body=html_message,
        to=[email],
        bcc=[
            "coasttourismconference@gmail.com",
            "halloo@thetourismconference.org",
        ],
    )
    email_msg.content_subtype = "html"
    email_msg.attach_file(pdf_path)
    email_msg.send()


def send_reject_email1(email, guest_name):
    subject = "Your Application Result"
    message = f"""
    <p>Dear {guest_name},</p>

    <p>Your application has been rejected because you don’t qualify for this category. 
    Applications for this category are strictly for invited officials, invited participants, 
    contracted suppliers & accredited journalists.</p>

    <p>Please purchase a ticket as a DELEGATE to secure your participation:  
    <a style="color: white; background: #007bff; padding: 8px 12px; 
                      text-decoration: none; border-radius: 5px;" href="https://shorturl.at/UiAak" target="_blank"> Click here</a></p>

    <p>Regards,<br>
    Conference Secretariat.</p>
    """

    email_msg = EmailMessage(
        subject=subject,
        body=message.strip(),
        to=[email],
        bcc=[
            "coasttourismconference@gmail.com",
            "halloo@thetourismconference.org",
        ],
    )
    email_msg.content_subtype = "html"   
    email_msg.send()


def send_reject_email2(email, guest_name, mpesa_code):
    subject = "Your Application Result"
    message = f"""
    <html>
      <body>
        <p>Dear {guest_name},</p>

        <p>
          Your Mpesa code <b>{mpesa_code}</b> did not match any of our records.<br>
          Therefore, your application to serve at the 
          <strong>4th UG-KE Coast Tourism Conference 2025</strong> has been rejected.
        </p>

        <p>Click
            <a href="https://shorturl.at/yEAXf" 
               style="color: white; background: #007bff; padding: 8px 12px; 
                      text-decoration: none; border-radius: 5px;">
                here 
          </a> to purchase your delegate ticket.
        </p>

        <p>Regards,<br>Conference Secretariat</p>
      </body>
    </html>
    """

    email_msg = EmailMessage(subject, message, to=[email])
    email_msg.content_subtype = "html"    
    email_msg.send()


signer = TimestampSigner()

def generate_signup_link(email):
    signed_email = signer.sign(email)
    return f"{settings.BASE_URL}signup/?token={signed_email}"


def assign_user_to_group(user, group_name):
    group, created = Group.objects.get_or_create(name=group_name)
    user.groups.clear()  # remove any old group to avoid confusion
    user.groups.add(group)


def send_boothrep_ticket_email(email, rep_name, pdf_path):
    subject = "Your Booth Representative Tag"
    message = f"""
    Dear {rep_name},

    Congratulations 🎉! Your application as a Booth Representative has been approved.

    Please find attached your official tag for the
    4th UG-KE Coast Tourism Conference 2025.

    ✅ Remember:
    - Carry this tag (printed or digital) with you.
    - Bring a valid ID for verification at the gate.
    - Wear your tag visibly throughout the event.

    We look forward to seeing you represent your company at the conference!

    Regards,  
    Conference Secretariat
    """

    email_msg = EmailMessage(
        subject,
        message.strip(),
        to=[email],
        bcc=[
            "coasttourismconference@gmail.com",
            "halloo@thetourismconference.org",
        ],
    )
    email_msg.attach_file(pdf_path)
    email_msg.send()


def send_boothrep_reject_email(email, name):
    subject = "Booth Representative Application Status"
    body = f"""
    Hi {name},

    Thank you for your interest in being a booth representative. 
    Unfortunately, your application was not successful this time.

    We appreciate the effort you put into applying and encourage you to 
    stay connected for future opportunities.

    Regards,  
    Event Team
    """
    msg = EmailMessage(subject, body, to=[email])
    msg.send()





def generate_paid_booth_receipt_pdf(application):
    """
    Generate PDF receipt from HTML template for paid booth applications - Using weasyprint
    """
    try:
        # Generate receipt and transaction IDs if not exists
        receipt_number = application.generate_paid_booth_receipt_number()
        transaction_id = application.generate_paid_booth_transaction_id()
        
        # Get absolute path to logo
        buzz_logo_path = os.path.join(settings.STATIC_ROOT, 'assets/img/buzz.jpeg')
        # Alternative if STATIC_ROOT is not set:
        # buzz_logo_path = os.path.join(settings.BASE_DIR, 'static/assets/img/buzz.jpeg')
        
        # Prepare context data for the receipt
        context = {
            'receipt_number': receipt_number,
            'date': datetime.now().strftime('%d/%m/%Y'),
            'transaction_id': transaction_id,
            
            # Logo path for WeasyPrint
            'buzz_logo_path': buzz_logo_path,
            
            # Customer details from application
            'customer_name': application.name,
            'customer_email': application.email,
            'customer_phone': application.phone_number,
            'customer_company': application.company,
            'customer_pin': application.kra_pin or 'N/A',
            
            # Booth details
            'booth_number': application.booth_number,
            'booth_price': 50000,
            'vat_amount': 8000,
            'total_amount': 58000,
            
            # Company details (your company)
            'company_name': 'BUZZ AFRIQUE LIMITED',
            'company_address': 'P.O Box 81039-80100',
            'company_city': 'Mombasa',
            'company_phone': '+254 722 274707',
            'company_email': 'accounts@buzzafrique.co.ke',
            'company_pin': 'P051185889S',
        }
        
        # Render HTML template
        html_content = render_to_string('events/paid_booth_receipt.html', context)
        
        # Generate PDF using weasyprint with proper base_url
        # Use request.build_absolute_uri if available, or construct base_url
        base_url = f"{settings.STATIC_URL}"
        html_doc = HTML(string=html_content)
        
        # Create file path
        filename = f"paid_booth_receipt_{receipt_number.replace('#', '').replace('-', '_')}.pdf"
        file_path = os.path.join('receipts/paid_booth/', filename)
        
        # Create directory if it doesn't exist
        full_dir = os.path.join(settings.MEDIA_ROOT, 'receipts/paid_booth/')
        os.makedirs(full_dir, exist_ok=True)
        
        # Save PDF file
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        html_doc.write_pdf(full_path)
        
        # Update application with timestamp
        application.paid_booth_receipt_generated_at = datetime.now()
        application.save()
        
        return file_path
        
    except Exception as e:
        print(f"Error generating paid booth receipt PDF: {str(e)}")
        return None



def get_paid_booth_receipt_context(application):
    """
    Get context data for paid booth receipt email
    """
    return {
        'customer_name': application.name,
        'booth_number': application.booth_number,
        'company_name': application.company,
        'receipt_number': application.paid_booth_receipt_number,
        'total_amount': 'Ksh 58,000'
    }
import os
from datetime import datetime
from django.conf import settings
from django.template.loader import render_to_string
from tourismconference.pdf import HTML
from .models import InvoiceReceipt, DocumentCounter


def generate_invoice_receipt_pdf(ticket, document_type):
    """
    Generate PDF invoice or receipt for a ticket
    document_type: 'invoice' or 'receipt'
    Returns: InvoiceReceipt object or None
    """
    try:
        # Check if document already exists for this ticket
        existing_doc = InvoiceReceipt.objects.filter(
            ticket=ticket, 
            document_type=document_type
        ).first()
        
        if existing_doc:
            # Return existing document (will just resend)
            return existing_doc
        
        # Generate new document number
        document_number = DocumentCounter.get_next_number(document_type)
        
        # Get logo path
        buzz_logo_path = os.path.join(settings.STATIC_ROOT, 'assets/img/buzz.jpeg')
        
        # Determine payment method and date
        payment_method = "Online Payment"
        payment_date = ticket.created_at.strftime('%d/%m/%Y')
        
        # For manually approved tickets, check if M-Pesa
        if hasattr(ticket, 'staff_application') and ticket.staff_application:
            if ticket.staff_application.mpesa_message:
                payment_method = "M-Pesa"
                payment_date = ticket.staff_application.approved_at.strftime('%d/%m/%Y') if ticket.staff_application.approved_at else payment_date
        
        # Prepare context
        context = {
            'document_number': document_number,
            'invoice_date' if document_type == 'invoice' else 'receipt_date': datetime.now().strftime('%d/%m/%Y'),
            'ticket_number': ticket.ticket_number,
            'buzz_logo_path': buzz_logo_path,
            
            # Customer details
            'customer_name': ticket.guest_name,
            'customer_email': ticket.guest_email,
            'customer_phone': ticket.guest_phone or 'N/A',
            'customer_country': ticket.guest_country or '',
            'company_name': ticket.company_name or '',
            
            # Ticket/Event details
            'event_name': ticket.category.event.name if ticket.category else 'Event',
            'event_date': ticket.category.event.date.strftime('%d/%m/%Y') if ticket.category and ticket.category.event.date else 'TBA',
            'ticket_category': ticket.category.name if ticket.category else 'N/A',
            'ticket_price': float(ticket.category.price) if ticket.category else 0.00,
            
            # Transaction details
            'transaction_reference': ticket.ticket_number,  # Using ticket number as ref
            'payment_method': payment_method,
            'payment_date': payment_date,
            
            # Company details
            'company_pin': 'P051185889S',
        }
        
        # Select template
        template_name = f'documents/{document_type}_template.html'
        
        # Render HTML
        html_content = render_to_string(template_name, context)
        html_doc = HTML(string=html_content)
        
        # Create file path
        filename = f"{document_type}_{document_number.replace('-', '_')}.pdf"
        subfolder = 'invoices' if document_type == 'invoice' else 'receipts'
        file_path = os.path.join(f'{subfolder}/', filename)
        
        # Create directory
        full_dir = os.path.join(settings.MEDIA_ROOT, subfolder)
        os.makedirs(full_dir, exist_ok=True)
        
        # Save PDF
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        html_doc.write_pdf(full_path)
        
        # Create InvoiceReceipt record
        invoice_receipt = InvoiceReceipt.objects.create(
            ticket=ticket,
            document_type=document_type,
            document_number=document_number,
            pdf_file=file_path,
            sent_to_email=ticket.guest_email,
            company_name=ticket.company_name or '',
            customer_name=ticket.guest_name,
            customer_phone=ticket.guest_phone or 'N/A',
            customer_email=ticket.guest_email,
        )
        
        return invoice_receipt
        
    except Exception as e:
        print(f"Error generating {document_type} PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def send_invoice_receipt_email(invoice_receipt):
    """
    Send invoice or receipt via email
    Returns: (success: bool, message: str)
    """
    try:
        from django.core.mail import EmailMessage
        
        ticket = invoice_receipt.ticket
        doc_type = invoice_receipt.document_type.upper()
        
        # Email subject
        subject = f"Your {doc_type} - {ticket.category.event.name if ticket.category else 'Event'}"
        
        # Email body
        body = f"""Dear {invoice_receipt.customer_name},

Thank you for your purchase!

Please find attached your {doc_type.lower()} for:
- Event: {ticket.category.event.name if ticket.category else 'Event'}
- Ticket Number: {ticket.ticket_number}
- Amount: KES {float(ticket.category.price):,.2f}

If you have any questions, please contact us at accounts@buzzafrique.co.ke

Best regards,
Buzz Afrique Team

---
This is an automated email. Please do not reply directly to this message.
"""
        
        # Create email
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[invoice_receipt.sent_to_email],
        )
        
        # Attach PDF
        pdf_path = os.path.join(settings.MEDIA_ROOT, invoice_receipt.pdf_file.name)
        
        if os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as pdf_file:
                email.attach(
                    filename=f"{doc_type}_{invoice_receipt.document_number}.pdf",
                    content=pdf_file.read(),
                    mimetype='application/pdf'
                )
        else:
            return False, "PDF file not found"
        
        # Send email
        email.send(fail_silently=False)
        
        # Mark as sent
        invoice_receipt.mark_as_sent()
        
        return True, f"{doc_type} sent successfully"
        
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"Failed to send: {str(e)}"

