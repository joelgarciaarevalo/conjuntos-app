import json
import logging
import os
import smtplib
from email.message import EmailMessage
from app import models

log = logging.getLogger("iris.notifications")


def deliver_external(db, user_id: int, title: str, message: str, allow_unverified: bool = False) -> None:
    """Entrega opcional. Si SMTP/VAPID no están configurados, permanece solo in-app."""
    user = db.query(models.Usuario).filter_by(id=user_id).first()
    if not user:
        return
    host = os.getenv("SMTP_HOST")
    if host and user.email and (user.email_verificado or allow_unverified):
        try:
            mail = EmailMessage()
            mail["Subject"] = title
            mail["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "iris@localhost"))
            mail["To"] = user.email
            mail.set_content(f"Hola {user.nombre_completo},\n\n{message}\n\nNotificación del sistema IRIS.")
            with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=5) as smtp:
                smtp.starttls()
                smtp.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", ""))
                smtp.send_message(mail)
        except Exception as exc:
            log.warning("No fue posible enviar correo a usuario %s: %s", user_id, exc)
    public_key = os.getenv("VAPID_PUBLIC_KEY")
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    if public_key and private_key:
        try:
            from pywebpush import webpush, WebPushException
            subs = db.query(models.PushSubscription).filter_by(usuario_id=user_id).all()
            for sub in subs:
                try:
                    webpush(
                        subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                        data=json.dumps({"title": title, "body": message}),
                        vapid_private_key=private_key,
                        vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")},
                        ttl=60,
                    )
                except WebPushException as exc:
                    if getattr(exc.response, "status_code", None) in (404, 410):
                        db.delete(sub)
                    else:
                        log.warning("Web Push falló para usuario %s: %s", user_id, exc)
        except Exception as exc:
            log.warning("Web Push no está disponible: %s", exc)
