"""Pruebas de los canales de notificación con envío simulado."""
import os
from unittest.mock import MagicMock, patch

import requests
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from config.settings import _env_choice_list

from .notifications.base import Notification, NotificationError, Notifier
from .notifications.console import ConsoleNotifier
from .notifications.email_channel import EmailNotifier
from .notifications.registry import CHANNELS, active_notifiers
from .notifications.telegram_channel import TelegramNotifier


def notification(**overrides):
    values = dict(subject="Incendio en NODE-001", message="Humo y llama detectados.", node_id="NODE-001", priority=1)
    values.update(overrides)
    return Notification(**values)


class NotifierInterfaceTests(SimpleTestCase):
    def test_the_interface_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            Notifier()

    def test_a_channel_is_configured_by_default(self):
        class Minimal(Notifier):
            name = "minimal"

            def send(self, notification):
                pass

        self.assertTrue(Minimal().is_configured())

    def test_notifications_are_immutable(self):
        with self.assertRaises(Exception):
            notification().subject = "otro"

    def test_every_channel_has_a_unique_name(self):
        self.assertEqual(set(CHANNELS), {"console", "email", "telegram"})
        for name, channel in CHANNELS.items():
            self.assertEqual(channel.name, name)


class ConsoleNotifierTests(SimpleTestCase):
    def test_writes_the_notice_to_the_log(self):
        with self.assertLogs("api.notifications", level="WARNING") as logs:
            ConsoleNotifier().send(notification(priority=2))

        self.assertIn("prioridad 2", logs.output[0])
        self.assertIn("Incendio en NODE-001", logs.output[0])
        self.assertIn("Humo y llama detectados.", logs.output[0])

    def test_it_is_always_configured(self):
        self.assertTrue(ConsoleNotifier().is_configured())


@override_settings(
    NOTIFY_EMAIL_TO=["ops@example.com", "guardia@example.com"],
    DEFAULT_FROM_EMAIL="pyroguard@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailNotifierTests(SimpleTestCase):
    def test_sends_one_email_to_every_recipient(self):
        EmailNotifier().send(notification())

        (message,) = mail.outbox
        self.assertEqual(message.subject, "[PyroGuard] Incendio en NODE-001")
        self.assertEqual(message.body, "Humo y llama detectados.")
        self.assertEqual(message.from_email, "pyroguard@example.com")
        self.assertEqual(message.to, ["ops@example.com", "guardia@example.com"])

    @override_settings(NOTIFY_EMAIL_TO=[])
    def test_it_is_not_configured_without_recipients(self):
        self.assertFalse(EmailNotifier().is_configured())

    def test_it_is_configured_with_recipients(self):
        self.assertTrue(EmailNotifier().is_configured())

    def test_a_smtp_failure_becomes_a_notification_error_without_details(self):
        with patch("api.notifications.email_channel.send_mail", side_effect=OSError("clave=secreta")):
            with self.assertRaises(NotificationError) as raised:
                EmailNotifier().send(notification())

        self.assertIn("OSError", str(raised.exception))
        self.assertNotIn("secreta", str(raised.exception))

    def test_a_rejected_message_is_an_error(self):
        with patch("api.notifications.email_channel.send_mail", return_value=0):
            with self.assertRaises(NotificationError):
                EmailNotifier().send(notification())


@override_settings(TELEGRAM_BOT_TOKEN="123:SECRETO", TELEGRAM_CHAT_ID="-1001")
class TelegramNotifierTests(SimpleTestCase):
    def test_posts_to_the_bot_api_with_the_chat_and_text(self):
        with patch("api.notifications.telegram_channel.requests.post", return_value=MagicMock(status_code=200)) as post:
            TelegramNotifier().send(notification())

        (url,), kwargs = post.call_args
        self.assertEqual(url, "https://api.telegram.org/bot123:SECRETO/sendMessage")
        self.assertEqual(kwargs["json"]["chat_id"], "-1001")
        self.assertEqual(kwargs["json"]["text"], "Incendio en NODE-001\n\nHumo y llama detectados.")
        self.assertEqual(kwargs["timeout"], 10)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_it_is_not_configured_without_a_token(self):
        self.assertFalse(TelegramNotifier().is_configured())

    @override_settings(TELEGRAM_CHAT_ID="")
    def test_it_is_not_configured_without_a_chat(self):
        self.assertFalse(TelegramNotifier().is_configured())

    def test_it_is_configured_with_both(self):
        self.assertTrue(TelegramNotifier().is_configured())

    def test_a_network_failure_does_not_leak_the_token(self):
        error = requests.ConnectionError("fallo en https://api.telegram.org/bot123:SECRETO/sendMessage")
        with patch("api.notifications.telegram_channel.requests.post", side_effect=error):
            with self.assertRaises(NotificationError) as raised:
                TelegramNotifier().send(notification())

        self.assertIn("ConnectionError", str(raised.exception))
        self.assertNotIn("SECRETO", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_a_non_200_answer_is_an_error_without_the_token(self):
        with patch("api.notifications.telegram_channel.requests.post", return_value=MagicMock(status_code=401)):
            with self.assertRaises(NotificationError) as raised:
                TelegramNotifier().send(notification())

        self.assertIn("401", str(raised.exception))
        self.assertNotIn("SECRETO", str(raised.exception))


class ActiveNotifiersTests(SimpleTestCase):
    @override_settings(NOTIFICATION_CHANNELS=["console"])
    def test_only_the_listed_channels_are_used(self):
        self.assertEqual([n.name for n in active_notifiers()], ["console"])

    @override_settings(
        NOTIFICATION_CHANNELS=["console", "email", "telegram"],
        NOTIFY_EMAIL_TO=["ops@example.com"],
        TELEGRAM_BOT_TOKEN="t",
        TELEGRAM_CHAT_ID="c",
    )
    def test_all_configured_channels_are_returned_in_order(self):
        self.assertEqual([n.name for n in active_notifiers()], ["console", "email", "telegram"])

    @override_settings(NOTIFICATION_CHANNELS=["console", "email", "telegram"], NOTIFY_EMAIL_TO=[],
                       TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_channels_without_configuration_are_skipped_with_a_warning(self):
        with self.assertLogs("api.notifications", level="WARNING") as logs:
            names = [n.name for n in active_notifiers()]

        self.assertEqual(names, ["console"])
        self.assertEqual(len(logs.output), 2)


class ChannelSettingsTests(SimpleTestCase):
    CHOICES = {"console", "email", "telegram"}

    def parse(self, value):
        with patch.dict(os.environ, {"NOTIFICATION_CHANNELS": value}):
            return _env_choice_list("NOTIFICATION_CHANNELS", self.CHOICES, default=["console"])

    def test_empty_uses_the_default(self):
        self.assertEqual(self.parse(""), ["console"])
        self.assertEqual(self.parse("  "), ["console"])

    def test_a_list_is_parsed_without_repeats(self):
        self.assertEqual(self.parse("console, telegram,console"), ["console", "telegram"])

    def test_unknown_channels_are_rejected(self):
        with self.assertRaises(ImproperlyConfigured) as raised:
            self.parse("console,sms")

        self.assertIn("sms", str(raised.exception))
