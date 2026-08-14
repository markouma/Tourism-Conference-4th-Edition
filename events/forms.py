from django import forms
from .models import Event, TicketCategory, StaffApplication, PaidApplication, Ticket , PaidBoothApplication
from django.forms import formset_factory
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from .models import BoothApplication, BoothRepresentative







class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['name', 'location', 'poster', 'date', 'description']
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }



class TicketCategoryForm(forms.ModelForm):
    class Meta:
        model = TicketCategory
        fields = ['name', 'price', 'available_tickets']


TicketCategoryFormSet = inlineformset_factory(
    parent_model=Event,
    model=TicketCategory,
    form=TicketCategoryForm,
    fields=['name', 'price', 'available_tickets'],
    extra=1,
    can_delete=True
    
)
 

# staff application 
class StaffApplicationForm(forms.ModelForm):
    media_number = forms.CharField(required=False, label="Media Council Number")

    class Meta:
        model = StaffApplication
        fields = [
            'full_name', 'email', 'phone', 'role',
            'company', 'designation', 'photo', 'media_number',
            'country', 'city', 'age_range', 'consent', 'tshirt_size',
            'referral_source', 'sector'
        ]
        widgets = {
            'consent': forms.CheckboxInput(attrs={'required': True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True

        self.fields['media_number'].required = False
        self.fields['consent'].required = True
        self.fields['country'].required = False
        self.fields['city'].required = False
        self.fields['referral_source'].required = False
        self.fields['sector'].required = False

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        media_number = cleaned_data.get('media_number')
        email = cleaned_data.get('email')
        consent = cleaned_data.get('consent')

        if StaffApplication.objects.filter(email=email).exists():
            raise ValidationError({'email': "An application with this email already exists."})

        if role == 'media' and not media_number:
            self.add_error('media_number', 'Media Number is required for Media applicants.')

        if not consent:
            self.add_error('consent', 'You must agree to the consent terms.')

        return cleaned_data


class PaidApplicationForm(forms.ModelForm):
    mpesa_code = forms.CharField(label="M-Pesa Transaction Code")
    
    class Meta:
        model = PaidApplication
        fields = [
            'full_name', 'email', 'phone', 
            'company', 'designation', 'photo',
            'country', 'city', 'age_range', 'consent',
            'tshirt_size', 'referral_source', 'sector', 'mpesa_code'
        ]
        widgets = {
            'consent': forms.CheckboxInput(attrs={'required': True}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make ALL fields required
        for field_name in self.fields:
            self.fields[field_name].required = True
        
        # Special handling for consent checkbox error message
        self.fields['consent'].error_messages = {
            'required': 'You must give consent to proceed'
        }
    
    def clean(self):
        cleaned_data = super().clean()
        mpesa_code = cleaned_data.get('mpesa_code')

        if mpesa_code and PaidApplication.objects.filter(mpesa_code=mpesa_code).exists():
            raise ValidationError({
                'mpesa_code': "This M-Pesa code has already been used. Check your email or wait for approval."
            })

        return cleaned_data




class BoothRegistrationRequestForm(forms.Form):
    # For admin / booking email flow (optional UI)
    booth_name = forms.CharField(max_length=100, disabled=True)
    company_name = forms.CharField(max_length=150, disabled=True)

class DelegateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            "guest_name", "guest_email", "guest_phone",
            "company_name", "designation", "industry", "city", "country", "attendee_photo"
        ]
        widgets = {
            "guest_name": forms.TextInput(attrs={"placeholder": "Full name"}),
            "guest_email": forms.EmailInput(attrs={"placeholder": "Email"}),
            "guest_phone": forms.TextInput(attrs={"placeholder": "Phone"}),
        }

# helper factory: maximum 2 forms
DelegateFormSet = formset_factory(DelegateForm, extra=0, max_num=2, validate_max=True)




class BoothApplicationForm(forms.ModelForm):
    class Meta:
        model = BoothApplication
        fields = ['booth_number', 'company']


class BoothRepresentativeForm(forms.ModelForm):
    class Meta:
        model = BoothRepresentative
        exclude = ['application']
        widgets = {
            'photo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # enforce all fields required
        for field_name, field in self.fields.items():
            field.required = True



class PaidBoothApplicationForm(forms.ModelForm):
    """
    This form handles the user application for booth representatives
    It's based on our PaidBoothApplication model
    """
    
    class Meta:
        model = PaidBoothApplication
        fields = [
            'booth_number',
            'payment_message', 
            'name',
            'email',
            'phone_number',
            'company',
            'title_designation',
            'country',
            'city', 
            'industry',
            'consent_given',
            'profile_image',
            'kra_pin',
        ]
        
        # Custom labels (what users see on the form)
        labels = {
            'booth_number': 'Booth Number',
            'payment_message': 'Payment Message/Code',
            'name': 'Full Name',
            'email': 'Email Address',
            'phone_number': 'Phone Number',
            'company': 'Company Name',
            'title_designation': 'Title/Designation',
            'country': 'Country',
            'city': 'City',
            'industry': 'Industry',
            'consent_given': 'I agree to the terms and conditions',
            'profile_image': 'Upload Your Photo',
            'kra_pin': 'Tax Identification Number(TIN)/KRA PIN',
        }
        
        # Custom widgets (how the form fields look)
        widgets = {
            'booth_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., B1'
            }),

            'payment_message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter your payment confirmation code or message'
            }),
            'profile_image': forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'your.email@company.com'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+254700000000'
            }),
            'company': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your company name'
            }),
            'kra_pin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., A123456789B'
            }),
            'title_designation': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Sales Manager, CEO'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Kenya'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nairobi'
            }),
            'industry': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Technology, Healthcare'
            }),
            'consent_given': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        
        # Help text for fields
        help_texts = {
            'booth_number': 'The booth number assigned to your company',
            'payment_message': 'Provide payment confirmation details or transaction code',
            'consent_given': 'Required to process your application',
            'profile_image': 'This photo will appear on your tag',
            'kra_pin': 'Required for payment receipts and invoicing'
        }

    def clean_consent_given(self):
        """
        Custom validation: Make sure they checked the consent box
        Django calls this automatically when form is submitted
        """
        consent = self.cleaned_data.get('consent_given')
        if not consent:
            raise ValidationError("You must agree to the terms and conditions to proceed.")
        return consent
    
    def clean_email(self):
        """
        Custom validation: Check if email already has a pending/approved application
        Prevents duplicate applications
        """
        email = self.cleaned_data.get('email')
        
        # Check if this email already has a pending or approved application
        existing_application = PaidBoothApplication.objects.filter(
            email='email',
            status__in=['pending', 'approved']
        ).first()
        
        if existing_application:
            if existing_application.status == 'pending':
                raise ValidationError("You already have a pending application with this email.")
            elif existing_application.status == 'approved':
                raise ValidationError("You already have an approved application with this email.")
        
        return email
    
     
    def clean_booth_number(self):
        """
        Custom validation: Check if booth number is already taken
        """
        booth_number = self.cleaned_data.get('booth_number')
        
        # Check if this booth number already has an approved application
        existing_application = PaidBoothApplication.objects.filter(
            booth_number=booth_number,
            status='approved'
        ).first()
        
        if existing_application:
            raise ValidationError(f"Booth {booth_number} is already assigned to another representative.")
        
        return booth_number

