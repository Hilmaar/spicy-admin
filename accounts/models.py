from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, discord_id, **extra_fields):
        user = self.model(discord_id=discord_id, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    discord_id = models.CharField(max_length=20, unique=True)
    username = models.CharField(max_length=80)
    display_name = models.CharField(max_length=80, blank=True)
    avatar = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    USERNAME_FIELD = "discord_id"
    objects = UserManager()

    @property
    def name(self):
        return self.display_name or self.username

    @property
    def avatar_url(self):
        if self.avatar:
            return f"https://cdn.discordapp.com/avatars/{self.discord_id}/{self.avatar}.png?size=80"
        index = (int(self.discord_id) >> 22) % 6
        return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


class GuildAuthorization(models.Model):
    """Shared across Gunicorn workers; never keep an OAuth token in this record."""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    guild_id = models.CharField(max_length=20)
    roles = models.JSONField(default=list)
    is_member = models.BooleanField(default=False)
    unavailable = models.BooleanField(default=False)
    checked_at = models.DateTimeField()
