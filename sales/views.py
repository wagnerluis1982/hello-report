from django.shortcuts import render

from .models import Invoice


def index(request):
    invoices = Invoice.objects.all()
    context = {'invoices': invoices}

    return render(request, 'sales/index.html', context)
