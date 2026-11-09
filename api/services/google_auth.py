from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token

from api.models import GoogleAccount


def verify_credential(credential, client_id):
    return verify_oauth2_token(
        credential,
        Request(),
        client_id,
        clock_skew_in_seconds=10,
    )


def _find_account(google_sub):
    return (
        GoogleAccount.objects.select_related("user")
        .filter(google_sub=google_sub)
        .first()
    )


def get_existing_user(email, google_sub):
    user_model = get_user_model()
    try:
        with transaction.atomic():
            account = _find_account(google_sub)
            if account is not None:
                return account.user

            user = user_model._default_manager.filter(email__iexact=email).first()
            if user is None:
                return None

            account = GoogleAccount.objects.filter(user=user).first()
            if account is None:
                GoogleAccount.objects.create(user=user, google_sub=google_sub)
            return user
    except IntegrityError:
        account = _find_account(google_sub)
        if account is not None:
            return account.user

        user = user_model._default_manager.filter(email__iexact=email).first()
        if user is not None:
            account = GoogleAccount.objects.filter(user=user).first()
            if account is not None:
                return user
        return None
