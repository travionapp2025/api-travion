import json
import re
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from ..models import User
from ..models import Language
from ..constants.languages import LANGUAGES


class SignupView(View):
    """
    Simple user registration view with JWT tokens
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        
        # Extract data
        email = data.get('email', '').strip().lower()
        firstname = data.get('firstname', '').strip()
        lastname = data.get('lastname', '').strip()
        phonenumber = data.get('phonenumber', '').strip()
        password = data.get('password', '')
        password_confirm = data.get('password_confirm', '')
        role = data.get('role', 'seeker')
        gender = data.get('gender')
        languages = data.get('languages')
        fcm_token = data.get('fcm_token', '').strip()
        device_type = data.get('device_type', 'android')
        
        # Validation errors
        errors = {}
        
        # Email validation
        if not email:
            errors['email'] = 'Email is required'
        elif not self._is_valid_email(email):
            errors['email'] = 'Enter a valid email address'
        elif User.objects.filter(email=email).exists():
            errors['email'] = 'A user with this email already exists'
        
        if not firstname or len(firstname) < 2:
            errors['firstname'] = 'First name is required and must be at least 2 characters'
        if not lastname or len(lastname) < 2:
            errors['lastname'] = 'Last name is required and must be at least 2 characters'
        
        if phonenumber and not self._is_valid_phone(phonenumber):
            errors['phonenumber'] = 'Enter a valid phone number'
        
        if not password:
            errors['password'] = 'Password is required'
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                errors['password'] = list(e.messages)
        
        if password != password_confirm:
            errors['password_confirm'] = "Passwords don't match"
        
        if role not in ['seeker', 'provider', 'both']:
            errors['role'] = 'Role must be seeker, provider, or both'
        
        if not fcm_token:
            errors['fcm_token'] = 'FCM token is required for signup'
        elif len(fcm_token) < 10:
            errors['fcm_token'] = 'Invalid FCM token format'
        
        # Device type validation
        if device_type not in ['android', 'ios', 'web']:
            errors['device_type'] = 'Device type must be android, ios, or web'

        if gender is not None:
            valid_genders = {choice[0] for choice in User.GENDER_CHOICES}
            if gender not in valid_genders:
                errors['gender'] = f"Invalid gender. Allowed: {', '.join(sorted(valid_genders))}"

        # Languages validation
        if languages is not None:
            if not isinstance(languages, list):
                errors['languages'] = 'Languages must be a list of codes'
            else:
                valid_codes = {code for code, _ in LANGUAGES}
                invalid = [c for c in languages if c not in valid_codes]
                if invalid:
                    errors['languages'] = f"Invalid language codes: {', '.join(invalid)}"
        
        if errors:
            return JsonResponse({'error': 'Validation failed', 'errors': errors}, status=400)
        
        try:
            user = User.objects.create_user(
                email=email,
                firstname=firstname,
                lastname=lastname,
                phonenumber=phonenumber or None,
                role=role,
                gender=gender,
                password=password
            )
            if isinstance(languages, list) and languages:
                code_to_name = {code: name for code, name in LANGUAGES}
                for code in languages:
                    lang, _ = Language.objects.get_or_create(code=code, defaults={'name': code_to_name[code]})
                    user.languages.add(lang)
            
            from ..models import DeviceToken
            DeviceToken.objects.update_or_create(
                user=user,
                token=fcm_token,
                defaults={'device_type': device_type, 'is_active': True}
            )
            
            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token
            
            return JsonResponse({
                'message': 'User registered successfully',
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'firstname': user.firstname,
                    'lastname': user.lastname,
                    'phonenumber': user.phonenumber,
                    'role': user.role,
                    'gender': user.gender,
                    'languages': [
                        {'code': l.code, 'name': l.name} for l in user.languages.all().order_by('name')
                    ],
                    'full_name': user.full_name
                },
                'tokens': {
                    'access': str(access_token),
                    'refresh': str(refresh)
                }
            }, status=201)
            
        except Exception as e:
            return JsonResponse({'error': 'Failed to create user', 'details': str(e)}, status=500)
    
    def _is_valid_email(self, email):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _is_valid_phone(self, phone):
        digits_only = re.sub(r'\D', '', phone)
        return 10 <= len(digits_only) <= 15