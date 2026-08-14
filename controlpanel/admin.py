from django.contrib import admin
from events.models import Booth, BoothVisit, BoothReview, BoothReviewHistory


@admin.register(Booth)
class BoothAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price', 'is_booked', 'booked_by', 'order', 'booked_at', 'public_token', 'public_qr_code')
    list_filter = ('event', 'is_booked')
    search_fields = ('name', 'booked_by__email', 'order__id')
    readonly_fields = ('public_token', 'qr_code', 'booth_qr_code', 'public_qr_code')
    fields = ('event', 'name', 'price', 'is_booked', 'booked_by', 'booked_at', 'reserved_until', 'pdf_ticket', 'qr_code', 'booth_qr_code', 'public_qr_code', 'order', 'public_token')

@admin.register(BoothVisit)
class BoothVisitAdmin(admin.ModelAdmin):
    list_display = ('booth', 'visitor', 'scanned_at')
    list_filter = ('booth', 'scanned_at')
    search_fields = ('visitor__email', 'booth__name')

@admin.register(BoothReview)
class BoothReviewAdmin(admin.ModelAdmin):
    list_display = ('booth', 'reviewer', 'name', 'email', 'phone_number', 'rating', 'content', 'ip_address', 'created_at', 'has_been_edited')
    list_filter = ('booth', 'rating')
    search_fields = ('reviewer__email', 'booth__name', 'content', 'name', 'email', 'phone_number')
    readonly_fields = ('created_at', 'edited_at')

    def has_been_edited(self, obj):
        return obj.edited_at > obj.created_at
    has_been_edited.boolean = True
    has_been_edited.short_description = 'Edited'

    def has_add_permission(self, request):
        return False  # No adding from admin

@admin.register(BoothReviewHistory)
class BoothReviewHistoryAdmin(admin.ModelAdmin):
    list_display = ('review', 'rating', 'timestamp')
    search_fields = ('review__reviewer__email', 'review__booth__name', 'content')