from django.contrib.auth.backends import BaseBackend

from .models import User


class DiscordSessionBackend(BaseBackend):
    """Restores OAuth-created sessions. No password authentication or superuser bypass."""

    def get_user(self, user_id):
        return User.objects.filter(pk=user_id, is_active=True).first()
