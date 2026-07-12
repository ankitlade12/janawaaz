from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import janawaaz.web.app as webapp
from janawaaz.models import User
from janawaaz.pipeline.summarize import _dev_embedding


def test_signup_telegram_consent_stop_and_delete(db, monkeypatch):
    monkeypatch.setattr(webapp.summarize, "embed", _dev_embedding)
    monkeypatch.setattr(webapp, "_match_user_background", lambda uid: None)

    with TestClient(webapp.app) as client:
        response = client.post(
            "/onboard",
            data={
                "name": "Web Flow Test",
                "language": "hi",
                "interests_text": "I care about rural broadband tariffs and consumer complaints.",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        parsed = urlparse(location)
        query = parse_qs(parsed.query)
        uid = int(query["uid"][0])
        manage_token = query["token"][0]

        done = client.get(location)
        assert done.status_code == 200
        assert "Connect Telegram securely" in done.text

        telegram_token = webapp._signed_token(uid, "telegram")
        linked = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 998877}, "text": f"/start {telegram_token}"}},
        )
        assert linked.status_code == 200

        stopped = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 998877}, "text": "/stop"}},
        )
        assert stopped.status_code == 200

        deleted = client.post(
            f"/profile/{uid}/delete",
            data={"token": manage_token},
            follow_redirects=False,
        )
        assert deleted.status_code == 303

    from janawaaz.db import session

    with session() as s:
        user = s.get(User, uid)
        assert user.name == "Deleted user"
        assert user.telegram_chat_id is None
        assert not user.active

