"""Tes notifikasi SMTP."""

import smtplib

from pipeline.alerts import send_pipeline_report


def test_email_report_skips_without_smtp_password(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    monkeypatch.setenv("SMTP_FROM", "sender@example.com")
    monkeypatch.setenv("PIPELINE_REPORT_RECIPIENTS", "recipient@example.com")

    assert send_pipeline_report({"status": "SUCCESS"}) is False


def test_email_report_uses_starttls_and_sends(monkeypatch):
    events = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            events.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            events.append(("starttls",))

        def login(self, username, password):
            events.append(("login", username, password))

        def send_message(self, message):
            events.append(("send", message["To"], message["Subject"]))

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_FROM", "sender@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("PIPELINE_REPORT_RECIPIENTS", "recipient@example.com")
    monkeypatch.setattr("pipeline.alerts.smtplib.SMTP", FakeSmtp)

    assert send_pipeline_report({"run_id": "run-1", "status": "SUCCESS"}) is True
    assert events[0] == ("connect", "smtp.example.com", 587, 15)
    assert ("starttls",) in events
    assert any(event[0] == "send" for event in events)


def test_gmail_app_password_spaces_are_removed(monkeypatch):
    events = []

    class FakeSmtp:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            pass

        def login(self, _username, password):
            events.append(("login", password))

        def send_message(self, _message):
            events.append(("send",))

    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("SMTP_FROM", "sender@gmail.com")
    monkeypatch.setenv("PIPELINE_REPORT_RECIPIENTS", "recipient@gmail.com")
    monkeypatch.setattr("pipeline.alerts.smtplib.SMTP", FakeSmtp)

    assert send_pipeline_report({"run_id": "run-gmail", "status": "SUCCESS"}) is True
    assert ("login", "abcdefghijklmnop") in events


def test_email_report_retries_connection_before_sending(monkeypatch):
    events = []

    class FakeSmtp:
        attempts = 0

        def __init__(self, *_args, **_kwargs):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise OSError("temporary DNS failure")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            events.append("starttls")

        def login(self, *_):
            events.append("login")

        def send_message(self, _message):
            events.append("send")

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("PIPELINE_REPORT_RECIPIENTS", "recipient@example.com")
    monkeypatch.setenv("SMTP_CONNECT_RETRIES", "2")
    monkeypatch.setattr("pipeline.alerts.smtplib.SMTP", FakeSmtp)
    monkeypatch.setattr("pipeline.alerts.sleep", lambda _: None)

    assert send_pipeline_report({"run_id": "run-2", "status": "SUCCESS"}) is True
    assert FakeSmtp.attempts == 2
    assert events == ["starttls", "login", "send"]


def test_email_report_retries_transient_disconnect_during_tls(monkeypatch):
    events = []

    class FakeSmtp:
        attempts = 0

        def __init__(self, *_args, **_kwargs):
            type(self).attempts += 1
            self.attempt = type(self).attempts

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            events.append(("starttls", self.attempt))
            if self.attempt == 1:
                raise smtplib.SMTPServerDisconnected("connection closed")

        def login(self, *_):
            events.append(("login", self.attempt))

        def close(self):
            events.append(("close", self.attempt))

        def send_message(self, _message):
            events.append(("send", self.attempt))

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_FROM", "sender@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("PIPELINE_REPORT_RECIPIENTS", "recipient@example.com")
    monkeypatch.setenv("SMTP_CONNECT_RETRIES", "2")
    monkeypatch.setattr("pipeline.alerts.smtplib.SMTP", FakeSmtp)
    monkeypatch.setattr("pipeline.alerts.sleep", lambda _: None)

    assert send_pipeline_report({"run_id": "run-3", "status": "SUCCESS"}) is True
    assert FakeSmtp.attempts == 2
    assert events == [
        ("starttls", 1),
        ("close", 1),
        ("starttls", 2),
        ("login", 2),
        ("send", 2),
    ]
