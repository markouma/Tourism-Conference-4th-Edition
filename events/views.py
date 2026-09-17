from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .models import BoothReviewHistory, Event, TicketCategory, Order, Ticket, Booth,    TicketScanLog, BoothReview, BoothVisit, PPVAccessToken, PPVEvent, ScanInstance, Speaker

from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden, JsonResponse, HttpResponseRedirect, FileResponse, Http404, HttpResponse
 
from django.conf import settings
from django.contrib import messages
import requests, base64, hashlib, hmac, os, json, uuid, qrcode, re, traceback, certifi, socket, logging
from django.db import IntegrityError, transaction
from django.db.models import Q   
from decimal import Decimal, ROUND_HALF_UP
from django.core.files.storage import FileSystemStorage

# pdf
from django.template.loader import render_to_string
from tourismconference.pdf import HTML


# login/signup
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group

# smtp
from django.core.mail import send_mail, EmailMessage   
from .utils import generate_paid_booth_receipt_pdf, get_paid_booth_receipt_context, generate_qr_code, generate_ticket_pdf, send_ticket_email, send_reject_email1, send_reject_email2, send_exhibitor_ticket_email, generate_payment_receipt_pdf, send_payment_receipt_email
  
from django.shortcuts import render

from django.utils.timezone import now, localtime
from django.utils.http import urlencode
from django.urls import reverse
from datetime import timedelta

from .forms import EventForm, TicketCategoryForm, TicketCategoryFormSet, StaffApplicationForm, StaffApplication, PaidApplicationForm, PaidApplication
from django.forms import inlineformset_factory, modelformset_factory
 
from tempfile import NamedTemporaryFile
from django.core.files import File
from .decorators import scanner_required, admin_or_scanner_required,  group_required



from django.core.serializers.json import DjangoJSONEncoder


import os, time
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from datetime import datetime
from requests.auth import HTTPBasicAuth 

from collections import defaultdict
from django.core.cache import cache



from django.views.decorators.cache import never_cache
from django.views.decorators.vary import vary_on_headers


from django.core.mail import EmailMultiAlternatives



def handle_temp_upload(uploaded_file):
    """Saving uploaded file temporarily and returns path"""
    temp_file = NamedTemporaryFile(delete=False)
    for chunk in uploaded_file.chunks():
        temp_file.write(chunk)
    temp_file.close()
    return temp_file.name

 

def homepage(request):
    query = request.GET.get('q', '')
    
    # Filter by query if present
    if query:
        events = Event.objects.filter(name__icontains=query) | Event.objects.filter(description__icontains=query)  | Event.objects.filter(location__icontains=query)
    else:
        events = Event.objects.all()

    # Sort events
    upcoming_events = events.filter(date__gte=now()).order_by('date')
    past_events = events.filter(date__lt=now()).order_by('-date')

    context = {
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'query': query,
    }

    return render(request, 'events/home.html', context)




def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    categories = TicketCategory.objects.filter(event=event)
    return render(request, 'events/event_detail.html', {
        'event': event,
        'categories': categories,
    })



def add_to_cart(request, event_id):
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        category = get_object_or_404(TicketCategory, id=category_id, event_id=event_id)

        cart = request.session.get('cart', {})
        existing_quantity = cart.get(category_id, 0)
        requested_quantity = existing_quantity + 1
        remaining = category.remaining_tickets()

        if requested_quantity > remaining:
            if existing_quantity > 0:
                # User already has tickets in cart
                messages.warning(
                    request, 
                    f"You already have {existing_quantity} {category.name} ticket(s) in your cart. "
                    f"Only {remaining} ticket(s) available total. "
                    f'<a href="/checkout/" class="alert-link">Go to Checkout</a> to complete your purchase.',
                    extra_tags='safe'  # Allows HTML in the message
                )
            else:
                # No tickets in cart, but none available
                messages.error(request, f"Sorry, {category.name} tickets are sold out!")
            
            return redirect('event_detail', event_id=event_id)

        # All good, add to cart
        cart[category_id] = requested_quantity
        request.session['cart'] = cart
        
        if existing_quantity > 0:
            messages.success(
                request, 
                f"Added another {category.name} ticket to cart (total: {requested_quantity}). "
                f'<a href="/checkout/" class="alert-link">Go to Checkout</a> to complete purchase.',
                extra_tags='safe'
            )
        else:
            messages.success(
                request, 
                f"{category.name} ticket added to cart! "
                f'<a href="/checkout/" class="alert-link">Go to Checkout</a> to complete purchase.',
                extra_tags='safe'
            )
        
        return redirect('checkout_router')



def checkout(request):
    cart = request.session.get('cart', {})
    cart_items = []
    total = 0

    for category_id, quantity in cart.items():
        category = get_object_or_404(TicketCategory, id=category_id)
        subtotal = category.price * quantity
        total += subtotal
        cart_items.append({
            'category': category,
            'quantity': quantity,
            'subtotal': subtotal,
        })
 
    if request.method == 'POST':
        try:
            # Save user details to session
            request.session['user_details'] = {
                'name': request.POST['name'],
                'email': request.POST['email'],
                'phone': request.POST['phone'],
            }
            request.session.save()  # Force session save
            if not cart:
                raise ValueError("Your cart is empty!")
            
            # Get first category to set event
            # CORRECTED: Get first category ID from cart
            first_category_id = list(cart.keys())[0]
            first_category = TicketCategory.objects.get(id=int(first_category_id))

            # Create order
            order = Order.objects.create(
                user_email=request.POST['email'],
                total_amount=total,
                event=first_category.event,  # Critical line
                is_paid=False
            )
            print(f" Order Created: {order.id}")

            # Get Pesapal token
            # from .utils import get_pesapal_token   
            token = get_pesapal_token()

            # Prepare payload
            payload = {
                "id": str(order.id),
                "currency": "KES",
                "amount": float(total),
                "description": "Event Tickets",
                "callback_url": f"{settings.BASE_URL}/payment_callback/",
                "redirect_mode": "PARENT_WINDOW",
                "notification_id": settings.PESAPAL_CONFIG['IPN_ID'],
                "billing_address": {
                    "email_address": request.POST['email'],
                    "phone": request.POST['phone'],
                    "first_name": request.POST['name'].split()[0],
                }
            }



            # Submit to Pesapal
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            response = requests.post(
                settings.PESAPAL_CONFIG['ORDER_URL'],
                json=payload,
                headers=headers,
                timeout=30
            )
            print(" Pesapal Response JSON (checkout):", response.json())  #  Add this here

            
            if response.status_code == 200:
                return redirect(response.json()['redirect_url'])
            else:
                messages.error(request, f"Payment error: {response.text}")

        except Exception as e:
            messages.error(request, f"Payment failed: {str(e)}")
            print(f" Checkout Error: {str(e)}")

    return render(request, 'events/checkout.html', {
        'cart_items': cart_items,
        'total': total,
    })


 

