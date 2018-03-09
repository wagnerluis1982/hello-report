from django.contrib import admin

from .models import Invoice, Tax

admin.site.register(Invoice)
admin.site.register(Tax)
