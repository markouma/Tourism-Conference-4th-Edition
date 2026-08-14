
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('events.urls')),
    path('controlpanel/', include('controlpanel.urls')),
        path('', include('exhibitor_feedback.urls')),

]
urlpatterns += staticfiles_urlpatterns()  # ✅ This serves from STATICFILES_DIRS
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
handler404 = 'events.views.custom_404_view'