@require_POST
def update_cart(request, category_id):
    try:
        data = json.loads(request.body)
        cart = request.session.get('cart', {})
        action = data.get('action')

        if action == 'increment':
            cart[str(category_id)] = cart.get(str(category_id), 0) + 1
        elif action == 'decrement' and cart.get(str(category_id), 0) > 1:
            cart[str(category_id)] -= 1

        request.session['cart'] = cart
        category = TicketCategory.objects.get(id=category_id)
        current_qty = cart.get(str(category_id), 0)
        
        # Convert Decimal to float for JSON serialization
        new_subtotal = float(category.price) * current_qty
        new_total = float(sum(
            TicketCategory.objects.get(id=int(id)).price * qty 
            for id, qty in cart.items()
        ))
        
        return JsonResponse({
            'success': True,
            'new_quantity': current_qty,
            'new_subtotal': new_subtotal,
            'new_total': new_total  # Make sure this is included
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@require_POST
def remove_from_cart(request, category_id):
    try:
        cart = request.session.get('cart', {})
        if str(category_id) in cart:
            del cart[str(category_id)]
            request.session['cart'] = cart
            return JsonResponse({
                'success': True,
                'new_total': sum(
                    TicketCategory.objects.get(id=int(id)).price * qty 
                    for id, qty in cart.items()
                )
            })
        return JsonResponse({'success': False, 'error': 'Item not in cart'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


SUCCESS_CODES = {"COMPLETED", "SUCCESSFUL", "SUCCESS", "PAID", "APPROVED"}
FINAL_FAILURE_CODES = {"FAILED", "CANCELLED", "DECLINED", "VOID"}
PENDING_INDICATORS = {"PENDING", "PROCESSING", "INCOMPLETE", "UNKNOWN"}



@csrf_exempt
def payment_callback(request):
    """
    Unified Pesapal callback for both delegates and exhibitors.
    Purpose: record the tracking id, mark order.pending_verification, and
    schedule the async Celery verify task. Minimal and idempotent.
    """
    print("\n⚡ Unified Pesapal Callback Triggered")

    # Pesapal uses several different param names in the wild — accept them all.
    tracking_id = (
        request.GET.get("OrderTrackingId")
        or request.GET.get("orderTrackingId")
        or request.GET.get("pesapal_transaction_tracking_id")
        or None
    )
    order_id = (
        request.GET.get("OrderMerchantReference")
        or request.GET.get("order_id")
        or request.GET.get("pesapal_merchant_reference")
        or None
    )

    if not tracking_id or not order_id:
        print("Missing tracking_id or order_id in Pesapal callback:", request.GET)
        return JsonResponse({"status": "missing ids"}, status=400)

    try:
        from .models import Order
        order = Order.objects.get(id=order_id)
    except Exception as e:
        print("Order not found in unified callback:", order_id, e)
        return JsonResponse({"status": "order not found"}, status=404)

    # Save tracking id (useful for reconcile sweep / debug)
    if not order.pesapal_tracking_id:
        order.pesapal_tracking_id = tracking_id

    # Mark it in a conservative state and persist
    order.payment_status = "pending_verification"
    order.save()

    # Schedule the existing verification task (async)
    try:
        # local import to avoid circular imports at module import time
        from .tasks import verify_payment_task
        verify_payment_task.delay(str(order.id), tracking_id)
        print(f"Scheduled verify_payment_task for order={order.id} tracking={tracking_id}")
    except Exception:
        print("Failed to schedule verify_payment_task:", traceback.format_exc())

    # Redirect user to the same pending page your delegate flow used
    return HttpResponseRedirect(request.build_absolute_uri(f"/payment_pending/?order_id={order_id}"))



def pesapal_status(order_tracking_id: str, merchant_reference: str) -> dict:
    """
    Return parsed JSON from Pesapal status endpoint OR {'status': 'UNKNOWN'} on unrecoverable failure.
    This will retry once with force_refresh token on 401.
    """
    url = (
        f"{settings.PESAPAL_CONFIG['STATUS_URL']}"
        f"?orderTrackingId={order_tracking_id}&merchantReference={merchant_reference}"
    )

    def _call_with_token(token):
        res = requests.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=30)
        res.raise_for_status()
        return res.json()

    # Try cached token first
    try:
        token = get_pesapal_token(force_refresh=False)
        return _call_with_token(token)
    except requests.HTTPError as http_err:
        status_code = getattr(http_err.response, "status_code", None)
        if status_code == 401:
            # refresh and retry once
            try:
                fresh = get_pesapal_token(force_refresh=True)
                return _call_with_token(fresh)
            except Exception as e:
                logger.exception("Pesapal status retry after token refresh failed: %s", e)
                return {"status": "UNKNOWN"}
        else:
            logger.exception("Pesapal status http error: %s", http_err)
            return {"status": "UNKNOWN"}
    except Exception as exc:
        logger.exception("Pesapal status general error: %s", exc)
        return {"status": "UNKNOWN"}


@never_cache
@vary_on_headers('User-Agent')
def payment_success(request):
    request.session.modified = True
    try:
        order_id = request.GET.get('order_id')
        if not order_id:
            raise ValueError("Missing order_id in request")

        order = Order.objects.get(id=order_id)
        attendees = request.session.get('attendees') or request.session.get('booth_attendees')
        generated_tickets = []

        # Multi-attendee booth flow
        if attendees:
            print(f"DEBUG: Multi-attendee mode with {len(attendees)} attendees")
            
            # Mark order as paid first
            if not order.is_paid:
                order.is_paid = True
                order.payment_status = 'completed'
                order.save()
                print(f"DEBUG: Order {order.id} marked as paid")

            # Mark booths as permanently booked
            booth_count = 0
            for booth in order.booths.all():
                booth.mark_as_booked(user=order.user)
                booth_count += 1
            print(f"DEBUG: Marked {booth_count} booths as booked")

            # Generate and send payment receipt FIRST
            print(f"DEBUG: Starting receipt generation process...")
            try:
                booths = order.booths.all()
                print(f"DEBUG: Found {booths.count()} booths for order {order.id}")
                
                if booths.exists():
                    user_details = {
                        'name': order.user_name,
                        'email': order.user_email,
                        'phone': order.user_phone,
                        'kra_pin': order.kra_pin,
                    }
                    print(f"DEBUG: User details for receipt: {user_details}")
                    
                    # Check if functions exist
                    print(f"DEBUG: Checking if receipt functions exist...")
                    try:
                        # Test import
                        from .utils import generate_payment_receipt_pdf, send_payment_receipt_email
                        print(f"DEBUG: Receipt functions imported successfully")
                    except ImportError as ie:
                        print(f"ERROR: Failed to import receipt functions: {ie}")
                        raise
                    
                    print(f"DEBUG: About to generate receipt PDF...")
                    receipt_pdf_path = generate_payment_receipt_pdf(request, order, booths, user_details)
                    print(f"DEBUG: Receipt PDF generated successfully at: {receipt_pdf_path}")
                    
                    print(f"DEBUG: About to send receipt email to {order.user_email}...")
                    send_payment_receipt_email(
                        email=order.user_email,
                        customer_name=order.user_name,
                        order=order,
                        pdf_path=receipt_pdf_path
                    )
                    print(f"SUCCESS: Payment receipt sent to {order.user_email}")
                    
                else:
                    print(f"WARNING: No booths found for order {order.id} - skipping receipt")
                    
            except ImportError as ie:
                print(f"CRITICAL ERROR: Receipt functions not found: {ie}")
                print("Make sure generate_payment_receipt_pdf and send_payment_receipt_email are in your utils.py")
            except Exception as receipt_error:
                print(f"ERROR: Receipt generation failed: {receipt_error}")
                import traceback
                print("Full error traceback:")
                traceback.print_exc()

            # Create tickets if not already created
            print(f"DEBUG: Checking if tickets already exist for order {order.id}")
            if not order.tickets.exists():
                print(f"DEBUG: Creating tickets for {len(attendees)} attendees")
                for i, attendee in enumerate(attendees):
                    try:
                        print(f"DEBUG: Processing attendee #{i+1}: {attendee.get('name')}")
                        
                        temp_photo_rel = attendee.get('photo')
                        temp_photo_abs = (
                            os.path.join(settings.MEDIA_ROOT, temp_photo_rel)
                            if temp_photo_rel else None
                        )
                        print(f"DEBUG: Photo path for attendee #{i+1}: {temp_photo_abs}")

                        booth = None
                        booth_id = attendee.get('booth_id')
                        if booth_id:
                            try:
                                booth = Booth.objects.get(id=booth_id)
                                print(f"DEBUG: Found booth {booth.name} for attendee #{i+1}")
                            except Booth.DoesNotExist:
                                print(f"ERROR: Booth with ID {booth_id} not found for attendee #{i+1}")

                        ticket = Ticket.objects.create(
                            order=order,
                            category_id=attendee.get('category_id'),
                            guest_email=attendee.get('email'),
                            guest_name=attendee.get('name'),
                            guest_phone=attendee.get('phone'),
                            company_name=attendee.get('company') or attendee.get('company_name'),
                            designation=attendee.get('designation'),
                            booth=booth,
                            industry=attendee.get('industry'),
                            industry_description=attendee.get('industry_description'),
                            country=attendee.get('country'),
                            city=attendee.get('city'),
                            age_range=attendee.get('age_range'),
                            tshirt_size=attendee.get('tshirt_size'),
                            heard_about=attendee.get('referral_source'),
                            consent_given=attendee.get('consent', True),
                            kra_pin=attendee.get('kra_pin', ''),
                        )
                        print(f"SUCCESS: Created Ticket {ticket.id} for {ticket.guest_name}")

                        # Save photo
                        if temp_photo_abs and os.path.exists(temp_photo_abs):
                            with open(temp_photo_abs, 'rb') as f:
                                ticket.attendee_photo.save(
                                    f"attendee_{ticket.id}.jpg",
                                    File(f),
                                    save=True
                                )
                            print(f"DEBUG: Photo saved for ticket {ticket.id}")
                        else:
                            print(f"WARNING: No photo found for ticket {ticket.id}")

                        print(f"DEBUG: Generating QR code for ticket {ticket.id}")
                        generate_qr_code(ticket)

                        # Generate ticket PDF with KRA PIN
                        ticket_user_details = {
                            'name': ticket.guest_name,
                            'email': ticket.guest_email,
                            'phone': ticket.guest_phone,
                            'company': ticket.company_name,
                            'designation': ticket.designation,
                            'kra_pin': ticket.kra_pin,
                        }

                        print(f"DEBUG: Generating PDF for ticket {ticket.id}")
                        pdf_path = generate_ticket_pdf(
                            request=request,
                            ticket=ticket,
                            user_details=ticket_user_details,
                            qr_code_path=ticket.qr_code.path,
                            attendee_photo_path=ticket.attendee_photo.path if ticket.attendee_photo else None
                        )

                        ticket.pdf_ticket = pdf_path
                        ticket.save()
                        generated_tickets.append(ticket)
                        print(f"SUCCESS: PDF generated for ticket {ticket.id}")

                        # Send ticket email
                        try:
                            print(f"DEBUG: Sending ticket email to {ticket.guest_email}")
                            if ticket.order and ticket.order.booths.exists():
                                send_exhibitor_ticket_email(
                                    email=ticket.guest_email,
                                    guest_name=ticket.guest_name,
                                    company_name=ticket.company_name,
                                    booth_number=ticket.booth.name if ticket.booth else None,
                                    pdf_path=os.path.join(settings.MEDIA_ROOT, ticket.pdf_ticket.name),
                                )
                                print(f"SUCCESS: Sent Exhibitor ticket email to {ticket.guest_email}")
                            else:
                                send_ticket_email(
                                    email=ticket.guest_email,
                                    pdf_path=os.path.join(settings.MEDIA_ROOT, ticket.pdf_ticket.name),
                                    guest_name=ticket.guest_name,
                                )
                                print(f"SUCCESS: Sent General ticket email to {ticket.guest_email}")

                        except Exception as email_error:
                            print(f"ERROR: Failed to send ticket email to {ticket.guest_email}: {email_error}")

                        # Clean up temp photo
                        if temp_photo_abs and os.path.exists(temp_photo_abs):
                            try:
                                os.remove(temp_photo_abs)
                                print(f"DEBUG: Cleaned up temp photo for attendee #{i+1}")
                            except Exception as cleanup_error:
                                print(f"WARNING: Failed to clean up temp photo: {cleanup_error}")

                    except Exception as attendee_error:
                        print(f"ERROR: Error processing attendee #{i+1}: {attendee_error}")
                        import traceback
                        traceback.print_exc()
                        continue
            else:
                print(f"INFO: Tickets already created for order {order.id}")
            
            # Final ticket fetch
            order.refresh_from_db()
            generated_tickets = list(order.tickets.all())
            print(f"DEBUG: Final ticket count: {len(generated_tickets)}")

            # Clean up session
            session_keys_cleaned = 0
            for key in ['attendees', 'order_id', 'cart', 'booth_attendees']:
                if key in request.session:
                    request.session.pop(key, None)
                    session_keys_cleaned += 1
            print(f"DEBUG: Cleaned up {session_keys_cleaned} session keys")

            return render(
                request,
                'events/payment_success.html',
                {
                    'order': order,
                    'tickets': generated_tickets,
                    'user_details': {
                        'email': order.user_email,
                        'name': order.user_name or 'Guest',
                        'phone': order.user_phone,
                        'company_name': order.company,
                        'designation': order.designation,
                        'company': order.company,
                        'kra_pin': order.kra_pin,
                    }
                }
            )

        # Fallback single-ticket legacy mode
        print("DEBUG: Fallback to single-attendee flow")

        temp_photo_rel = request.session.get('temp_photo_path')
        temp_photo_abs = os.path.join(settings.MEDIA_ROOT, temp_photo_rel) if temp_photo_rel else None
        session_user = request.session.get('user_details', {})

        user_details = {
            'name': session_user.get('name') or order.user_name or 'Guest',
            'email': session_user.get('email') or order.user_email,
            'phone': session_user.get('phone') or order.user_phone,
            'company': session_user.get('company') or order.company,
            'designation': session_user.get('designation') or order.designation,
            'kra_pin': session_user.get('kra_pin') or order.kra_pin or '',
        }

        cart = request.session.get('cart', {})
        if not cart:
            first_ticket = order.tickets.first()
            if first_ticket and first_ticket.category:
                cart = {str(first_ticket.category.id): 1}
            else:
                raise ValueError("No cart or ticket data found.")

        category_id = str(next(iter(cart)))
        quantity = cart[category_id]
        category = TicketCategory.objects.get(id=int(category_id))

        # Mark order as paid
        if not order.is_paid:
            order.is_paid = True
            order.payment_status = 'completed'
            order.save()

        if not order.tickets.exists():
            for ticket_num in range(quantity):
                ticket = Ticket.objects.create(
                    order=order,
                    category=category,
                    guest_email=user_details['email'],
                    guest_name=user_details['name'],
                    guest_phone=user_details['phone'],
                    company_name=user_details['company'],
                    designation=user_details['designation'],
                    kra_pin=user_details['kra_pin'],
                )
                print(f"DEBUG: Created legacy ticket {ticket.id}")

                if temp_photo_abs and os.path.exists(temp_photo_abs):
                    with open(temp_photo_abs, 'rb') as f:
                        ticket.attendee_photo.save(
                            f"attendee_{ticket.id}.jpg",
                            File(f),
                            save=True
                        )

                generate_qr_code(ticket)

                pdf_path = generate_ticket_pdf(
                    request=request,
                    ticket=ticket,
                    user_details=user_details,
                    qr_code_path=ticket.qr_code.path,
                    attendee_photo_path=ticket.attendee_photo.path if ticket.attendee_photo else None
                )

                ticket.pdf_ticket = pdf_path
                ticket.save()
                generated_tickets.append(ticket)

                try:
                    if ticket.category and ticket.category.name == "Exhibitor":
                        send_exhibitor_ticket_email(
                            email=ticket.guest_email,
                            guest_name=ticket.guest_name,
                            company_name=ticket.company_name,
                            booth_number=ticket.booth.name if ticket.booth else None,
                            pdf_path=os.path.join(settings.MEDIA_ROOT, ticket.pdf_ticket.name)
                        )
                    else:
                        send_ticket_email(
                            email=ticket.guest_email,
                            pdf_path=os.path.join(settings.MEDIA_ROOT, ticket.pdf_ticket.name),
                            guest_name=ticket.guest_name
                        )
                    print(f"DEBUG: Sent ticket email for legacy ticket {ticket.id}")
                except Exception as e:
                    print(f"ERROR: Failed to send legacy ticket email: {e}")
        else:
            print("DEBUG: Tickets already exist for legacy fallback flow.")

        # Clean up temp photo
        if temp_photo_abs and os.path.exists(temp_photo_abs):
            try:
                os.remove(temp_photo_abs)
            except:
                pass

        # Clean up session
        for key in ['cart', 'user_details', 'temp_photo_path']:
            request.session.pop(key, None)

        # Final guaranteed fetch
        order.refresh_from_db()
        generated_tickets = list(order.tickets.all())

        return render(
            request,
            'events/payment_success.html',
            {'order': order, 'tickets': generated_tickets, 'user_details': user_details}
        )

    except Exception as e:
        print(f"CRITICAL ERROR in payment_success: {e}")
        import traceback
        print("Full error traceback:")
        traceback.print_exc()
        messages.error(request, "There was an error processing your tickets. Please contact support.")
        return redirect('payment_failed')



def payment_failed(request):
    """Display failure page"""
    messages.error(request, "Your request could not be processed. Please try again.")
    return render(request, 'events/payment_failed.html')



def not_found(request):
    messages.error(request, "Sorry, Ticket Not Found.")
    return render(request, 'events/not_found.html')



def get_pesapal_token(force_refresh: bool = False) -> str:
    """
    Returns a valid Pesapal token.
    If force_refresh True, always request a new token.
    Otherwise will use cached token if it has > TOKEN_REFRESH_MARGIN seconds left.
    """
    now = time.time()

    # 1. Reuse cached token if still valid
    if not force_refresh:
        token_data = cache.get(TOKEN_CACHE_KEY)
        if token_data:
            token = token_data.get("token")
            expires_at = float(token_data.get("expires_at", 0))
            if expires_at - now > TOKEN_REFRESH_MARGIN:
                return token
            else:
                logger.info(
                    "Pesapal token expiring soon (in %ds). Refreshing...",
                    int(expires_at - now),
                )

    original = _force_ipv4_getaddrinfo_patch()
    try:
        response = requests.post(
            "https://pay.pesapal.com/v3/api/Auth/RequestToken",
            data=json.dumps({
                "consumer_key": settings.PESAPAL_CONFIG["CONSUMER_KEY"],
                "consumer_secret": settings.PESAPAL_CONFIG["CONSUMER_SECRET"],
            }),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=15,
            verify=True,
        )
        print("🔎 Status:", response.status_code)
        print("🔎 Body:", response.text)

        response.raise_for_status()
        data = response.json()

        token = data.get("token")
        expiry_str = data.get("expiryDate")

        if not token or not expiry_str:
            raise Exception(f"Invalid response from Pesapal: {data}")

        # ✅ Parse expiryDate (e.g. "2025-09-02T03:33:50.6359064Z")
        from datetime import datetime, timezone

        try:
            expires_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            expires_at = expires_dt.timestamp()
        except Exception:
            logger.warning("Failed to parse expiryDate, defaulting to +1hr")
            expires_at = now + 3600

        cache_timeout = int(expires_at - now)
        cache.set(
            TOKEN_CACHE_KEY,
            {"token": token, "expires_at": expires_at},
            timeout=cache_timeout,
        )
        logger.info(
            "Pesapal token acquired. Expires at %s (in %ds)",
            expiry_str,
            cache_timeout,
        )
        return token

    except requests.exceptions.SSLError:
        raise Exception(
            "SSL verification failed. Ensure CA certs are installed on the server."
        )
    except requests.exceptions.RequestException as e:
        logger.error("Pesapal auth request failed: %s", str(e))
        raise
    finally:
        _restore_getaddrinfo(original)



logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "pesapal_token_data"
# safety margin in seconds - refresh if less than this time left
TOKEN_REFRESH_MARGIN = 300  # 5 mins


def _force_ipv4_getaddrinfo_patch():
    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda *args: original_getaddrinfo(args[0], args[1], socket.AF_INET)
    return original_getaddrinfo


def _restore_getaddrinfo(original):
    socket.getaddrinfo = original

















def download_ticket(request, ticket_id):
    try:
        ticket = Ticket.objects.get(id=ticket_id)

        if not ticket or not ticket.pdf_ticket:
            raise Http404("Ticket not found")

        pdf_path = ticket.pdf_ticket.path

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF missing at {pdf_path}")

        return FileResponse(
            open(pdf_path, 'rb'),
            filename=f'{ticket.id}_www.thetourismconference.org.pdf',
            as_attachment=True
        )

    except Ticket.DoesNotExist:
        return redirect('not_found')
    except Exception as e:
        print(f" Download Error: {str(e)}")
        return redirect('not_found')





# def signup(request):
#     if request.method == 'POST':
#         email = request.POST.get('email')
#         password = request.POST.get('password')
        
#         try:
#             # Existing email check remains unchanged
#             if User.objects.filter(email=email).exists():
#                 messages.error(request, "Account already exists! Please log in.")
#                 login_url = reverse('login')  # Your login view's name
#                 next_url = reverse('all_tickets')  # Where you want them to land after login
#                 query = urlencode({'next': next_url, 'email': email})
#                 return redirect(f"{login_url}?{query}")

#             # Create user (existing code)
#             user = User.objects.create_user(
#                 username=email,
#                 email=email,
#                 password=password
#             )
            
#             # Auto-login (existing code)
#             user = authenticate(username=email, password=password)
#             if user is not None:
#                 login(request, user)
                
#                 # FIX: Case-insensitive ticket linking
#                 updated_count = Ticket.objects.filter(
#                     Q(guest_email__iexact=email)  # Match email case-insensitively
#                 ).update(user=user)
                
#                 print(f"Linked {updated_count} tickets to new account")
#                 messages.success(request, "Account created successfully!")
#                 return redirect('all_tickets')

       
#             else:
#                 messages.error(request, "Authentication failed")
#                 return redirect('payment_success')

#         except IntegrityError:
#             messages.error(request, "Account already exists!")
#             return redirect('payment_success')

#         except Exception as e:
#             messages.error(request, f"Error: {str(e)}")
#             return redirect('payment_success')

#     return redirect('homepage')


# new signed sign-up
from django.core.signing import BadSignature, SignatureExpired
from django.core.signing import TimestampSigner
signer = TimestampSigner()



def assign_to_regular_group(user):
    group, created = Group.objects.get_or_create(name='Regular')
    if not user.groups.filter(name='Regular').exists():
        user.groups.add(group)



def assign_booths_to_user_by_email(user):
    """
    Auto-assign booths to user if they previously paid for one using their email.
    This also upgrades their group to 'Exhibitor'.
    """

    unassigned_booths = Booth.objects.filter(
        booked_by__isnull=True,
        order__user_email=user.email,
        order__is_paid=True
    )

    for booth in unassigned_booths:
        booth.mark_as_booked(user)  # should handle both .booked_by and group assign



def signup(request):
    token = request.GET.get('token')
    prefilled_email = None

    if token:
        try:
            prefilled_email = signer.unsign(token, max_age=60*60*24*30)  # 30 days
        except SignatureExpired:
            messages.error(request, "The signup link has expired.")
        except BadSignature:
            messages.error(request, "Invalid signup link.")

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        if User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists.")
            return redirect('login')

        user = User.objects.create_user(username=email, email=email, password=password)

        # 👉 Assign to 'Regular' group
        assign_to_regular_group(user)

        # 👉 Link to past booths & promote if necessary
        user_booths = Booth.objects.filter(order__user_email=email, booked_by__isnull=True)
        for booth in user_booths:
            booth.mark_as_booked(user)

        # ✅ Login & redirect
        login(request, user)
        return redirect('all_tickets')

    return render(request, 'events/signup.html', {'prefilled_email': prefilled_email})



def logout_view(request):
    logout(request)
    return redirect('index')

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)

            # If you want to honor ?next=... when present, check first
            next_url = request.POST.get('next')
            if not next_url:  
                if user.groups.filter(name='exhibitor').exists():
                    next_url = '/dashboard/exhibitor/'
                else:
                    next_url = '/dashboard/user/'

            return redirect(next_url)

        else:
            messages.error(request, 'Invalid email or password.')

    return render(request, 'events/login.html')



@login_required
def all_tickets(request):
    tickets = Ticket.objects.filter(
        Q(user=request.user) |
        Q(guest_email__iexact=request.user.email)
    ).distinct().order_by('-created_at')

    enriched_tickets = []
    for ticket in tickets:
        event_date = ticket.order.event.date if ticket.order and ticket.order.event else None
        is_expired = event_date and timezone.now() > (event_date + timedelta(days=1))

        # Get owner name
        if ticket.order:
            if ticket.order.user:  # Linked user
                owner_name = (
                    ticket.order.user.get_full_name()
                    or ticket.order.user.username
                    or ticket.order.user.email.split("@")[0]
                )
            elif ticket.order.user_name:  # Name stored directly in order
                owner_name = ticket.order.user_name
            else:
                owner_name = "Unknown"
        elif ticket.staff_application:
            owner_name = ticket.staff_application.full_name
        else:
            owner_name = "Unknown"

        enriched_tickets.append({
            "ticket": ticket,
            "is_expired": is_expired,
            "owner_name": owner_name
        })

    return render(request, 'events/all_tickets.html', {
        "tickets": enriched_tickets
    })



# password reset views
from django.shortcuts import render, redirect
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.core.mail import send_mail
from django.conf import settings
from django.utils.crypto import get_random_string
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

signer = TimestampSigner()


def password_reset_request(request):
    """Step 1: User enters email to request password reset"""
    if request.method == 'POST':
        email = request.POST.get('email')
        
        try:
            user = User.objects.get(email=email)
            
            # Generate OTP (6 digits)
            otp = get_random_string(length=6, allowed_chars='0123456789')
            
            # Generate signed reset token
            reset_token = signer.sign(email)
            
            # Store OTP in cache (expires in 15 minutes)
            cache_key = f'password_reset_otp_{email}'
            cache.set(cache_key, otp, 60*15)  # 15 minutes
            
            # Store email in session for auto-fill
            request.session['reset_email'] = email
            
            # Build reset URL
            reset_url = request.build_absolute_uri(f'/reset-password/{reset_token}/')
            
            # Send email with both OTP and reset link
            subject = 'Password Reset Request'
            message = f"""
Hi {user.username},

You requested to reset your password. You have two options:

Option 1 - Use OTP:
Your OTP code is: {otp}
This code expires in 15 minutes.
Enter it here: {request.build_absolute_uri('/reset-password/verify/')}

Option 2 - Use Reset Link:
Click here to reset: {reset_url}
This link expires in 1 hour.

If you didn't request this, please ignore this email.
"""
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            messages.success(request, f"Password reset instructions sent to {email}")
            return redirect('password_reset_verify')
            
        except User.DoesNotExist:
            # Don't reveal if email exists or not (security)
            messages.success(request, f"If an account exists with {email}, reset instructions have been sent.")
            return redirect('password_reset_verify')
    
    return render(request, 'events/password_reset_request.html')


def password_reset_verify(request, token=None):
    """Step 2: Verify OTP or handle token from URL"""
    # Get email from session or token
    email_from_session = request.session.get('reset_email')
    email_from_token = None
    
    if token:
        try:
            email_from_token = signer.unsign(token, max_age=60*60)  # 1 hour
        except (SignatureExpired, BadSignature):
            pass
    
    prefilled_email = email_from_token or email_from_session
    context = {'token': token, 'prefilled_email': prefilled_email}
    
    # Handle GET request - just show the form
    if request.method == 'GET':
        return render(request, 'events/password_reset_verify.html', context)
    
    # Handle POST request
    if request.method == 'POST':
        email = request.POST.get('email')
        otp = request.POST.get('otp', '').strip()
        token_input = request.POST.get('token', token)
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # Validate passwords match
        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'events/password_reset_verify.html', context)
        
        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters.")
            return render(request, 'events/password_reset_verify.html', context)
        
        verified_email = None
        
        # Method 1: Verify using OTP
        if otp and email:
            cache_key = f'password_reset_otp_{email}'
            stored_otp = cache.get(cache_key)
            
            if stored_otp and stored_otp == otp:
                verified_email = email
                cache.delete(cache_key)  # OTP used, delete it
            else:
                messages.error(request, "Invalid or expired OTP.")
                return render(request, 'events/password_reset_verify.html', context)
        
        # Method 2: Verify using signed token
        elif token_input:
            try:
                verified_email = signer.unsign(token_input, max_age=60*60)  # 1 hour
            except SignatureExpired:
                messages.error(request, "Reset link has expired.")
                return render(request, 'events/password_reset_verify.html', context)
            except BadSignature:
                messages.error(request, "Invalid reset link.")
                return render(request, 'events/password_reset_verify.html', context)
        else:
            messages.error(request, "Please provide either OTP or use the reset link.")
            return render(request, 'events/password_reset_verify.html', context)
        
        # Reset the password
        if verified_email:
            try:
                user = User.objects.get(email=verified_email)
                user.set_password(new_password)
                user.save()
                
                # Clear session
                if 'reset_email' in request.session:
                    del request.session['reset_email']
                
                messages.success(request, "Password reset successfully! You can now login.")
                return redirect('login')
            except User.DoesNotExist:
                messages.error(request, "User not found.")
                return render(request, 'events/password_reset_verify.html', context)
    
    return render(request, 'events/password_reset_verify.html', context)


@require_http_methods(["POST"])
def verify_otp_ajax(request):
    """AJAX endpoint to verify OTP instantly"""
    try:
        data = json.loads(request.body)
        email = data.get('email')
        otp = data.get('otp', '').strip()
        
        if not email or not otp:
            return JsonResponse({'valid': False, 'message': 'Email and OTP required'})
        
        # Check OTP from cache
        cache_key = f'password_reset_otp_{email}'
        stored_otp = cache.get(cache_key)
        
        if stored_otp and stored_otp == otp:
            return JsonResponse({'valid': True, 'message': 'OTP verified! ✓'})
        else:
            return JsonResponse({'valid': False, 'message': 'Invalid or expired OTP'})
            
    except Exception as e:
        return JsonResponse({'valid': False, 'message': 'Error verifying OTP'})
   

# password reset complete




@staff_member_required
def admin_dashboard(request):
    event_id = request.GET.get('edit')
    event = None

    if event_id:
        event = get_object_or_404(Event, id=event_id)

    if request.method == 'POST':
        event_form = EventForm(request.POST, request.FILES, instance=event)
        formset = TicketCategoryFormSet(request.POST, instance=event)
        if event_form.is_valid() and formset.is_valid():
            event = event_form.save()
            formset.instance = event
            formset.save()
            return redirect('admin_dashboard')  # refresh
    else:
        event_form = EventForm(instance=event)
        formset = TicketCategoryFormSet(instance=event)

    events = Event.objects.all().order_by('-date')
    context = {
        'event_form': event_form,
        'formset': formset,
        'events': events,
    }
    return render(request, 'admin/admin_dashboard.html', context)

@staff_member_required
def delete_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    event.delete()
    return redirect('admin_dashboard')

@staff_member_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    formset_class = inlineformset_factory(Event, TicketCategory, form=TicketCategoryForm, extra=0, can_delete=True)
    
    
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        formset = formset_class(request.POST, instance=event)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect('admin_dashboard')
    else:
        form = EventForm(instance=event)
        formset = formset_class(instance=event)

    return render(request, 'admin/edit_event.html', {
        'event_form': form,
        'formset': formset,
        'event': event,
    })


 

def checkout_router(request):
    print(f"🎯 checkout_router: Entered successfully")
    """Routes user to appropriate checkout based on event type"""
    cart = request.session.get('cart', {})
    if not cart:
        print("❌ checkout_router: No cart, redirecting to index")
        return redirect('index')
    
    first_category_id = list(cart.keys())[0]
    first_category = TicketCategory.objects.get(id=int(first_category_id))
    
    if first_category.event.event_type == 'conference':
        print(f"🏢 checkout_router: Redirecting to conference_checkout")
        return redirect('conference_checkout')
    
    print(f"📝 checkout_router: Redirecting to regular_checkout")
    return redirect('regular_checkout')




def regular_checkout(request):
    print(f"💳 regular_checkout: Entered successfully")
    start = time.time()
    print(f"\n=== ⏱️ Checkout started: {start} ===")

    cart = request.session.get('cart', {})
    if not cart:
        return redirect('index')

    cart_items = []
    total = 0

    for category_id, quantity in cart.items():
        category = get_object_or_404(TicketCategory, id=category_id)
        subtotal = category.price * quantity
        total += subtotal
        cart_items.append({
            'category': category,
            'quantity': quantity,
            'subtotal': subtotal,
        })

    print(f"✅ Cart processed in {time.time() - start:.2f}s")

    if request.method == 'POST':
        try:
            checkpoint = time.time()
            print("📥 POST received. Time:", checkpoint - start)

            print("Session keys:", request.session.keys())
            print("POST data:", request.POST)
            print("Phone field raw:", request.POST.get('phone'))

            phone = request.POST.get('phone')
            if not phone:
                raise ValueError("Phone number is required for payment.")

            # Extract attendees
            attendees_data = defaultdict(list)
            for key in list(request.POST.keys()) + list(request.FILES.keys()):
                match = re.match(r"attendees\[(\d+)\]\[(\d+)\]\[(\w+)\]", key)
                if match:
                    outer, inner, field = match.groups()
                    value = request.FILES[key] if key in request.FILES else request.POST[key]
                    attendees_data[(outer, inner)].append((field, value))

            attendees = []
            for k, v in attendees_data.items():
                attendee = {field: val for field, val in v}
                if 'photo' in attendee:
                    uploaded_file = attendee['photo']
                    temp_dir = 'temp_photos/'
                    temp_filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
                    temp_path = os.path.join(temp_dir, temp_filename)
                    full_path = default_storage.save(temp_path, ContentFile(uploaded_file.read()))
                    attendee['photo'] = full_path
                attendee['consent_given'] = attendee.get('consent_given') == 'true'
                attendees.append(attendee)

            print(f"🧍‍♂️ Extracted {len(attendees)} attendees in {time.time() - checkpoint:.2f}s")
            checkpoint = time.time()

            if not attendees:
                raise ValueError("No attendee data submitted.")

            first_category_id = list(cart.keys())[0]
            first_category = TicketCategory.objects.get(id=int(first_category_id))
            photo_path = attendees[0].get('photo')


            order = Order.objects.create(
                user_email=attendees[0]['email'],
                total_amount=total,
                event=first_category.event,
                is_paid=False,
                payment_status='pending',
                user_phone=phone,
                user_name=attendees[0]['name'],
                company=attendees[0].get('company'),
                designation=attendees[0].get('designation'),
                country=attendees[0].get('country', 'Kenya'),
                city=attendees[0].get('city'),
                age_range=attendees[0].get('age_range'),
                tshirt_size=attendees[0].get('tshirt_size'),
                sector=attendees[0].get('sector'),
                consent=attendees[0].get('consent_given', False),
                referral_source=attendees[0].get('referral_source'),
                attendee_photo=photo_path
            )

            print(f"💾 Order created (ID: {order.id}) in {time.time() - checkpoint:.2f}s")
            checkpoint = time.time()

            request.session['attendees'] = attendees
            request.session['order_id'] = str(order.id)
            request.session.save()

            payment_method = request.POST.get('payment_method', 'pesapal')

            if payment_method == 'mpesa':
                print("Processing DARAJA (M-Pesa) payment")

                formatted_phone = format_phone_number(phone)

                if is_phone_locked(formatted_phone):
                    print(f"🚫 Phone locked: {formatted_phone}")
                    messages.error(request, "You already have a pending M-Pesa request.")
                    return redirect('checkout_router')

                order.user_phone = formatted_phone
                order.save()

                response = initiate_stk_push(phone=formatted_phone, amount=total, order_id=order.id)
                print("📲 Daraja response:", response)

                if response.get('ResponseCode') == '0':
                    order.checkout_request_id = response.get('CheckoutRequestID')
                    order.payment_status = 'pending'
                    order.save()
                    lock_phone(formatted_phone)
                    print(f"✅ STK push sent in {time.time() - checkpoint:.2f}s")
                    return render(request, 'events/mpesa_pending.html', {'order': order})
                else:
                    messages.error(request, "M-Pesa payment request failed.")
                    return redirect('checkout_router')

            else:
                print("Processing PesaPal payment")
                checkpoint = time.time()

                token = get_pesapal_token()
                print(f"🪙 Pesapal token acquired in {time.time() - checkpoint:.2f}s")
                checkpoint = time.time()

                callback_url = f"{settings.BASE_URL}/payment_callback/"
                payload = {
                    "id": str(order.id),
                    "currency": "KES",
                    "amount": float(total),
                    "description": f"Event Tickets - Ref:{order.id}",
                    "callback_url": callback_url,
                    "redirect_mode": "PARENT_WINDOW",
                    "notification_id": settings.PESAPAL_CONFIG['IPN_ID'],
                    "billing_address": {
                        "email_address": attendees[0]['email'],
                        "phone_number": phone,
                        "first_name": attendees[0]['name'].split()[0],
                    }
                }

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }

                response = requests.post(
                    settings.PESAPAL_CONFIG['ORDER_URL'],
                    json=payload,
                    headers=headers,
                    timeout=30
                )

                print(f"📤 PesaPal POST done in {time.time() - checkpoint:.2f}s")
                checkpoint = time.time()

                try:
                    response_data = response.json()
                    print("JSON Response:", json.dumps(response_data, indent=2))
                except ValueError:
                    print("Response was not valid JSON")
                    response_data = {}

                if response.status_code == 200 and 'redirect_url' in response_data:
                    print(f"✅ Redirecting to Pesapal in {time.time() - start:.2f}s total")
                    return redirect(response_data['redirect_url'])
                else:
                    raise ValueError("Pesapal response missing redirect_url")

        except Exception as e:
            error_msg = f"❌ Payment failed: {str(e)}"
            messages.error(request, error_msg)
            print(error_msg)
            print(traceback.format_exc())

    print(f"🕹️ Rendering checkout form. Total time: {time.time() - start:.2f}s")
    return render(request, 'events/regular_checkout.html', {
        'cart_items': cart_items,
        'total': total,
    })




