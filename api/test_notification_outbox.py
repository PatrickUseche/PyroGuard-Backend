"""Pruebas de la cola de avisos: prioridad, ventana de silencio, envío y alertas FIRE."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Alert, Node, NotificationOutbox, RiskAssessment, SensorReading
from .notifications.base import Notification, NotificationError, Notifier
from .notifications.outbox import enqueue, pending_heap, send_pending
from .services.alerts import maybe_create_alert

FIRE = NotificationOutbox.Kind.FIRE_ALERT
OFFLINE = NotificationOutbox.Kind.OFFLINE_ALERT


class RecordingNotifier(Notifier):
    def __init__(self, name="recorder", fail_times=0):
        self.name = name
        self.fail_times = fail_times
        self.sent = []

    def send(self, notification):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise NotificationError(f"{self.name} caído")
        self.sent.append(notification)


@override_settings(NOTIFICATION_COOLDOWN_SECONDS=0, NOTIFICATION_MAX_ATTEMPTS=3)
class OutboxBase(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")
        self.other = Node.objects.create(node_id="NODE-002")

    def age(self, row, seconds):
        NotificationOutbox.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(seconds=seconds))
        row.refresh_from_db()
        return row


class PriorityQueueTests(OutboxBase):
    def test_enqueue_stores_a_pending_notice_with_its_priority(self):
        fire = enqueue(FIRE, self.node, "Incendio", "Detalle")
        offline = enqueue(OFFLINE, self.other, "Sin señal", "Detalle")

        self.assertEqual((fire.priority, fire.status, fire.attempts), (1, "PENDING", 0))
        self.assertEqual(offline.priority, 2)
        self.assertEqual(fire.node, self.node)

    def test_the_subject_is_cut_to_the_column_size(self):
        row = enqueue(FIRE, self.node, "x" * 500, "Detalle")

        self.assertEqual(len(row.subject), 200)

    def test_the_heap_puts_the_most_urgent_first(self):
        offline = enqueue(OFFLINE, self.node, "Sin señal", "d")
        fire = enqueue(FIRE, self.other, "Incendio", "d")

        heap = pending_heap()

        self.assertEqual([heap.pop().pk, heap.pop().pk], [fire.pk, offline.pk])

    def test_with_equal_priority_the_oldest_comes_first(self):
        newer = enqueue(FIRE, self.node, "Nuevo", "d")
        older = self.age(enqueue(FIRE, self.other, "Viejo", "d"), 600)

        heap = pending_heap()

        self.assertEqual([heap.pop().pk, heap.pop().pk], [older.pk, newer.pk])

    def test_urgency_beats_age(self):
        old_offline = self.age(enqueue(OFFLINE, self.node, "Sin señal", "d"), 3600)
        new_fire = enqueue(FIRE, self.other, "Incendio", "d")

        self.assertEqual(pending_heap().pop().pk, new_fire.pk)
        self.assertEqual(old_offline.priority, 2)

    def test_only_pending_notices_are_in_the_heap(self):
        sent = enqueue(FIRE, self.node, "Enviado", "d")
        NotificationOutbox.objects.filter(pk=sent.pk).update(status="SENT")
        pending = enqueue(FIRE, self.other, "Pendiente", "d")

        heap = pending_heap()

        self.assertEqual(len(heap), 1)
        self.assertEqual(heap.pop().pk, pending.pk)

    def test_the_limit_loads_only_the_oldest_notices(self):
        rows = [self.age(enqueue(FIRE, self.node, f"A{n}", "d"), 1000 - n) for n in range(5)]

        heap = pending_heap(limit=2)

        self.assertEqual(sorted(row.pk for row in (heap.pop(), heap.pop())), [rows[0].pk, rows[1].pk])
        self.assertTrue(heap.is_empty())

    def test_an_empty_queue_gives_an_empty_heap(self):
        self.assertTrue(pending_heap().is_empty())


@override_settings(NOTIFICATION_COOLDOWN_SECONDS=300)
class SlidingWindowTests(OutboxBase):
    def test_a_repeated_notice_inside_the_window_is_dropped(self):
        first = enqueue(FIRE, self.node, "Incendio", "d")

        second = enqueue(FIRE, self.node, "Incendio otra vez", "d")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_the_window_counts_notices_already_sent(self):
        first = enqueue(FIRE, self.node, "Incendio", "d")
        NotificationOutbox.objects.filter(pk=first.pk).update(status="SENT")

        self.assertIsNone(enqueue(FIRE, self.node, "Incendio", "d"))

    def test_after_the_window_a_new_notice_is_allowed(self):
        self.age(enqueue(FIRE, self.node, "Incendio", "d"), 301)

        self.assertIsNotNone(enqueue(FIRE, self.node, "Incendio", "d"))

    def test_just_inside_the_window_is_still_dropped(self):
        self.age(enqueue(FIRE, self.node, "Incendio", "d"), 299)

        self.assertIsNone(enqueue(FIRE, self.node, "Incendio", "d"))

    def test_the_window_slides_with_each_new_notice(self):
        self.age(enqueue(FIRE, self.node, "Primero", "d"), 400)
        second = enqueue(FIRE, self.node, "Segundo", "d")
        self.assertIsNotNone(second)

        self.assertIsNone(enqueue(FIRE, self.node, "Tercero", "d"))
        self.age(second, 400)
        self.assertIsNotNone(enqueue(FIRE, self.node, "Cuarto", "d"))

    def test_other_nodes_and_other_kinds_are_independent(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        self.assertIsNotNone(enqueue(FIRE, self.other, "Incendio", "d"))
        self.assertIsNotNone(enqueue(OFFLINE, self.node, "Sin señal", "d"))

    @override_settings(NOTIFICATION_COOLDOWN_SECONDS=0)
    def test_zero_turns_the_window_off(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        self.assertIsNotNone(enqueue(FIRE, self.node, "Incendio", "d"))

    def test_a_notice_without_a_node_is_never_dropped(self):
        enqueue(FIRE, None, "General", "d")

        self.assertIsNotNone(enqueue(FIRE, None, "General", "d"))


class SendingTests(OutboxBase):
    def test_notices_are_sent_most_urgent_first(self):
        offline = enqueue(OFFLINE, self.node, "Sin señal", "d")
        fire = enqueue(FIRE, self.other, "Incendio", "d")
        notifier = RecordingNotifier()

        result = send_pending(notifiers=[notifier])

        self.assertEqual([n.subject for n in notifier.sent], ["Incendio", "Sin señal"])
        self.assertEqual(result.sent, 2)
        for row in (offline, fire):
            row.refresh_from_db()
            self.assertEqual(row.status, "SENT")
            self.assertIsNotNone(row.sent_at)
            self.assertEqual(row.delivered_channels, ["recorder"])

    def test_the_notification_carries_the_node_and_priority(self):
        enqueue(FIRE, self.node, "Incendio", "Detalle")
        notifier = RecordingNotifier()

        send_pending(notifiers=[notifier])

        self.assertEqual(
            notifier.sent[0],
            Notification(subject="Incendio", message="Detalle", node_id="NODE-001", priority=1),
        )

    def test_a_sent_notice_is_not_sent_again(self):
        enqueue(FIRE, self.node, "Incendio", "d")
        notifier = RecordingNotifier()
        send_pending(notifiers=[notifier])

        send_pending(notifiers=[notifier])

        self.assertEqual(len(notifier.sent), 1)

    def test_it_goes_to_every_active_channel(self):
        enqueue(FIRE, self.node, "Incendio", "d")
        first, second = RecordingNotifier("uno"), RecordingNotifier("dos")

        send_pending(notifiers=[first, second])

        self.assertEqual((len(first.sent), len(second.sent)), (1, 1))
        self.assertEqual(NotificationOutbox.objects.get().delivered_channels, ["uno", "dos"])

    def test_a_failing_channel_is_retried_without_repeating_the_others(self):
        enqueue(FIRE, self.node, "Incendio", "d")
        good, flaky = RecordingNotifier("bueno"), RecordingNotifier("flojo", fail_times=1)

        first = send_pending(notifiers=[good, flaky])
        row = NotificationOutbox.objects.get()
        self.assertEqual((first.sent, first.retrying), (0, 1))
        self.assertEqual((row.status, row.attempts, row.delivered_channels), ("PENDING", 1, ["bueno"]))
        self.assertIn("flojo caído", row.last_error)

        second = send_pending(notifiers=[good, flaky])
        row.refresh_from_db()
        self.assertEqual(second.sent, 1)
        self.assertEqual(row.status, "SENT")
        self.assertEqual(len(good.sent), 1)   # no se repitió en el canal que ya había funcionado
        self.assertEqual(len(flaky.sent), 1)
        self.assertEqual(row.last_error, "")

    def test_after_the_maximum_attempts_it_is_marked_failed(self):
        enqueue(FIRE, self.node, "Incendio", "d")
        flaky = RecordingNotifier("flojo", fail_times=99)

        results = [send_pending(notifiers=[flaky]) for _ in range(3)]

        row = NotificationOutbox.objects.get()
        self.assertEqual([r.retrying for r in results], [1, 1, 0])
        self.assertEqual(results[-1].failed, 1)
        self.assertEqual((row.status, row.attempts), ("FAILED", 3))
        self.assertTrue(row.last_error)
        self.assertTrue(pending_heap().is_empty())

    def test_without_active_channels_the_notice_fails(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        result = send_pending(notifiers=[])

        self.assertEqual(result.failed, 1)
        self.assertEqual(NotificationOutbox.objects.get().last_error, "No hay canales activos.")

    @override_settings(NOTIFICATION_CHANNELS=["console"])
    def test_by_default_it_uses_the_configured_channels(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        with self.assertLogs("api.notifications", level="WARNING") as logs:
            result = send_pending()

        self.assertEqual(result.sent, 1)
        self.assertIn("Incendio", logs.output[0])

    def test_the_limit_caps_one_run(self):
        for number in range(4):
            enqueue(FIRE, self.node, f"A{number}", "d")
        notifier = RecordingNotifier()

        send_pending(limit=3, notifiers=[notifier])

        self.assertEqual(len(notifier.sent), 3)
        self.assertEqual(NotificationOutbox.objects.filter(status="PENDING").count(), 1)

    def test_an_empty_queue_sends_nothing(self):
        notifier = RecordingNotifier()

        result = send_pending(notifiers=[notifier])

        self.assertEqual((result.sent, result.failed, result.retrying), (0, 0, 0))
        self.assertEqual(notifier.sent, [])


@override_settings(NOTIFICATION_CHANNELS=["console"])
class SendCommandTests(OutboxBase):
    def run_command(self, **options):
        out = StringIO()
        call_command("send_notifications", stdout=out, **options)
        return out.getvalue()

    def test_reports_what_it_sent(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        with self.assertLogs("api.notifications", level="WARNING"):
            output = self.run_command()

        self.assertIn("Enviados: 1", output)
        self.assertIn("En cola: 0", output)

    def test_warns_about_failed_notices(self):
        enqueue(FIRE, self.node, "Incendio", "d")

        with override_settings(NOTIFICATION_CHANNELS=["telegram"], TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""):
            with self.assertLogs("api.notifications", level="WARNING"):
                output = self.run_command()

        self.assertIn("Fallidos: 1", output)
        self.assertIn("revisa last_error", output)

    def test_an_invalid_limit_is_rejected(self):
        with self.assertRaises(CommandError):
            self.run_command(limit=0)

    def test_an_empty_queue(self):
        self.assertIn("Enviados: 0", self.run_command())


@override_settings(NOTIFICATION_COOLDOWN_SECONDS=300)
class FireAlertNotificationTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")
        self.counter = 0

    def assessed(self, level):
        self.counter += 1
        reading = SensorReading.objects.create(
            node=self.node, temperature=90, humidity=20, smoke=900, flame=True,
        )
        assessment = RiskAssessment.objects.create(
            reading=reading, risk_level=level, rule_reasons=["Se detectó llama."],
        )
        return reading, assessment

    def test_a_new_fire_alert_queues_one_notice(self):
        reading, assessment = self.assessed("FIRE")

        maybe_create_alert(self.node, reading, assessment)

        row = NotificationOutbox.objects.get()
        self.assertEqual((row.kind, row.priority, row.node), ("FIRE_ALERT", 1, self.node))
        self.assertEqual(row.subject, "Incendio detectado en el nodo NODE-001")
        self.assertIn("Se detectó llama.", row.message)

    def test_updating_the_same_alert_does_not_notify_again(self):
        maybe_create_alert(self.node, *self.assessed("FIRE"))
        maybe_create_alert(self.node, *self.assessed("FIRE"))

        self.assertEqual(Alert.objects.get().occurrences, 2)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    @override_settings(ALERT_ON_WARNING=True)
    def test_a_warning_alert_does_not_notify(self):
        maybe_create_alert(self.node, *self.assessed("WARNING"))

        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_a_reopened_alert_inside_the_window_does_not_notify_twice(self):
        maybe_create_alert(self.node, *self.assessed("FIRE"))
        Alert.objects.update(status="CLOSED")

        maybe_create_alert(self.node, *self.assessed("FIRE"))

        self.assertEqual(Alert.objects.count(), 2)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_a_failure_while_queueing_does_not_lose_the_alert(self):
        reading, assessment = self.assessed("FIRE")

        with patch("api.services.alerts.enqueue", side_effect=RuntimeError("fallo")):
            with self.assertLogs("api.readings", level="ERROR"):
                alert = maybe_create_alert(self.node, reading, assessment)

        self.assertEqual(Alert.objects.get(), alert)
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_a_database_error_while_queueing_does_not_break_the_surrounding_transaction(self):
        from django.db import DatabaseError, transaction

        reading, assessment = self.assessed("FIRE")

        with transaction.atomic():
            with patch("api.services.alerts.enqueue", side_effect=DatabaseError("boom")):
                with self.assertLogs("api.readings", level="ERROR"):
                    maybe_create_alert(self.node, reading, assessment)
            self.assertEqual(Alert.objects.count(), 1)  # la transacción sigue utilizable
