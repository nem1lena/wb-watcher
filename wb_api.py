# -*- coding: utf-8 -*-
"""
Клиент API отзывов Wildberries.
Хост: https://feedbacks-api.wildberries.ru
Токен — в заголовке Authorization как есть (без слова Bearer).

WB ограничивает частоту запросов. При 429 присылает X-Ratelimit-Retry —
сколько секунд ждать. Клиент это читает и выжидает.
"""
import time
import requests

BASE = "https://feedbacks-api.wildberries.ru"


class WBFeedbacks:
    def __init__(self, token: str):
        if not token:
            raise ValueError("Не задан WB_TOKEN (см. .env)")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": token})

    @staticmethod
    def _retry_after(r, default: int) -> int:
        for h in ("X-Ratelimit-Retry", "X-RateLimit-Retry", "Retry-After"):
            v = r.headers.get(h)
            if v:
                try:
                    return int(float(v)) + 1
                except ValueError:
                    pass
        return default

    def _request(self, method: str, path: str, **kwargs):
        url = BASE + path
        last = None
        for attempt in range(6):
            try:
                r = self.s.request(method, url, timeout=60, **kwargs)
            except requests.RequestException:
                if attempt == 5:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            last = r
            if r.status_code == 429:
                wait = self._retry_after(r, default=15 * (attempt + 1))
                time.sleep(min(wait, 120))
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return r
        return last

    def get_feedbacks(self, is_answered="false", date_from=None, date_to=None,
                      take: int = 5000, order: str = "dateAsc") -> list:
        """Универсальный список отзывов. is_answered: 'false'/'true'.
        date_from/date_to — unix-секунды (фильтр по дате создания отзыва)."""
        params = {"isAnswered": is_answered, "take": take, "skip": 0, "order": order}
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        r = self._request("GET", "/api/v1/feedbacks", params=params)
        if r is None:
            raise RuntimeError("WB не ответил после нескольких попыток")
        r.raise_for_status()
        data = r.json().get("data", {}) or {}
        return data.get("feedbacks", []) or []

    def get_unanswered(self, take: int = 5000) -> list:
        return self.get_feedbacks(is_answered="false", take=take, order="dateAsc")

    def count_unanswered(self) -> int:
        r = self._request("GET", "/api/v1/feedbacks/count-unanswered")
        if r is not None and r.ok:
            data = r.json().get("data", {}) or {}
            return data.get("countUnanswered", 0)
        return 0

    def answer(self, feedback_id: str, text: str):
        payload = {"id": feedback_id, "text": text}
        r = self._request("POST", "/api/v1/feedbacks/answer", json=payload)
        if r is None:
            return False, "нет ответа от WB"
        if r.status_code in (200, 204):
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"


# Разбор одного отзыва ─────────────────────────────────────────────────────────

def fb_id(fb: dict) -> str:
    return str(fb.get("id", ""))

def fb_rating(fb: dict) -> int:
    return int(fb.get("productValuation") or 0)

def fb_name(fb: dict) -> str:
    return (fb.get("userName") or "").strip()

def fb_text(fb: dict) -> str:
    parts = [fb.get("text") or ""]
    if fb.get("pros"):
        parts.append("Достоинства: " + fb["pros"])
    if fb.get("cons"):
        parts.append("Недостатки: " + fb["cons"])
    return " | ".join(p for p in parts if p).strip()

def fb_product(fb: dict):
    d = fb.get("productDetails") or {}
    return d.get("nmId", ""), (d.get("productName") or "")