def conference_checkout(request):
    cart = request.session.get('cart', {})
    if not cart:
        return redirect('index')

    cart_items = []
    total = 0

    for category_id, quantity in cart.items():
        category  = get_object_or_404(TicketCategory, id=category_id)
        subtotal  = category.price * quantity
        total    += subtotal
        cart_items.append({
            'category': category,
            'quantity': quantity,
            'subtotal': subtotal,
        })

    if request.method == 'POST':
        try:
            # --------------------------------------------------
            # 1. basic validation (unchanged)
            # --------------------------------------------------
            if not all([
                request.POST.get('name'),
                request.POST.get('email'),
                request.POST.get('phone'),
                'attendee_photo' in request.FILES
            ]):
                messages.error(request, "Please fill all fields including the photo")
                return redirect('conference_checkout')

            # --------------------------------------------------
            # 2. photo upload & size check (unchanged)
            # --------------------------------------------------
            photo = request.FILES['attendee_photo']
            if photo.size > 2 * 1024 * 1024:
                messages.error(request, "Photo size must be less than 2MB")
                return redirect('conference_checkout')

            # save temp photo
            temp_path = handle_temp_upload(photo)          # MEDIA/temp_photos/…
            request.session['temp_photo_path'] = temp_path

            # --------------------------------------------------
            # 3. build user_details + include photo path
            # --------------------------------------------------
            user_details = {
                'name'           : request.POST['name'],
                'email'          : request.POST['email'],
                'phone'          : request.POST['phone'],
                'attendee_photo' : temp_path,               # ← NEW
            }

            request.session['user_details'] = user_details
            request.session.save()

            # --------------------------------------------------
            # 4. (unchanged) create order & hit Pesapal
            # --------------------------------------------------
            first_category_id = list(cart.keys())[0]
            first_category    = TicketCategory.objects.get(id=int(first_category_id))

            order = Order.objects.create(
                user_email   = request.POST['email'],
                total_amount = total,
                event        = first_category.event,
                is_paid      = False
            )

            token = get_pesapal_token()

            payload = {
                "id"             : str(order.id),
                "currency"       : "KES",
                "amount"         : float(total),
                "description"    : "Conference Ticket",
                "callback_url"   : f"{settings.BASE_URL}/payment_callback/",
                "redirect_mode"  : "PARENT_WINDOW",
                "notification_id": settings.PESAPAL_CONFIG['IPN_ID'],
                "billing_address": {
                    "email_address": request.POST['email'],
                    "phone" : request.POST['phone'],
                    "first_name"   : request.POST['name'].split()[0],
                }
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            response = requests.post(
                settings.PESAPAL_CONFIG['ORDER_URL'],
                json=payload,
                headers=headers,
                timeout=30
            )
            print(" Pesapal Response JSON (checkout):", response.json())

            if response.status_code == 200:
                return redirect(response.json()['redirect_url'])
            else:
                messages.error(request, f"Payment error: {response.text}")

        except Exception as e:
            messages.error(request, f"Payment failed: {str(e)}")
            print(f" Conference Checkout Error: {str(e)}")

    return render(request, 'events/conference_checkout.html', {
        'cart_items': cart_items,
        'total'     : total,
    })



def debug_photo(request):
    if 'temp_photo_path' in request.session:
        try:
            with open(request.session['temp_photo_path'], 'rb') as f:
                return HttpResponse(f.read(), content_type='image/jpeg')
        except Exception as e:
            return HttpResponse(f"Error: {str(e)}")
    return HttpResponse("No temp photo in session")


 
 
def booths_list(request, event_id):
    """Show the floor plan, handle booth pre-checkout."""
    event  = get_object_or_404(Event, id=event_id)
    booths = Booth.objects.filter(event=event).order_by('name')

    # ------------------------------------------------------------------
    # POST: user pressed the Pay button (pre‑checkout)
    # ------------------------------------------------------------------
    if request.method == 'POST':
        name  = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')

        booth_ids_str = request.POST.get('booth_ids', '')
        booth_ids     = [
            int(i) for i in booth_ids_str.split(',') if i.strip().isdigit()
        ]

        selected_booths = Booth.objects.filter(id__in=booth_ids, event=event)
        already_booked  = selected_booths.filter(is_booked=True)

        if already_booked.exists():
            names = ', '.join(b.name for b in already_booked)
            messages.error(request, f'Some booths are already booked: {names}')
            return redirect(request.path)

        total_amount = sum(b.price for b in selected_booths)
        tracking_id  = str(uuid.uuid4())

        #  Create unpaid order
        order = Order.objects.create(
            event=event,
            user_email=email,
            total_amount=Decimal(total_amount),
            is_paid=False,
            pesapal_tracking_id=tracking_id
        )

        #  Soft‑lock booths to the order
        for booth in selected_booths:
            booth.order      = order
            booth.booked_at  = timezone.now()
            booth.save()

        #  Stash basic customer details in session
        request.session['booth_customer_name']  = name
        request.session['booth_customer_phone'] = phone
        request.session['booth_customer_email'] = email

        #  Kick off Pesapal payment
        try:
            token = get_pesapal_token()
            payload = {
                'id'           : str(order.id),
                'currency'     : 'KES',
                'amount'       : float(total_amount),
                'description'  : 'Exhibition Booth Booking',
                'callback_url' : f'{settings.BASE_URL}/payment_callback/',
                'redirect_mode': 'IFRAME',
                'notification_id': settings.PESAPAL_CONFIG['IPN_ID'],
                'billing_address': {
                    'email_address': email,
                    'phone'        : phone,
                    'first_name'   : name.split()[0],
                },
            }
            headers = {
                'Content-Type' : 'application/json',
                'Authorization': f'Bearer {token}',
                'Accept'       : 'application/json',
            }
            response = requests.post(
                settings.PESAPAL_CONFIG['ORDER_URL'],
                json=payload,
                headers=headers,
                timeout=30
            )
            if response.status_code == 200:
                return redirect(response.json()['redirect_url'])
            messages.error(request, f'Pesapal Error: {response.text}')
            return redirect(request.path)

        except Exception as exc:
            messages.error(request, f'Payment setup failed: {exc}')
            return redirect(request.path)

    # ------------------------------------------------------------------
    # GET: just render the floor‑plan page
    # ------------------------------------------------------------------

    # JSON blob the front‑end already used
    booths_json = json.dumps(
        [
            {
                'id': b.id,
                'name': b.name,
                'price': int(b.price),
                'is_booked': b.is_booked,
                'is_reserved': b.is_reserved
            }
            for b in booths
        ],
        cls=DjangoJSONEncoder
    )
    booths_dict_json = json.dumps({str(b.name).strip(): b.id for b in booths})
    return render(request, 'events/booth_floor.html', {
        'event': event,
        'booths': booths,
        'booths_json': booths_json,
        'booths_dict_json': booths_dict_json,
    })







@csrf_exempt
def booth_checkout(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method != 'POST':
        return redirect('index')

    try:
        phone = request.POST.get('phone')
        payment_method = request.POST.get('payment_method')
        booth_ids_str = request.POST.get('booth_ids', '')
        
        # NEW: Get primary KRA PIN from the payment section
        primary_kra_pin = request.POST.get('primary_kra_pin', '').strip()

        if not payment_method:
            messages.error(request, "Please choose a payment method.")
            return redirect(request.path)

        if not booth_ids_str:
            messages.error(request, "Please select at least one booth.")
            return redirect(request.path)

        booth_ids = [int(id.strip()) for id in booth_ids_str.split(',') if id.strip().isdigit()]
        selected_booths = list(Booth.objects.filter(id__in=booth_ids, event=event))

        # Check permanently booked
        already_booked = [b for b in selected_booths if b.is_booked]
        if already_booked:
            names = ", ".join([b.name for b in already_booked])
            messages.error(request, f"Some booths are already booked: {names}")
            return redirect(request.path)

        # Check active reservations
        reserved_now = [b for b in selected_booths if b.is_reserved]
        if reserved_now:
            names = ", ".join([b.name for b in reserved_now])
            messages.error(request, f"Some booths are temporarily reserved: {names}. Try again shortly.")
            return redirect(request.path)

        # Calculate total with 16% VAT
        subtotal = sum([b.price for b in selected_booths])
        vat_rate = Decimal("1.16")
        total_amount = subtotal * vat_rate
        total_amount = total_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        # Parse attendee data
        attendees_data = defaultdict(dict)
        for key in list(request.POST.keys()) + list(request.FILES.keys()):
            match = re.match(r'attendees\[(\d+)\]\[(\w+)\]', key)
            if match:
                index, field = match.groups()
                if key in request.FILES:
                    attendees_data[index][field] = request.FILES[key]
                else:
                    attendees_data[index][field] = request.POST[key]

        attendees = list(attendees_data.values())
        if not attendees:
            messages.error(request, "Attendee information is required.")
            return redirect(request.path)

        # NEW: Ensure KRA PIN is captured for each attendee
        for attendee in attendees:
            if not attendee.get('kra_pin'):
                attendee['kra_pin'] = primary_kra_pin

        # Validate required fields
        for i, attendee in enumerate(attendees):
            required = ["email", "name", "company_name", "designation"]
            for field in required:
                if not attendee.get(field):
                    messages.error(request, f"{field.replace('_',' ').title()} missing for attendee #{i+1}")
                    return redirect(request.path)
            if 'attendee_photo' not in attendee:
                messages.error(request, f"Passport photo missing for attendee #{i+1}")
                return redirect(request.path)

        # Save photos temporarily and get the default ticket category for exhibitors
        try:
            exhibitor_category = TicketCategory.objects.filter(
                event=event, 
                name__icontains='exhibitor'
            ).first()
            
            if not exhibitor_category:
                exhibitor_category = TicketCategory.objects.filter(event=event).first()
                
            if not exhibitor_category:
                messages.error(request, "No ticket categories found for this event.")
                return redirect(request.path)
                
        except Exception as e:
            messages.error(request, "Error finding ticket category.")
            return redirect(request.path)

        for i, attendee in enumerate(attendees):
            photo = attendee.get('attendee_photo')
            if photo:
                temp_dir = 'temp_photos/'
                temp_filename = f"{uuid.uuid4().hex}_{photo.name}"
                temp_path = os.path.join(temp_dir, temp_filename)
                full_path = default_storage.save(temp_path, ContentFile(photo.read()))
                attendee['attendee_photo_path'] = full_path
                attendee['attendee_photo_original'] = attendee['attendee_photo']
            
            # Add booth mapping
            booth_id = attendee.get('booth_id')
            if booth_id:
                try:
                    booth = next((b for b in selected_booths if str(b.id) == str(booth_id)), None)
                    if booth:
                        attendee['booth_obj'] = booth
                except Exception as e:
                    print(f"Error mapping booth {booth_id}: {e}")

        # Create Order with KRA PIN
        first_attendee = attendees[0]
        order = Order.objects.create(
            user_email=first_attendee['email'],
            user_name=first_attendee['name'],
            user_phone=phone,
            company=first_attendee.get('company_name', ''),
            designation=first_attendee.get('designation', ''),
            country=first_attendee.get('country', ''),
            city=first_attendee.get('city', ''),
            age_range=first_attendee.get('age_range', ''),
            sector=first_attendee.get('industry', ''),
            consent=first_attendee.get('consent') == 'on',
            referral_source=first_attendee.get('referral_source', ''),
            total_amount=Decimal(total_amount),
            event=event,
            tshirt_size=first_attendee.get('tshirt_size', ''),
            is_paid=False,
            payment_status='pending',
            kra_pin=first_attendee.get('kra_pin', ''), 
            payment_method=payment_method,  
        )

        photo_path = first_attendee.get('attendee_photo_path')
        if photo_path:
            from django.core.files import File
            with default_storage.open(photo_path, 'rb') as f:
                order.attendee_photo.save(os.path.basename(photo_path), File(f), save=False)
            order.save()

        # Reserve booths
        reserve_minutes = getattr(settings, 'BOOTH_RESERVE_MINUTES', 10)
        for booth in selected_booths:
            booth.reserve(user=(request.user if request.user.is_authenticated else None), order=order, minutes=reserve_minutes)

        # Store complete session data with KRA PIN
        request.session['order_id'] = str(order.id)
        request.session['booth_attendees'] = [
            {
                # Basic info
                'name': a['name'],
                'email': a['email'],
                'phone': phone,
                
                # Company info  
                'company': a.get('company_name', ''),
                'company_name': a.get('company_name', ''),
                'designation': a.get('designation', ''),
                'industry': a.get('industry', ''),
                'industry_description': a.get('industry_description', ''),
                
                # Location
                'country': a.get('country', ''),
                'city': a.get('city', ''),
                
                # Personal
                'age_range': a.get('age_range', ''),
                'tshirt_size': a.get('tshirt_size', ''),
                'referral_source': a.get('referral_source', ''),
                'consent': a.get('consent') == 'on',
                
                # Booth info
                'booth_id': a.get('booth_id'),
                'booth_name': a.get('booth_name'),
                
                # Photo
                'photo': a.get('attendee_photo_path'),
                
                # Ticket info
                'category_id': exhibitor_category.id,
                
                # NEW: KRA PIN
                'kra_pin': a.get('kra_pin', ''),
            }
            for a in attendees
        ]

        # Debug output to verify session data
        print(f"Session booth_attendees data:")
        for i, attendee in enumerate(request.session['booth_attendees']):
            print(f"Attendee {i}: {attendee}")

        # Handle Payment
        if payment_method == 'mpesa':
            try:
                formatted_phone = format_phone_number(phone)
                if is_phone_locked(formatted_phone):
                    messages.error(request, "You have a pending M-Pesa payment. Please check your phone or wait 1 minute before retrying.")
                    return redirect(request.path)

                order.user_phone = formatted_phone
                order.save()

                response = initiate_stk_push(phone=formatted_phone, amount=total_amount, order_id=order.id)
                print("Daraja Response:", response)

                if response.get('ResponseCode') == '0':
                    order.checkout_request_id = response.get('CheckoutRequestID')
                    order.payment_status = 'pending'
                    order.save()
                    lock_phone(formatted_phone)
                    return render(request, 'events/mpesa_pending.html', {'order': order})
                else:
                    for b in selected_booths:
                        b.release_reservation()
                    messages.error(request, "M-Pesa payment request failed to send.")
                    return redirect(request.path)

            except Exception as e:
                for b in selected_booths:
                    b.release_reservation()
                messages.error(request, f"M-Pesa error: {str(e)}")
                print("M-Pesa Error:", traceback.format_exc())
                return redirect(request.path)

        elif payment_method == 'pesapal':
            try:
                token = get_pesapal_token()
                payload = {
                    "id": str(order.id),
                    "currency": "KES",
                    "amount": float(total_amount),
                    "description": "Exhibition Booth Booking",
                    "callback_url": f"{settings.BASE_URL}/payment_callback/",
                    "redirect_mode": "PARENT_WINDOW",
                    "notification_id": settings.PESAPAL_CONFIG['IPN_ID'],
                    "billing_address": {
                        "email_address": first_attendee['email'],
                        "phone_number": phone,
                        "first_name": first_attendee['name'].split()[0],
                    }
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }
                response = requests.post(settings.PESAPAL_CONFIG['ORDER_URL'], json=payload, headers=headers, timeout=30)
                print("Pesapal Response:", response.json())

                if response.status_code == 200 and 'redirect_url' in response.json():
                    return redirect(response.json()['redirect_url'])
                else:
                    for b in selected_booths:
                        b.release_reservation()
                    messages.error(request, "Payment failed: Pesapal error")
                    return redirect(request.path)

            except Exception as e:
                for b in selected_booths:
                    b.release_reservation()
                messages.error(request, f"Pesapal error: {str(e)}")
                print("Pesapal Error:", traceback.format_exc())
                return redirect(request.path)

        else:
            for b in selected_booths:
                b.release_reservation()
            messages.error(request, "Invalid payment method selected.")
            return redirect(request.path)

    except Exception as e:
        try:
            if 'order' in locals():
                for b in Booth.objects.filter(order=order):
                    b.release_reservation()
        except Exception:
            pass
        messages.error(request, f"Booth checkout failed: {str(e)}")
        print("Checkout Error:", traceback.format_exc())
        return redirect(request.path)




def start_pesapal_booth_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    # SECURITY: Never redirect to pay if already paid
    if order.is_paid:
        messages.warning(request, "Order is already paid.")
        return redirect('index')

    # Build callback URL
    callback_url = request.build_absolute_uri(reverse('pesapal_booth_callback'))

    # Create a mock pesapal payment link (replace this with real one)
    payment_url = f"https://www.pesapal.com/payment/mock?amount={order.total_amount}&order_id={order.id}&callback={callback_url}"

    #  store order tracking ID if using Pesapal REST API
    order.pesapal_tracking_id = "..."
    order.save()

    return HttpResponseRedirect(payment_url)


@csrf_exempt
def pesapal_booth_callback(request):
    """
    Pesapal sends the customer back here. We now VERIFY with Pesapal
    before we mark the order paid, book booths, or issue tickets.
    """
    order_id         = request.GET.get("order_id")           # your local ID
    order_tracking_id = (                                    # Pesapal’s ID
        request.GET.get("OrderTrackingId") or                # normal param
        request.GET.get("orderTrackingId") or                # just in case
        None
    )

    if not order_id or not order_tracking_id:
        return HttpResponse("Missing IDs", status=400)

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return HttpResponse("Invalid order", status=404)

    if order.is_paid:
        return HttpResponse("Already processed")

    # ── 1. Ask Pesapal if the payment is really completed ──────────────
    try:
        token = get_pesapal_token()           # ← your existing helper
        status_url = (
            f"{settings.PESAPAL_CONFIG['STATUS_URL']}"
            f"?orderTrackingId={order_tracking_id}"
            f"&merchantReference={order_id}"
        )
        res = requests.get(
            status_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30
        )
        res.raise_for_status()
        payment_status = res.json().get("payment_status")  # COMPLETED / FAILED / CANCELLED …
        print(f"Pesapal status for {order_id}: {payment_status}")
    except Exception as exc:
        print("Pesapal verify error:", exc)
        return HttpResponse("Could not verify payment", status=502)

    # ── 2. Act on the status ───────────────────────────────────────────
    if payment_status != "COMPLETED":
        # OPTIONAL: free the booths if the user cancelled/failed
        if payment_status in ("CANCELLED", "FAILED", "EXPIRED"):
            for b in order.booths.all():
                b.order = None
                b.is_booked = False
                b.save()
            order.payment_status = payment_status.lower()
            order.save()
        return HttpResponse(f"Payment {payment_status}. Tickets NOT issued.")

    # ── 3. Mark paid & book booths ─────────────────────────────────────
    order.is_paid        = True
    order.payment_status = "success"
    order.save()

    for booth in order.booths.all():
        booth.is_booked  = True
        booth.booked_at  = timezone.now()
        booth.save()

    # ── 4. Generate tickets & email (unchanged) ───────────────────────
    name  = request.session.get('booth_customer_name',  'Guest')
    phone = request.session.get('booth_customer_phone', '')
    email = order.user_email

    for booth in order.booths.all():
        ticket = Ticket.objects.create(
            order=order, guest_name=name, guest_email=email,
            guest_phone=phone, booth=booth
        )
        generate_qr_code(ticket)
        pdf_path = generate_ticket_pdf(
            request, ticket,
            {'name': name, 'email': email, 'phone': phone},
            ticket.qr_code.path
        )
        ticket.pdf_ticket.name = pdf_path
        ticket.save()
        send_ticket_email(
    email=email,
    pdf_path=ticket.pdf_ticket.path,
    guest_name=ticket.guest_name
)

    return HttpResponse("Payment verified and tickets sent.")




def scanner_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None and user.groups.filter(name='Scanner').exists():
            login(request, user)
            return redirect('scanner_event_list')  
        else:
            messages.error(request, "Invalid scanner credentials or not authorized.")

    return render(request, 'events/scanner_login.html')



@scanner_required
def scanner_event_list(request):
    events = Event.objects.all().order_by('-date')
    return render(request, 'events/scanner_event_list.html', {'events': events})

@scanner_required
def scan_ticket(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    # Get all active scan instances for this event
    scan_instances = ScanInstance.objects.filter(event=event, is_active=True).order_by('name')
    
    return render(request, 'events/scan_ticket.html', {
        'event': event,
        'scan_instances': scan_instances
    })




@scanner_required
def validate_ticket(request):
    code = request.GET.get('code', '')
    scan_instance_id = request.GET.get('scan_instance_id', '')
    
    response = {'valid': False}

    # Validate scan instance
    if not scan_instance_id:
        return JsonResponse({
            'valid': False,
            'message': "Please select a scan checkpoint"
        })

    try:
        scan_instance = ScanInstance.objects.get(id=scan_instance_id, is_active=True)
        print(f"DEBUG: Found scan_instance: {scan_instance}")
        print(f"DEBUG: scan_instance.event: {scan_instance.event}")
    except ScanInstance.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'message': "Invalid or inactive scan checkpoint"
        })
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'message': f"Error getting scan instance: {str(e)}"
        })

    try:
        # Split the code into ticket + event parts
        ticket_part, event_part = code.split('|')
        ticket_id = int(ticket_part.split(':')[1])
        event_uuid = int(event_part.split(':')[1])
        
        print(f"DEBUG: ticket_id={ticket_id}, event_uuid={event_uuid}")
        print(f"DEBUG: scan_instance.event.id={scan_instance.event.id if scan_instance.event else 'None'}")

        # Verify the scan instance belongs to the event - ADD NULL CHECK
        if not scan_instance.event:
            return JsonResponse({
                'valid': False,
                'message': "Scan instance has no associated event"
            })
            
        if scan_instance.event.id != event_uuid:
            return JsonResponse({
                'valid': False,
                'message': "Scan checkpoint does not match event"
            })

        # Robust filter: Paid orders OR approved staff applications
        filters = Q(id=ticket_id) & (
            Q(order__event__id=event_uuid, order__is_paid=True) |
            Q(staff_application__event__id=event_uuid, staff_application__status='approved') |
            Q(paid_application__event__id=event_uuid, paid_application__status='approved') |
            Q(category__event__id=event_uuid)  # Catches booth reps and other category-based tickets
        )

        # Fetch ticket with related data
        try:
            ticket = Ticket.objects.select_related(
                'order__event', 'user', 'staff_application__event', 
                'paid_application__event', 'category__event'
            ).get(filters)
            print(f"DEBUG: Found ticket: {ticket}")
        except Ticket.DoesNotExist:
            return JsonResponse({
                'valid': False,
                'message': "Ticket not found or not valid"
            })

        # Pick event source (order or staff application)
        # Pick event source (order, staff, paid booth, or category)
        if ticket.order and ticket.order.event:
            event = ticket.order.event
        elif ticket.staff_application and ticket.staff_application.event:
            event = ticket.staff_application.event
        elif ticket.paid_application and ticket.paid_application.event:
            event = ticket.paid_application.event
        elif ticket.category and ticket.category.event:
            event = ticket.category.event
        else:
            event = None
            print("DEBUG: No event found")

        if not event:
            return JsonResponse({
                'valid': False,
                'message': "No event associated with this ticket"
            })

        # Holder info
        holder_name = ticket.user.get_full_name() if ticket.user else ticket.guest_name or "Guest"
        holder_email = ticket.user.email if ticket.user else ticket.guest_email
        holder_phone = getattr(ticket.user, 'phone', None) if ticket.user else ticket.guest_phone

        # Safe photo handling
        holder_photo = None
        try:
            if ticket.user and hasattr(ticket.user, 'profile') and ticket.user.profile and ticket.user.profile.photo:
                holder_photo = ticket.user.profile.photo.url
            elif ticket.attendee_photo:
                holder_photo = ticket.attendee_photo.url
        except Exception as photo_error:
            print(f"DEBUG: Photo error: {photo_error}")
            holder_photo = None

        # Check if already scanned at this specific instance
        try:
            existing_scan_log = ticket.get_scan_log_for_instance(scan_instance)
            already_scanned = existing_scan_log is not None
            print(f"DEBUG: existing_scan_log: {existing_scan_log}, already_scanned: {already_scanned}")
        except Exception as scan_check_error:
            print(f"DEBUG: Scan check error: {scan_check_error}")
            return JsonResponse({
                'valid': False,
                'message': f"Error checking scan status: {str(scan_check_error)}"
            })

        # Base response
        response.update({
            'valid': True,
            'ticket': {
                'event_name': event.name if event else "Unknown Event",
                'event_date': event.date.strftime("%Y-%m-%d %H:%M") if event and hasattr(event, 'date') and event.date else "N/A",
                'location': getattr(event, 'location', 'N/A') if event else "N/A",
                'ticket_id': str(ticket.ticket_id),
                'ticket_number': ticket.ticket_number,
                'holder_name': holder_name,
                'holder_email': holder_email or '',
                'holder_phone': holder_phone or '',
                'qr_code_url': ticket.qr_code.url if ticket.qr_code else None,
                'holder_photo': holder_photo,

                # Extended fields - with safe access
                'company_name': getattr(ticket, 'company_name', '') or '',
                'designation': getattr(ticket, 'designation', '') or '',
                'industry': getattr(ticket, 'industry', '') or '',
                'industry_description': getattr(ticket, 'industry_description', '') or '',
                'country': getattr(ticket, 'country', '') or '',
                'city': getattr(ticket, 'city', '') or '',
                'age_range': getattr(ticket, 'age_range', '') or '',
                'tshirt_size': getattr(ticket, 'tshirt_size', '') or '',
                'heard_about': getattr(ticket, 'heard_about', '') or '',
                'sector': getattr(ticket, 'sector', '') or '',
                'consent_given': getattr(ticket, 'consent_given', False),
                'scan_instance': scan_instance.name,
            }
        })

        if not already_scanned:
            # Create new scan log for this instance
            try:
                scan_log = TicketScanLog.objects.create(
                    ticket=ticket,
                    scan_instance=scan_instance,
                    scanned_by=request.user
                )
                print(f"DEBUG: Created scan_log: {scan_log}")
                
                # Update ticket's overall scanning status
                if not ticket.first_scanned_at:
                    ticket.first_scanned_at = scan_log.scanned_at
                    ticket.is_used = True
                    ticket.save()

                scanned_time = localtime(scan_log.scanned_at).strftime("%Y-%m-%d %H:%M")
                response.update({
                    'scanned_before': False,
                    'message': f"✅ Scanned successfully at {scan_instance.name}",
                    'ticket': {
                        **response['ticket'],
                        'scanned_at_instance': scanned_time,
                        'scanned_by': request.user.username
                    }
                })
            except Exception as create_log_error:
                print(f"DEBUG: Create log error: {create_log_error}")
                return JsonResponse({
                    'valid': False,
                    'message': f"Error creating scan log: {str(create_log_error)}"
                })
        else:
            # Already scanned at this instance
            try:
                scanned_time = localtime(existing_scan_log.scanned_at).strftime("%Y-%m-%d %H:%M")
                response.update({
                    'scanned_before': True,
                    'message': f"⚠️ Already scanned at {scan_instance.name} on {scanned_time}",
                    'ticket': {
                        **response['ticket'],
                        'scanned_at_instance': scanned_time,
                        'scanned_by': existing_scan_log.scanned_by.username if existing_scan_log.scanned_by else "Unknown"
                    }
                })
            except Exception as existing_log_error:
                print(f"DEBUG: Existing log error: {existing_log_error}")
                # Continue anyway
                response.update({
                    'scanned_before': True,
                    'message': f"⚠️ Already scanned at {scan_instance.name}",
                })

        # Add scan history for all instances
        try:
            scan_history = []
            for log in ticket.get_all_scan_history():
                scan_history.append({
                    'instance_name': log.scan_instance.name if log.scan_instance else 'Unknown',
                    'scanned_at': localtime(log.scanned_at).strftime("%Y-%m-%d %H:%M"),
                    'scanned_by': log.scanned_by.username if log.scanned_by else "Unknown"
                })
            response['ticket']['scan_history'] = scan_history
        except Exception as history_error:
            print(f"DEBUG: History error: {history_error}")
            response['ticket']['scan_history'] = []

    except (ValueError, IndexError) as parse_error:
        print(f"DEBUG: Parse error: {parse_error}")
        response = {
            'valid': False,
            'message': "Invalid ticket code format"
        }
    except Exception as e:
        print(f"DEBUG: General error: {e}")
        import traceback
        traceback.print_exc()
        response = {
            'valid': False,
            'message': f"Server error: {str(e)}"
        }

    return JsonResponse(response)


