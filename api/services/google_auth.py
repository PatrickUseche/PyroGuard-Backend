from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token

from api.models import GoogleAccount
from api.services.users import build_username


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


def get_or_create_user(email, google_sub, given_name=None):
    user_model = get_user_model()
    try:
        with transaction.atomic():
            account = _find_account(google_sub)
            if account is not None:
                return account.user

            user = user_model._default_manager.filter(email__iexact=email).first()
            if user is None:
                user_manager = user_model._default_manager
                user = user_manager.create_user(
                    username=build_username(
                        email,
                        lambda username: user_manager.filter(
                            username__iexact=username
                        ).exists(),
                    ),
                    email=email,
                    is_staff=False,
                    is_superuser=False,
                )
                user.set_unusable_password()
                update_fields = ["password"]
                if isinstance(given_name, str):
                    user.first_name = given_name[:150]
                    update_fields.append("first_name")
                user.save(update_fields=update_fields)

            GoogleAccount.objects.create(user=user, google_sub=google_sub)
            return user
    except IntegrityError:
        account = _find_account(google_sub)
        if account is not None:
            return account.user

        user = user_model._default_manager.filter(email__iexact=email).first()
        if user is not None:
            account = GoogleAccount.objects.filter(user=user).first()
            if account is not None and account.google_sub == google_sub:
                return user
            if account is None:
                try:
                    with transaction.atomic():
                        GoogleAccount.objects.create(
                            user=user,
                            google_sub=google_sub,
                        )
                except IntegrityError:
                    account = _find_account(google_sub)
                    if account is not None:
                        return account.user
                    raise
                return user
        raise
