from django.shortcuts import render

def privacy_policy(request):
    return render(request, 'privacy-policy.html')

def terms_and_conditions(request):
    return render(request, 'terms-and-conditions.html')