# Utility function for creating scan logs - updated for instances
def create_scan_log_for_instance(ticket, scan_instance, scanned_by=None):
    """
    Creates a scan log for a specific instance if not already scanned there.
    Returns (scan_log, created) tuple.
    """
    try:
        # Check if already scanned at this instance
        existing_log = TicketScanLog.objects.get(
            ticket=ticket, 
            scan_instance=scan_instance
        )
        return existing_log, False
    except TicketScanLog.DoesNotExist:
        # Create new scan log
        scan_log = TicketScanLog.objects.create(
            ticket=ticket,
            scan_instance=scan_instance,
            scanned_by=scanned_by
        )
        
        # Update ticket's overall status if this is the first scan anywhere
        if not ticket.first_scanned_at:
            ticket.first_scanned_at = scan_log.scanned_at
            ticket.is_used = True
            ticket.save()
            
        return scan_log, True




def get_recent_scans(request):
    """
    API endpoint to fetch recent scans from 'Print' checkpoint
    Returns scans ordered by most recent first
    """
    try:
        # Get the 'Print' scan instance
        print_instance = ScanInstance.objects.get(name='Print', is_active=True)
        
        # Get all scans from this instance, ordered by newest first
        recent_scans = TicketScanLog.objects.filter(
            scan_instance=print_instance
        ).select_related(
            'ticket__user',
            'ticket__category',
            'scanned_by'
        ).order_by('-scanned_at')  # Newest first!
        
        # Build response data
        scans_data = []
        for scan_log in recent_scans:
            ticket = scan_log.ticket
            
            # Get holder info
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
    """
    Print station page that shows live feed of scans
    """
    return render(request, 'events/print_station.html')



