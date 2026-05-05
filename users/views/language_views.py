from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from users.models import Language
from users.constants.languages import LANGUAGES
import json


def _serialize_user_languages(user):
    langs = user.languages.all().order_by('name')
    return {
        'languages': [{'code': l.code, 'name': l.name} for l in langs]
    }

class LanguageOptionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        existing = {l.code for l in Language.objects.all()}
        to_create = [
            Language(code=code, name=name) for code, name in LANGUAGES if code not in existing
        ]
        if to_create:
            Language.objects.bulk_create(to_create, ignore_conflicts=True)

        options = [{'code': code, 'name': name} for code, name in LANGUAGES]
        return Response({'languages': options}, status=status.HTTP_200_OK)


class SetUserLanguagesView(APIView):
    """
    Unified endpoint to set the authenticated user's languages to the provided list.
    Accepts JSON (preferred) or form/multipart. Passing an empty list clears all languages.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        codes = []

        if hasattr(request.data, 'getlist'):
            repeated = request.data.getlist('codes')
            if repeated:
                codes = repeated

        if not codes:
            raw = request.data.get('codes')
            if isinstance(raw, list):
                codes = raw
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        codes = parsed
                    else:
                        codes = [p.strip() for p in raw.split(',') if p.strip()]
                except Exception:
                    codes = [p.strip() for p in raw.split(',') if p.strip()]
            else:
                codes = []  
                
        valid_codes = {code for code, _ in LANGUAGES}
        invalid = [c for c in codes if c not in valid_codes]
        if invalid:
            return Response({'error': f'Invalid codes: {", ".join(invalid)}'}, status=status.HTTP_400_BAD_REQUEST)

        code_to_name = {code: name for code, name in LANGUAGES}
        for code in codes:
            Language.objects.get_or_create(code=code, defaults={'name': code_to_name[code]})

        if len(codes) == 0:
            request.user.languages.clear()
        else:
            qs = Language.objects.filter(code__in=codes)
            request.user.languages.set(list(qs))

        return Response(_serialize_user_languages(request.user), status=status.HTTP_200_OK)