# new pages
def blog(request):
    return render(request, 'events/blog.html')

def conference(request):
    return render(request, 'events/conference.html')

def exhibitors(request):
    return render(request, 'events/exhibitors.html')

def gallery(request):
    return render(request, 'events/gallery.html')

def golf(request):
    return render(request, 'events/golf.html')

def speakers(request):
    return render(request, 'events/speakers.html')

def stay(request):
    return render(request, 'events/stay.html')

def index(request):
    return render(request, 'events/index.html')


def Forewords(request):
    return render(request, 'events/Forewords.html')



# daraja 


def get_daraja_token():
    token_data = cache.get("daraja_token_data")
    now = time.time()

    if token_data:
        token = token_data.get('token')
        expires_at = float(token_data.get('expires_at', 0))

        # Keep token if it has more than 5 minutes left
        if expires_at - now > 300:
            return token
        else:
            print(f"⚠️ Daraja token expiring soon (in {expires_at - now:.0f}s). Refreshing...")

    consumer_key = settings.DARAJA_CONFIG['CONSUMER_KEY']
    consumer_secret = settings.DARAJA_CONFIG['CONSUMER_SECRET']
    auth_url = settings.DARAJA_CONFIG.get(
        'TOKEN_URL',
        'https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
    )

    response = requests.get(auth_url, auth=(consumer_key, consumer_secret))
    response.raise_for_status()
    data = response.json()

    token = data.get('access_token')
    try:
        expires_in = int(float(data.get('expires_in', 3600)))  # force numeric
    except (TypeError, ValueError):
        expires_in = 3600  # safe fallback

    expires_at = now + expires_in
    cache.set("daraja_token_data", {'token': token, 'expires_at': expires_at}, timeout=expires_in)

    print(f"✅ Daraja token acquired. Expires in {expires_in}s at {expires_at}")
    return token



def initiate_stk_push(phone, amount, order_id):
    try:
        #  Format phone first
        phone = format_phone_number(phone)

        token = get_daraja_token()
        shortcode = settings.DARAJA_CONFIG['SHORTCODE']
        passkey = settings.DARAJA_CONFIG['PASSKEY']
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": shortcode,
            "PhoneNumber": phone,
            "CallBackURL": settings.DARAJA_CONFIG['CALLBACK_URL'],
            "AccountReference": f"ORDER{order_id}",
            "TransactionDesc": "Event Ticket Purchase"
        }

        stk_url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest" 
        print("\n Sending STK Push Request to DARAJA")
        print(" Payload:", json.dumps(payload, indent=2))
        print(" Headers:", headers)
        print(" URL:", stk_url)

        response = requests.post(stk_url, json=payload, headers=headers, timeout=30)

        print("\n DARAJA STK RESPONSE")
        print(" Status Code:", response.status_code)
        print(" Raw Response Text:", response.text)

        if response.status_code == 200 and response.text.strip():
            return response.json()
        else:
            raise ValueError(f"Unexpected response from Daraja (Status {response.status_code}): {response.text}")

    except requests.exceptions.RequestException as e:
        print(" Network error during STK push:", str(e))
        raise

    except json.JSONDecodeError as e:
        print(" JSON decode error from Daraja:", str(e))
        raise

    except Exception as e:
        print(" General error during STK push:", str(e))
        raise



@csrf_exempt
def daraja_callback(request):
    data = json.loads(request.body)
    stk_data = data.get("Body", {}).get("stkCallback", {})

    checkout_id = stk_data.get("CheckoutRequestID")
    result_code = stk_data.get("ResultCode")
    result_desc = stk_data.get("ResultDesc")

    try:
        order = Order.objects.get(checkout_request_id=checkout_id)
        if result_code == 0:
            order.payment_status = 'success'
            order.is_paid = True  #  This was missing
            for booth in order.booths.all():
                booth.is_booked = True
                booked_at = timezone.now()
                booth.booked_at = booked_at  # Store booking time
                booth.save()
        else:
            order.payment_status = 'failed'
        order.save()
    except Order.DoesNotExist:
        print(" No matching order for CheckoutRequestID")

    return JsonResponse({"message": "OK"})



def format_phone_number(phone):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0") and len(phone) == 10:
        return "254" + phone[1:]
    elif phone.startswith("254") and len(phone) == 12:
        return phone
    elif phone.startswith("+254") and len(phone) == 13:
        return phone[1:]
    else:
        raise ValueError("Invalid phone number format.")


def payment_status_view(request, order_id):
    try:
        order = Order.objects.get(id=order_id)

        if not order.is_paid and order.checkout_request_id:
            print("↪ Callback might've failed, doing fallback STK query...")
            response = query_stk_status(order.checkout_request_id)
            print("STK Query Response:", response)

            # ResultCode comes as string from Daraja, so compare with '0' not int 0
            if response.get("ResultCode") == '0':
                order.payment_status = "success"
                order.is_paid = True
                order.save()

                # Lock the booths after successful payment
                for booth in order.booths.all():
                    booth.is_booked = True
                    booth.booked_at = timezone.now()
                    booth.save()

        status = 'success' if order.is_paid else order.payment_status or 'pending'
        return JsonResponse({'status': status})

    except Order.DoesNotExist:
        return JsonResponse({'status': 'unknown'}, status=404)


@require_POST
def retry_stk_push(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"message": "Order not found"}, status=404)

    if is_phone_locked(order.user_phone):
        return JsonResponse({
            "message": "M-Pesa request already sent. Please wait a minute before retrying."
        }, status=429)

    try:
        response = initiate_stk_push(
            phone=order.user_phone,
            amount=order.total_amount,
            order_id=order.id
        )
        if response.get("ResponseCode") == "0":
            order.checkout_request_id = response.get("CheckoutRequestID")
            order.payment_status = "pending"
            order.save()

            # 🔐 Lock this phone for 60 seconds
            lock_phone(order.user_phone)

            return JsonResponse({"message": "STK push retried successfully."})
        else:
            return JsonResponse({
                "message": "STK push failed to send. Please try again later."
            }, status=400)

    except Exception as e:
        return JsonResponse({
            "message": f"Error retrying STK push: {str(e)}"
        }, status=500)


# caching phone numbers

PHONE_LOCK_TTL = 60  # seconds

def is_phone_locked(phone):
    return cache.get(f"stk_lock:{phone}") is not None

def lock_phone(phone):
    cache.set(f"stk_lock:{phone}", True, timeout=PHONE_LOCK_TTL)





def query_stk_status(checkout_request_id):
    token = get_daraja_token()
    shortcode = settings.DARAJA_CONFIG['SHORTCODE']
    passkey = settings.DARAJA_CONFIG['PASSKEY']
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    response = requests.post(
        "https://api.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json=payload,
        headers=headers,
        timeout=30
    )

    return response.json()



# Staff application 


def staff_application_view(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if request.method == 'POST':
        form = StaffApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save(commit=False)
            app.event = event  # 🔥 Use the event from the URL param here
            app.save()
            send_mail(
                    subject='Acknowledgement of Tag Application - Pending Approval',
                    message=(
                        f"Dear {app.full_name},\n\n"
                        f"We acknowledge receipt of your tag application for the 4th Tourism Conference. Your request is currently under review.\n\n"
                        f"Once approved, the official tag will be sent to you via email.\n\n"
                        f"Thank you for your interest and cooperation\n\n"
                        f"Warm regards,\n"
                        f"The 4th Tourism Conference Secretariat."
                    ),
                    from_email='halloo@thetourismconference.org',
                    recipient_list=[app.email],
                    fail_silently=False,
                )
            messages.success(request, 'Application submitted! You will be notified once approved.')
            return redirect('staff_application_success')
    else:
        form = StaffApplicationForm()
    return render(request, 'events/staff_application.html', {
        'form': form,
        'event': event,  # pass it to template if you wanna display event info
    })


def staff_application_success(request):
    return render(request, 'events/staff_success.html')



def staff_application_denied(request):
    return render(request, 'events/staff_denied.html')



def approve_staff_application(request, app_id):
    app = get_object_or_404(StaffApplication, id=app_id)

    if app.status == 'approved':
        messages.warning(request, "Already approved.")
        return redirect('/admin/events/staffapplication/')

    app.status = 'approved'
    app.save()

    # Create ticket
    ticket = Ticket.objects.create(
        guest_name=app.full_name,
        guest_email=app.email,
        guest_phone=app.phone,
        company_name=app.company,
        designation=app.designation,
        country=app.country,
        city=app.city,
        tshirt_size=app.tshirt_size,
        sector=app.sector,
        consent_given=app.consent,
        heard_about=app.referral_source,
        age_range=app.age_range,
        attendee_photo=app.photo,
        staff_application=app   
    )

    # ✅ Generate QR and refresh ticket instance
    generate_qr_code(ticket)
    ticket.refresh_from_db()  # 💥 THIS is the magic

    user_details = {
        "name": app.full_name,
        "role": app.get_role_display(),
        "company": app.company,
        "designation": app.designation,
    }

    photo_path = app.photo.path if app.photo and app.photo.name and os.path.exists(app.photo.path) else None

    pdf_path = generate_ticket_pdf(
        request=request,
        ticket=ticket,
        user_details=user_details,
        qr_code_path=ticket.qr_code.name,
        attendee_photo_path=photo_path
    )

    ticket.pdf_ticket.name = pdf_path
    ticket.save()

    send_ticket_email(
    email=app.email,
    pdf_path=ticket.pdf_ticket.path,
    guest_name=app.full_name
)


    app.tag_sent = True
    app.save()

    return redirect('/admin/events/staffapplication/')

def reject_staff(request, pk):
    app = get_object_or_404(StaffApplication, pk=pk, status='pending')
    app.status = 'rejected'
    app.save()

    send_reject_email1(app.email, app.full_name)

    messages.success(request, f"{app.full_name} rejected and notified.")
    return redirect('/admin/events/staffapplication/')



# contact form

@csrf_exempt
def contact_form_submit(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')

        # Full email message
        full_message = f"From: {name} <{email}>\n\nSubject: {subject}\n\nMessage:\n{message}"

        try:
            send_mail(
                subject=f"📨 Contact Form: {subject}",
                message=full_message,
                from_email='halloo@thetourismconference.org',  # Must be allowed in   email backend
                recipient_list=['halloo@thetourismconference.org'],
                fail_silently=False,
            )
            return JsonResponse({'status': 'success', 'message': 'Message sent'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Failed to send email: {str(e)}'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


def clear_cart_view(request):
    if request.method == "POST":
        request.session.pop('cart', None)
        request.session.pop('attendees', None)
        request.session.pop('booth_attendees', None)
        request.session.modified = True
        return JsonResponse({'status': 'success', 'message': 'Cart cleared'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


def create_or_get_scan_log(ticket, scanned_by=None):
    """
    Logs the first scan of a ticket if it hasn't been scanned already.
    """
    scan_log, created = TicketScanLog.objects.get_or_create(
        ticket=ticket,
        defaults={'scanned_by': scanned_by}
    )

    if created:
        ticket.first_scanned_at = scan_log.scanned_at
        ticket.is_used = True
        ticket.save()

    return scan_log, created


def custom_404_view(request, exception):
    return render(request, 'events/404.html', status=404)

 
@group_required('regular')
def user_feedback_view(request):
    ...



@login_required
def user_dashboard(request):
    user = request.user

    # Get all tickets linked to this user
    user_tickets = Ticket.objects.filter(user=user)

    # Get booth visits where the scanned ticket belongs to this user
    booths_visited = BoothVisit.objects.filter(visitor=user).select_related('booth')

    # Optional: Also show reviews left by this user
    reviews_left = BoothReview.objects.filter(reviewer=user).select_related('booth')

    return render(request, 'events/user_dashboard.html', {
        'booths_visited': booths_visited,
        'reviews_left': reviews_left,
    })


@login_required
@user_passes_test(lambda u: u.groups.filter(name='Exhibitor').exists())
def exhibitor_dashboard(request):
    user = request.user
    booths = Booth.objects.filter(booked_by=user)
    
    # Generate QR codes for booths that don't have them
    for booth in booths:
        if not booth.booth_qr_code:
            booth.generate_booth_qr()

    visitors = BoothVisit.objects.filter(booth__in=booths).select_related('visitor', 'booth')
    reviews_received = BoothReview.objects.filter(booth__in=booths).select_related('reviewer', 'booth')

    # Attach guest_name for each review if exists
    for review in reviews_received:
        visit = BoothVisit.objects.filter(booth=review.booth, visitor=review.reviewer).first()
        review.guest_name = visit.guest_name if visit and visit.guest_name else None

    return render(request, 'events/exhibitor_dashboard.html', {
        'booths': booths,
        'visitors': visitors,
        'reviews_received': reviews_received,
    })




from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json

@csrf_exempt
@require_POST
def universal_scan_api(request):
    # ✅ Always return JSON even if not logged in
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Not logged in'}, status=403)

    try:
        data = json.loads(request.body)

        # 👋 Warmup check
        if data.get('code') == 'warmup':
            return JsonResponse({'success': True, 'message': 'Session active'})

        qr_code_data = data.get('code', '')
        if not qr_code_data or 'ticket:' not in qr_code_data:
            return JsonResponse({'success': False, 'message': 'Invalid QR data'})

        # Extract ticket and event ID from QR string: "ticket:257|event:7"
        code_parts = qr_code_data.split('|')
        if len(code_parts) != 2:
            return JsonResponse({'success': False, 'message': 'Malformed QR code'})

        ticket_part, event_part = code_parts
        ticket_id_raw = ticket_part.replace('ticket:', '')
        event_id_raw = event_part.replace('event:', '')

        if not ticket_id_raw.isdigit() or not event_id_raw.isdigit():
            return JsonResponse({'success': False, 'message': 'Invalid QR contents'})

        ticket_id = int(ticket_id_raw)
        event_id = int(event_id_raw)

        ticket = Ticket.objects.select_related('user', 'booth').filter(id=ticket_id).first()
        if not ticket:
            return JsonResponse({'success': False, 'message': 'Ticket not found'})

        current_user = request.user

        # 👨‍💼 Exhibitor scanning a visitor (EXISTING FUNCTIONALITY)
        if current_user.groups.filter(name='Exhibitor').exists():
            exhibitor_booths = current_user.booth_set.all()
            if not exhibitor_booths.exists():
                return JsonResponse({'success': False, 'message': 'You don`t own any booths.'})

            booth = exhibitor_booths.first()

            email = ticket.guest_email
            user = None

            if email:
                user = User.objects.filter(email=email).first()

            if not user:
                user = ticket.user

            if user:
                name = user.get_full_name() or user.email
                phone = getattr(user.profile, 'phone', None) if hasattr(user, 'profile') else None
                photo = getattr(user.profile, 'photo', None) if hasattr(user, 'profile') else None
            else:
                name = ticket.guest_name or email
                phone = ticket.guest_phone
                photo = ticket.attendee_photo

            # ✅ Safe for JSON
            photo_url = photo.url if photo else None

            visit_qs = BoothVisit.objects.filter(booth=booth)
            if user:
                visit_qs = visit_qs.filter(visitor=user)
            else:
                visit_qs = visit_qs.filter(visitor__isnull=True, guest_email=email)

            if visit_qs.exists():
                return JsonResponse({
                    'success': True,
                    'already_logged': True,
                    'visitor_name': name or email,
                    'visitor_photo': photo_url
                })

            BoothVisit.objects.create(
                booth=booth,
                visitor=user if user else None,
                guest_name=name,
                guest_email=email,
                guest_phone=phone,
                guest_photo=photo
            )

            return JsonResponse({
                'success': True,
                'already_logged': False,
                'visitor_name': name or email,
                'visitor_photo': photo_url
            })

        # 🙋🏽‍♂️ Attendee scanning an exhibitor (NEW FUNCTIONALITY)  
        else:  # Allow any logged-in user who is not an exhibitor
            # Check if the scanned ticket belongs to an exhibitor
            scanned_user = ticket.user
            if not scanned_user:
                return JsonResponse({'success': False, 'message': 'Invalid ticket - no user associated'})
            
            # DEBUG: Let's see what we have
            print(f"DEBUG: Scanned user: {scanned_user}")
            print(f"DEBUG: Scanned user groups: {list(scanned_user.groups.all())}")
            
            # Check if the scanned user is an exhibitor
            is_exhibitor = scanned_user.groups.filter(name='Exhibitor').exists()
            print(f"DEBUG: Is exhibitor: {is_exhibitor}")
            
            if not is_exhibitor:
                return JsonResponse({'success': False, 'message': f'This QR code belongs to {scanned_user.email}, who is not an exhibitor'})
            
            # Find the booth owned by this exhibitor - try different approaches
            from django.db import models
            booth = None
            
            # Method 1: Direct relationship
            if hasattr(scanned_user, 'booth_set'):
                booth = scanned_user.booth_set.first()
                print(f"DEBUG: Booth from booth_set: {booth}")
            
            # Method 2: Filter by booked_by
            if not booth:
                booth = Booth.objects.filter(booked_by=scanned_user).first()
                print(f"DEBUG: Booth from booked_by filter: {booth}")
            
            # Method 3: Check if ticket.booth exists
            if not booth and ticket.booth:
                booth = ticket.booth
                print(f"DEBUG: Booth from ticket.booth: {booth}")
                
            if not booth:
                return JsonResponse({'success': False, 'message': f'Exhibitor {scanned_user.email} does not have a booth assigned'})
            
            # Check if this user already visited this booth
            existing_visit = BoothVisit.objects.filter(booth=booth, visitor=current_user).first()
            
            if existing_visit:
                # Already visited, redirect to review page
                return JsonResponse({
                    'success': True,
                    'action': 'redirect_to_review',
                    'message': 'You already visited this booth. You can review it.',
                    'booth_id': booth.id,
                    'booth_name': booth.name,
                    'redirect_url': f'/leave_review/{booth.id}/'
                })
            
            # Create new booth visit
            BoothVisit.objects.create(
                booth=booth,
                visitor=current_user,
                guest_name=current_user.get_full_name(),
                guest_email=current_user.email,
                guest_phone=getattr(current_user.profile, 'phone', None) if hasattr(current_user, 'profile') else None,
                guest_photo=getattr(current_user.profile, 'photo', None) if hasattr(current_user, 'profile') else None
            )
            
            return JsonResponse({
                'success': True,
                'action': 'redirect_to_review',
                'message': f'Visit to {booth.name} logged successfully!',
                'booth_id': booth.id,
                'booth_name': booth.name,
                'redirect_url': f'/leave_review/{booth.id}/',
                'new_visit': True
            })

        return JsonResponse({'success': False, 'message': 'Unauthorized scan attempt'})

    except Exception as e:
        return JsonResponse({'success': False, 'message': f"Server error: {str(e)}"})


@login_required
@csrf_exempt
def submit_booth_review(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body)
        booth_id = data.get('booth_id')
        content = data.get('content', '').strip()
        rating = data.get('rating')
    except:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    if not content:
        return JsonResponse({'success': False, 'message': 'Review content is required'})

    try:
        booth = Booth.objects.get(id=booth_id)
    except Booth.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Booth not found'})

    review = BoothReview.objects.create(
        booth=booth,
        reviewer=request.user,
        content=content,
        rating=rating if rating else None
    )

    return JsonResponse({'success': True, 'message': 'Review submitted', 'booth_name': booth.name})


@login_required
def leave_review(request, booth_id):
    user = request.user

    # Updated: Check if user visited the booth OR allow direct access after scanning
    booth_visit = BoothVisit.objects.filter(booth_id=booth_id, visitor=user).first()
    if not booth_visit:
        return HttpResponseForbidden("You can only review booths you've visited.")

    booth = get_object_or_404(Booth, id=booth_id)
    existing_review = BoothReview.objects.filter(booth=booth, reviewer=user).first()

    if request.method == 'POST':
        try:
            rating = int(request.POST.get('rating'))
            content = request.POST.get('content')

            if not (1 <= rating <= 5):
                return HttpResponse("Rating must be between 1 and 5.", status=400)

            if existing_review:
                # Already reviewed before
                if existing_review.has_been_edited:
                    return HttpResponseForbidden("You already edited your review. No more changes allowed.")

                # Save the original to history
                BoothReviewHistory.objects.create(
                    review=existing_review,
                    rating=existing_review.rating,
                    content=existing_review.content
                )

                # Update review with new content
                existing_review.rating = rating
                existing_review.content = content
                existing_review.edited_at = timezone.now()
                existing_review.has_been_edited = True
                existing_review.save()

            else:
                # First time review
                BoothReview.objects.create(
                    booth=booth,
                    reviewer=user,
                    rating=rating,
                    content=content
                )

            return redirect('user_dashboard')

        except (ValueError, TypeError):
            return HttpResponse("Invalid input", status=400)

    return render(request, 'events/leave_review.html', {
        'booth': booth,
        'existing_review': existing_review,
    })


@login_required
def user_visits_api(request):
    visits = BoothVisit.objects.filter(visitor=request.user).select_related('booth').order_by('-scanned_at')
    data = [
        {
            'id': v.id,
            'booth_name': v.booth.name,
            'scanned_at': v.scanned_at.strftime("%b %d, %Y %H:%M"),
            'review': {
                'rating': v.booth.boothreview_set.filter(reviewer=request.user).first().rating
                          if v.booth.boothreview_set.filter(reviewer=request.user).exists() else None,
                'content': v.booth.boothreview_set.filter(reviewer=request.user).first().content
                          if v.booth.boothreview_set.filter(reviewer=request.user).exists() else None,
                'has_been_edited': v.booth.boothreview_set.filter(reviewer=request.user).first().has_been_edited
                          if v.booth.boothreview_set.filter(reviewer=request.user).exists() else False,
            }
        }
        for v in visits
    ]
    return JsonResponse({'visits': data})




# PAYBILL

def paid_application_view(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == 'POST':
        form = PaidApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save(commit=False)
            app.event = event
            app.save()

            send_mail(
                subject='Acknowledgement of Paid Tag Application - Pending Verification',
                message=(
                    f"Dear {app.full_name},\n\n"
                    f"We received your application and M-Pesa payment code {app.mpesa_code}. "
                    f"Our team will verify your payment and approve shortly.\n\n"
                    f"You will receive your tag via email once approved.\n\n"
                    f"Thank you!"
                ),
                from_email='halloo@thetourismconference.org',
                recipient_list=[app.email],
                fail_silently=False,
            )

            messages.success(request, 'Application submitted! We’ll notify you after payment verification.')
            return redirect('paid_application_success')
    else:
        form = PaidApplicationForm()

    return render(request, 'events/paid_application.html', {'form': form, 'event': event})


def approve_paid_application(request, app_id):
    app = get_object_or_404(PaidApplication, id=app_id)

    if app.status == 'approved':
        messages.warning(request, "Already approved.")
        return redirect('/admin/tickets/paidapplication/')

    # ✅ Mark approved
    app.status = 'approved'
    app.save()

    # 🎟️ Create ticket
    ticket = Ticket.objects.create(
        guest_name=app.full_name,
        guest_email=app.email,
        guest_phone=app.phone,
        company_name=app.company,
        designation=app.designation,
        country=app.country,
        city=app.city,
        tshirt_size=app.tshirt_size,
        sector=app.sector,
        consent_given=app.consent,
        heard_about=app.referral_source,
        age_range=app.age_range,
        attendee_photo=app.photo,
        paid_application=app
    )

    # 🔗 Generate QR + get path
    qr_code_path = generate_qr_code(ticket)

    # 👤 User details for PDF
    user_details = {
        "name": app.full_name,
        "role": app.designation,
        "company": app.company,
        "designation": app.designation,
    }

    # 🖼️ Photo path (optional)
    photo_path = app.photo.path if app.photo and os.path.exists(app.photo.path) else None

    # 📄 Generate PDF ticket
    pdf_path = generate_ticket_pdf(
        request=request,
        ticket=ticket,
        user_details=user_details,
        qr_code_path=qr_code_path,
        attendee_photo_path=photo_path
    )

    ticket.pdf_ticket.name = pdf_path
    ticket.save()

    # 📧 Send email with ticket attached
    send_ticket_email(
        email=app.email,
        pdf_path=ticket.pdf_ticket.path,
        guest_name=app.full_name,
        # mpesa_code=app.mpesa_code
    )

    app.tag_sent = True
    app.save()

    return redirect('/admin/events/paidapplication/')




def reject_paid_application(request, app_id):
    app = get_object_or_404(PaidApplication, id=app_id)

    if app.status == 'rejected':
        messages.warning(request, "Already rejected.")
        return redirect('/admin/events/paidapplication/')

    app.status = 'rejected'
    app.save()

    send_reject_email2(app.email, app.full_name, app.mpesa_code)

    messages.success(request, f"{app.full_name} rejected and notified.")
    return redirect('/admin/events/paidapplication/')


def paid_application_success(request):
    return render(request, 'events/paid_success.html')

def paid_application_denied(request):
    return render(request, 'events/paid_denied.html')








def payment_pending(request):
    order_id = request.GET.get("order_id")
    order = Order.objects.filter(id=order_id).first()

    if not order:
        return redirect("payment_failed")

    if order.payment_status == "success":
        return redirect(f"/payment_success/?order_id={order_id}")
    if order.payment_status == "failed":
        return redirect(f"/payment_failed/?order_id={order_id}")

    # still pending -> show spinner page
    return render(request, 'events/payment_pending.html', {"order_id": order_id})


# AJAX endpoint for status polling
def check_payment_status(request, order_id):
    order = Order.objects.filter(id=order_id).first()
    if not order:
        return JsonResponse({"status": "failed"})

    return JsonResponse({"status": order.payment_status})





# PPV

def create_ppv_token(order, ppv_event):
    token = PPVAccessToken.objects.create(
        order=order,
        ppv_event=ppv_event
    )
    redemption_link = f"{settings.BASE_URL}/ppv/redeem/{token.token}/"
    # Reuse your existing email system
    send_mail(order.user_email, "Your PPV Access Link",
               f"Click here to create your account: {redemption_link}") 
     
    
    return token


def ppv_redeem_view(request, token):
    ppv_token = get_object_or_404(PPVAccessToken, token=token)

    if not ppv_token.is_valid():
        return render(request, "ppv/invalid_token.html")  # create this template

    if request.method == "POST":
        password = request.POST.get("password")
        email = ppv_token.order.user_email
        user = User.objects.create_user(email=email, password=password)
        ppv_token.user = user
        ppv_token.redeemed = True
        ppv_token.save()
        return redirect("ppv_dashboard", ppv_event_id=ppv_token.ppv_event.id)

    return render(request, "ppv/redeem.html", {"email": ppv_token.order.user_email})


from .forms import BoothApplicationForm, BoothRepresentativeForm


def booth_application_view(request, event_id):
    from .models import Event
    event = Event.objects.get(id=event_id)

    # always create base forms
    if request.method == 'POST':
        app_form = BoothApplicationForm(request.POST)
        rep1_form = BoothRepresentativeForm(request.POST, request.FILES, prefix='rep1')
        rep2_form = BoothRepresentativeForm(request.POST, request.FILES, prefix='rep2')

        if app_form.is_valid() and rep1_form.is_valid():
            try:
                booth_app = app_form.save(commit=False)
                booth_app.event = event
                booth_app.save()
            except IntegrityError:
                messages.error(request, "Booth number + company combo already used. Contact support.")
                return redirect(request.path)

            # save rep1
            rep1 = rep1_form.save(commit=False)
            rep1.application = booth_app
            rep1.save()

            # only save rep2 if the form is valid *and* not empty
            if rep2_form.is_valid() and any(rep2_form.cleaned_data.values()):
                rep2 = rep2_form.save(commit=False)
                rep2.application = booth_app
                rep2.save()

            messages.success(request, "Booth representatives submitted successfully!")
            return redirect('booth_application_success')

        # If validation fails, fall through to re-render the form with errors
        rep_forms = [rep1_form, rep2_form]

    else:
        app_form = BoothApplicationForm()
        rep1_form = BoothRepresentativeForm(prefix='rep1')
        rep2_form = BoothRepresentativeForm(prefix='rep2')
        rep_forms = [rep1_form, rep2_form]

    return render(request, 'events/booth_application.html', {
        'app_form': app_form,
        'rep_forms': rep_forms,
        'event': event,
    })





def booth_application_success(request):
    return render(request, 'events/booth_application_success.html')


# Ongeza hizi kwa views.py 

from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils import timezone
from .models import PaidBoothApplication, Ticket, TicketCategory
from .forms import PaidBoothApplicationForm

def paid_booth_application_view(request):
    """
    This view handles the booth application form
    GET request = show the form
    POST request = process the form submission
    """
    
    if request.method == 'POST':
        # User submitted the form
        form = PaidBoothApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            # Form data is valid, save the application
            application = form.save()
            
            # Send "application received" email
            send_application_received_email(application)
            
            # Show success message to user
            messages.success(
                request, 
                f"Application received! We've sent a confirmation to {application.email}. "
                "You will hear from us within 2 business days."
            )
            
            # Redirect to prevent resubmission
            return redirect('paid_booth_application_success')
        else:
            # Form has errors, show them to user
            messages.error(request, "Please correct the errors below.")
    
    else:
        # GET request = show empty form
        form = PaidBoothApplicationForm()
    
    return render(request, 'events/paid_booth_application.html', {
        'form': form,
        'title': 'Booth Ticke Application Status'
    })



def paid_booth_application_success(request):
    """
    Success page shown after form submission
    """
    return render(request, 'events/paid_booth_success.html', {
        'title': 'Application Submitted Successfully'
    })


@staff_member_required
def paid_booth_admin_dashboard(request):
    """
    Admin dashboard to view all applications
    Only staff members can access this
    """
    # Get all applications, newest first
    applications = PaidBoothApplication.objects.all()
    
    # Count applications by status
    pending_count = applications.filter(status='pending').count()
    approved_count = applications.filter(status='approved').count()
    rejected_count = applications.filter(status='rejected').count()
    
    context = {
        'applications': applications,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'title': 'Paid Booth Applications Dashboard'
    }
    
    return render(request, 'admin/paid_booth_dashboard.html', context)

@staff_member_required
def approve_paid_booth_application(request, application_id):
    """
    Approve a specific application and create ticket
    """
    application = get_object_or_404(PaidBoothApplication, id=application_id)
    
    if request.method == 'POST':
        admin_message = request.POST.get('admin_message', '')
        
        try:
            # Approve the application
            application.approve(request.user, admin_message)
            
            # Create the ticket
            ticket = create_ticket_from_application(application)
            
            # Send approval email with ticket
            send_approval_email(application, ticket)
            
            messages.success(request, f"Application approved! Ticket sent to {application.email}")
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            messages.error(request, f"Error approving application: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})



@staff_member_required
def reject_paid_booth_application(request, application_id):
    """
    Reject a specific application
    """
    application = get_object_or_404(PaidBoothApplication, id=application_id)
    
    if request.method == 'POST':
        admin_message = request.POST.get('admin_message', 'Your application was not approved.')
        
        try:
            # Reject the application
            application.reject(request.user, admin_message)
            
            # Send rejection email
            PaidBooth_rejection_email(application)
            
            messages.success(request, f"Application rejected. Email sent to {application.email}")
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            messages.error(request, f"Error rejecting application: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

def create_ticket_from_application(application):
    # Get or create category with event_id
    category, created = TicketCategory.objects.get_or_create(
        name="Paid Booth Representative",
        event_id=1,  # Add this
        defaults={'price': 0}
    )
    
    # Create ticket
    ticket = Ticket.objects.create(
        category=category,
        guest_email=application.email,
        guest_name=application.name,
        guest_phone=application.phone_number,
        attendee_photo=application.profile_image,  # Add this
        company_name=application.company,
        designation=application.title_designation,
        industry=application.industry,
        country=application.country,
        city=application.city,
        booth_number=application.booth_number,
        consent_given=application.consent_given,
    )
    
    # Link ticket to application
    application.ticket = ticket
    application.save()
    
    # Generate QR and PDF
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
            request=None,
            ticket=ticket,
            user_details=user_details,
            qr_code_path=qr_code_path,
            attendee_photo_path=application.profile_image.path if application.profile_image else None
            )
        print(f"Application profile_image: {application.profile_image}")
        print(f"Profile image path: {application.profile_image.path if application.profile_image else 'None'}")
        print(f"File exists: {os.path.exists(application.profile_image.path) if application.profile_image else False}")
        
        ticket.pdf_ticket = pdf_path
        ticket.save()
    
    return ticket



# Email Functions
def send_application_received_email(application):
    """
    Send "application received" confirmation email
    """
    subject = "Booth Tag Application Received"
    
    html_message = render_to_string('events/paid_booth_success_mail.html', {
        'application': application,
        'name': application.name,
    })
    
    send_mail(
        subject=subject,
        message=f"Dear {application.name}, your booth tag application has been received.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[application.email],
        html_message=html_message,
        fail_silently=False,
    )

def send_approval_email(application, ticket):
    """
    Send approval email with ticket attachment
    """
    subject = "Payment Approved - Your Ticket(Booth)"
    
    html_message = render_to_string('events/paid_booth_approved.html', {
        'application': application,
        'ticket': ticket,
        'admin_message': application.admin_message,
    })
    
    # Create email with PDF attachment
    from django.core.mail import EmailMultiAlternatives
    
    email = EmailMultiAlternatives(
        subject=subject,
        body=f"Dear {application.name}, your application has been approved!",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[application.email],
    )
    
    email.attach_alternative(html_message, "text/html")
    
    # Attach PDF ticket if it exists
    if ticket.pdf_ticket:
        email.attach_file(ticket.pdf_ticket.path)
    
    email.send()





def PaidBooth_rejection_email(application):
    """
    Send rejection email
    """
    subject = "Booth Tag Application Update"
    
    html_message = render_to_string('events/paid_booth_rejected.html', {
        'application': application,
        'admin_message': application.admin_message,
    })
    
    send_mail(
        subject=subject,
        message=f"Dear {application.name}, regarding your booth tag application.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[application.email],
        html_message=html_message,
        fail_silently=False,
    )


from django.views.decorators.clickjacking import xframe_options_exempt

@xframe_options_exempt
def booth_floor_live(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    booths = Booth.objects.filter(event=event)
    
    # Handle JSON requests for AJAX updates
    if request.headers.get('Accept') == 'application/json':
        booths_data = [{
            'id': booth.id,
            'name': booth.name,
            'price': float(booth.price),
            'is_booked': booth.is_booked,
            'is_reserved': booth.is_reserved,
        } for booth in booths]
        return JsonResponse({'booths': booths_data})
    
    # Handle regular HTML requests for initial iframe load
    booths_json = json.dumps([{
        'id': booth.id,
        'name': booth.name,
        'price': float(booth.price),
        'is_booked': booth.is_booked,
        'is_reserved': booth.is_reserved,
    } for booth in booths])
    
    context = {
        'event': event,
        'booths': booths,
        'booths_json': booths_json,
    }
    return render(request, 'events/booth_floor2.html', context)




@csrf_exempt
@require_POST
def booth_scan_api(request):
    """Simple API to handle booth:123 QR codes"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Not logged in'}, status=403)

    try:
        data = json.loads(request.body)
        
        # Warmup check
        if data.get('code') == 'warmup':
            return JsonResponse({'success': True, 'message': 'Session active'})

        qr_code_data = data.get('code', '')
        
        # Check for booth QR format: "booth:123"
        if qr_code_data.startswith('booth:'):
            booth_id_str = qr_code_data.replace('booth:', '')
            
            if not booth_id_str.isdigit():
                return JsonResponse({'success': False, 'message': 'Invalid booth QR code'})
            
            booth_id = int(booth_id_str)
            
            try:
                booth = Booth.objects.get(id=booth_id)
            except Booth.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'Booth not found'})
            
            current_user = request.user
            
            # Check if user already visited this booth
            existing_visit = BoothVisit.objects.filter(booth=booth, visitor=current_user).first()
            
            if existing_visit:
                return JsonResponse({
                    'success': True,
                    'action': 'redirect_to_review',
                    'message': f'You already visited {booth.name}. You can review it.',
                    'booth_id': booth.id,
                    'booth_name': booth.name,
                    'redirect_url': f'/leave_review/{booth.id}/',
                    'already_visited': True
                })
            
            # Create new booth visit
            BoothVisit.objects.create(
                booth=booth,
                visitor=current_user,
                guest_name=current_user.get_full_name() or current_user.username,
                guest_email=current_user.email,
                guest_phone=getattr(current_user.profile, 'phone', None) if hasattr(current_user, 'profile') else None,
                guest_photo=getattr(current_user.profile, 'photo', None) if hasattr(current_user, 'profile') else None
            )
            
            return JsonResponse({
                'success': True,
                'action': 'redirect_to_review',
                'message': f'Visit to {booth.name} logged successfully!',
                'booth_id': booth.id,
                'booth_name': booth.name,
                'redirect_url': f'/leave_review/{booth.id}/',
                'new_visit': True
            })
        
        else:
            return JsonResponse({'success': False, 'message': 'Invalid QR code format. Expected booth QR code.'})

    except Exception as e:
        return JsonResponse({'success': False, 'message': f"Server error: {str(e)}"})


# Add these functions to your existing views.py file



# CC email addresses for paid booth receipts
PAID_BOOTH_CC_EMAILS = ['accounts@buzzafrique.co.ke', 'coasttourismconference@gmail.com']

def send_paid_booth_receipt_email(application):
    """
    Send payment receipt email with PDF attachment
    """
    try:
        # Generate receipt PDF
        pdf_path = generate_paid_booth_receipt_pdf(application)
        
        if not pdf_path:
            raise Exception("Failed to generate receipt PDF")
        
        # Get context for email
        context = get_paid_booth_receipt_context(application)
        
        # Email subject
        subject = f"Payment Receipt - Booth {application.booth_number}"
        
        # Email body (simple HTML message)
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #BF1F2F;">Payment Receipt</h2>
            
            <p>Dear <strong>{application.name}</strong>,</p>
            
            <p>Thank you for your payment! Please find attached your official payment receipt for <strong>Booth {application.booth_number}</strong> at the 4th Uganda - Kenya Coast Tourism Conference & Exhibition.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1d3557;">Payment Summary:</h3>
                <p><strong>Company:</strong> {application.company}</p>
                <p><strong>Booth Number:</strong> {application.booth_number}</p>
                <p><strong>Receipt Number:</strong> {application.paid_booth_receipt_number}</p>
                <p><strong>Total Amount:</strong> Ksh 58,000</p>
            </div>
            
            <p><strong>Important:</strong> Your conference tag and other credentials will be sent to you in a separate email shortly.</p>
            
            <p>If you have any questions regarding this receipt or your booth booking, please don't hesitate to contact us via WhatsApp: <small> 0708487510 (Polycarp) </small> .</p>
            
            <p>We look forward to seeing you at the conference!</p>
            
            <p style="margin-top: 30px;">
                Best regards,<br>
                <strong>BUZZ AFRIQUE LIMITED</strong><br>
                <em>Conference Organizers</em><br>
                +254 722 274707<br>
                accounts@buzzafrique.co.ke
            </p>
        </div>
        """
        
        # Plain text version
        text_body = f"""
        Payment Receipt
        
        Dear {application.name},
        
        Thank you for your payment! Please find attached your official payment receipt for Booth {application.booth_number} at the 4th Uganda - Kenya Coast Tourism Conference & Exhibition.
        
        Payment Summary:
        - Company: {application.company}
        - Booth Number: {application.booth_number}
        - Receipt Number: {application.paid_booth_receipt_number}
        - Total Amount: Ksh 58,000
        
        Important: Your booth participation tag and event credentials will be sent to you in a separate email shortly.
        
        If you have any questions regarding this receipt or your booth booking, please don't hesitate to contact us.
        
        We look forward to seeing you at the conference!
        
        Best regards,
        BUZZ AFRIQUE LIMITED
        Conference Organizers
        +254 722 274707
        accounts@buzzafrique.co.ke
        """
        
        # Create email with attachments
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[application.email],
            cc=PAID_BOOTH_CC_EMAILS  # CC the specified emails
        )
        
        # Attach HTML version
        email.attach_alternative(html_body, "text/html")
        
        # Attach PDF receipt
        full_pdf_path = os.path.join(settings.MEDIA_ROOT, pdf_path)
        if os.path.exists(full_pdf_path):
            email.attach_file(full_pdf_path)
        
        # Send email
        email.send()
        
        print(f"✅ Receipt email sent to {application.email} (CC: {', '.join(PAID_BOOTH_CC_EMAILS)})")
        return True
        
    except Exception as e:
        print(f"❌ Error sending receipt email: {str(e)}")
        return False

def send_paid_booth_approval_email(application, ticket):
    """
    Modified version of send_approval_email specifically for paid booth applications
    This sends the ticket email (separate from receipt)
    """
    subject = "Booth Application Approved - Your Event Tag"
    
    html_message = render_to_string('events/paid_booth_approved.html', {
        'application': application,
        'ticket': ticket,
        'admin_message': application.admin_message,
    })
    
    # Create email with PDF attachment
    email = EmailMultiAlternatives(
        subject=subject,
        body=f"""
        Dear {application.name},
        
        Great news! Your booth application has been approved.
        
        Please find attached your official event participation tag for Booth {application.booth_number}.
        
        Note: Your payment receipt was sent in a separate email.
        
        Best regards,
        BUZZ AFRIQUE LIMITED
        """,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[application.email],
    )
    
    email.attach_alternative(html_message, "text/html")
    
    # Attach PDF ticket if it exists
    if ticket.pdf_ticket:
        email.attach_file(ticket.pdf_ticket.path)
    
    email.send()
    print(f"✅ Approval/ticket email sent to {application.email}")








# scan stats

from django.http import JsonResponse
from django.db.models import Count, Q

def checkpoint_statistics(request, event_id):
    """
    Get statistics for all checkpoints for a specific event
    MATCHES the unified_reports_view calculation exactly
    """
    from events.models import ScanInstance, TicketScanLog, Ticket, PaidApplication
    
    # Get all scan instances for this event
    scan_instances = ScanInstance.objects.filter(event_id=event_id)
    
    # ==================== MATCH UNIFIED REPORTS EXACTLY ====================
    
    # 1. DELEGATES - Regular event tickets (no paid_application, no booth)
    delegate_tickets = Ticket.objects.filter(
        category__event_id=event_id
    ).count()
    
    # 2. BOOTHS - Count booked booths (not tickets!)
    from events.models import Booth
    booth_tickets = Booth.objects.filter(is_booked=True).count()
    
    # 3. MTN MONEY - Deduplicate exactly like unified reports
    paid_tickets = Ticket.objects.filter(
        paid_application__isnull=False,
        paid_application__status='approved'
    ).select_related('paid_application')
    
    # Deduplicate by name + email + phone (same as unified reports)
    seen_combinations = set()
    mtn_tickets = 0
    
    for ticket in paid_tickets:
        app = ticket.paid_application
        unique_key = (
            app.full_name.strip().lower() if app.full_name else '',
            app.email.strip().lower() if app.email else '',
            app.phone.strip() if app.phone else ''
        )
        
        if unique_key not in seen_combinations:
            seen_combinations.add(unique_key)
            mtn_tickets += 1
    
    # GRAND TOTAL - exactly like unified reports
    total_all_tickets = delegate_tickets + booth_tickets + mtn_tickets
    
    checkpoint_stats = []
    for instance in scan_instances:
        # Count UNIQUE tickets scanned at this checkpoint
        scanned_count = TicketScanLog.objects.filter(
            scan_instance=instance
        ).values('ticket').distinct().count()
        
        checkpoint_stats.append({
            'id': instance.id,
            'name': instance.name,
            'scanned': scanned_count,
            'remaining': total_all_tickets - scanned_count,
            'total': total_all_tickets
        })
    
    # Sort by name
    checkpoint_stats.sort(key=lambda x: x['name'])
    
    return JsonResponse({
        'total_tickets': total_all_tickets,
        'delegate_tickets': delegate_tickets,
        'mtn_tickets': mtn_tickets,
        'booth_tickets': booth_tickets,
        'checkpoints': checkpoint_stats
    })


def search_tickets(request):
    """
    Search for tickets by name, email, or ticket number
    """
    from django.db.models import Q
    from events.models import Ticket
    
    query = request.GET.get('query', '').strip()
    event_id = request.GET.get('event_id')
    
    if not query or len(query) < 2:
        return JsonResponse({'success': False, 'message': 'Query too short'})
    
    # Build search query
    tickets = Ticket.objects.filter(
        Q(order__event_id=event_id, order__is_paid=True) |
        Q(staff_application__event_id=event_id, staff_application__status='approved') |
        Q(paid_application__event_id=event_id, paid_application__status='approved') |
        Q(category__event_id=event_id)
        ).filter(
        Q(user__username__icontains=query) |
        Q(user__email__icontains=query) |
        Q(user__first_name__icontains=query) |
        Q(user__last_name__icontains=query) |
        Q(guest_name__icontains=query) |
        Q(guest_email__icontains=query) |
        Q(ticket_number__icontains=query)
    ).select_related('user', 'category').order_by('-created_at')[:20]
    
    results = []
    for ticket in tickets:
        # Generate the proper QR code format
        ticket_code = f"TICKET:{ticket.id}|EVENT:{event_id}"
        
        results.append({
            'ticket_code': ticket_code,  # Add this - the proper format
            'ticket_number': ticket.ticket_number,
            'holder_name': ticket.user.get_full_name() if ticket.user else (ticket.guest_name or 'Unknown'),
            'holder_email': ticket.user.email if ticket.user else (ticket.guest_email or 'N/A'),
            'holder_phone': ticket.guest_phone or (ticket.user.phone if hasattr(ticket.user, 'phone') and ticket.user else 'N/A'),
            'category': ticket.category.name if ticket.category else 'N/A',
            'is_used': ticket.is_used,
        })
    
    return JsonResponse({
        'success': True,
        'tickets': results
    })



from django.shortcuts import render, get_object_or_404, HttpResponseRedirect
from django.urls import reverse
from django import forms
from .models import Booth, BoothReview

class PublicReviewForm(forms.ModelForm):
    class Meta:
        model = BoothReview
        fields = ['rating', 'content', 'name', 'email', 'phone_number']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Write your review...'}),
            'rating': forms.Select(choices=[(i, f"{i} stars") for i in range(1, 6)]),
            'name': forms.TextInput(attrs={'placeholder': 'Your name (optional)'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Your email'}),
            'phone_number': forms.TextInput(attrs={'placeholder': 'Your phone number (optional)'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.booth = kwargs.pop('booth', None)
        super().__init__(*args, **kwargs)
        if self.user and self.user.is_authenticated:
            self.fields.pop('name')
            self.fields.pop('email')
            self.fields.pop('phone_number')

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('content').strip():
            raise forms.ValidationError("Review content cannot be empty.")
        if not self.user and not cleaned_data.get('email'):
            raise forms.ValidationError("Email is required for guest reviews.")
        if self.booth and cleaned_data.get('email') and BoothReview.objects.filter(booth=self.booth, email=cleaned_data['email']).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This email has already submitted a review for this booth.")
        return cleaned_data

def public_booth_review(request, token):
    booth = get_object_or_404(Booth, public_token=token)
    if request.method == 'POST':
        form = PublicReviewForm(request.POST, user=request.user, booth=booth)
        if form.is_valid():
            review = form.save(commit=False)
            review.booth = booth
            review.reviewer = request.user if request.user.is_authenticated else None
            review.ip_address = request.META.get('REMOTE_ADDR')
            review.save()
            return HttpResponseRedirect(reverse('review_success'))
    else:
        form = PublicReviewForm(user=request.user, booth=booth)
    return render(request, 'events/public_review.html', {'form': form, 'booth': booth})

def review_success(request):
    return render(request, 'events/review_success.html')



def public_booth_review(request, token):
    booth = get_object_or_404(Booth, public_token=token)
    if request.method == 'POST':
        form = PublicReviewForm(request.POST, user=request.user)
        if form.is_valid():
            review = form.save(commit=False)
            review.booth = booth
            review.reviewer = request.user if request.user.is_authenticated else None
            review.ip_address = request.META.get('REMOTE_ADDR')
            review.save()
            return HttpResponseRedirect(reverse('review_success'))
    else:
        form = PublicReviewForm(user=request.user)
    return render(request, 'events/public_review.html', {'form': form, 'booth': booth})

def review_success(request):
    return render(request, 'events/review_success.html')


def public_booth_review(request, token):
    booth = get_object_or_404(Booth, public_token=token)
    if request.method == 'POST':
        form = PublicReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.booth = booth
            review.reviewer = request.user if request.user.is_authenticated else None
            review.ip_address = request.META.get('REMOTE_ADDR')
            review.save()
            return HttpResponseRedirect(reverse('review_success'))
    else:
        form = PublicReviewForm()
    return render(request, 'events/public_review.html', {'form': form, 'booth': booth})




def review_success(request):
    return render(request, 'events/review_success.html')

from django.views.generic import ListView, DetailView



class SpeakerListView(ListView):
    model = Speaker
    template_name = 'events/speakers.html'
    context_object_name = 'speakers'
    
    def get_queryset(self):
        return Speaker.objects.filter(is_active=True)

class SpeakerDetailView(DetailView):
    model = Speaker
    template_name = 'events/speaker_detail.html'
    context_object_name = 'speaker'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        return Speaker.objects.filter(is_active=True)


from django.views.generic import ListView, DetailView
from django.db.models import Q
from .models import Blog, BlogCategory

class BlogListView(ListView):
    model = Blog
    template_name = 'events/blog_list.html'
    context_object_name = 'blogs'
    paginate_by = 9  # 9 blogs per page (3x3 grid)
    
    def get_queryset(self):
        queryset = Blog.objects.filter(is_published=True)
        
        # Filter by category if provided
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category__slug=category)
        
        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | 
                Q(excerpt__icontains=search) |
                Q(content__icontains=search) |
                Q(tags__icontains=search)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = BlogCategory.objects.all()
        context['featured_blogs'] = Blog.objects.filter(is_published=True, is_featured=True)[:3]
        return context


class BlogDetailView(DetailView):
    model = Blog
    template_name = 'events/blog_detail.html'
    context_object_name = 'blog'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        return Blog.objects.filter(is_published=True)
    
    def get_object(self):
        obj = super().get_object()
        # Increment view count
        obj.increment_views()
        return obj
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get related blogs (same category, exclude current)
        context['related_blogs'] = Blog.objects.filter(
            is_published=True,
            category=self.object.category
        ).exclude(id=self.object.id)[:3]
        return context

        