# -*- coding: utf-8 -*-
"""
Клиент API отзывов Wildberries.
Хост: https://feedbacks-api.wildberries.ru
Токен — в заголовке Authorization как есть (без слова Bearer).

WB ограничивает частоту запросов. При 429 присылает X-Ratelimit-Retry —
сколько секунд ждать. При обрыве связи делаем повторы и НЕ роняем процесс:
если так и не дозвонились — возвращаем None, вызывающий код это переживёт.
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

    # Сколько раз пробуем и максимум ожидания при 429 (чтобы не залипать на одном отзыве)
    MAX_ATTEMPTS = 4
    WAIT_CAP = 30

    def _request(self, method: str, path: str, **kwargs):
        """Повторяет при 429/5xx/обрыве связи. Возвращает ответ или None.
        Ожидание ограничено, чтобы один проблемный отзыв не тормозил весь прогон —
        он просто будет обработан при следующем запуске."""
        url = BASE + path
        last = None
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                r = self.s.request(method, url, timeout=40, **kwargs)
            except requests.RequestException:
                # обрыв связи и т.п. — ждём и пробуем снова, НЕ падаем
                time.sleep(min(5 * (attempt + 1), self.WAIT_CAP))
                continue
            last = r
            if r.status_code == 429:
                wait = self._retry_after(r, default=10 * (attempt + 1))
                time.sleep(min(wait, self.WAIT_CAP))
                continue
            if r.status_code >= 500:
                time.sleep(min(5 * (attempt + 1), self.WAIT_CAP))
                continue
            return r
        return last  # None, если ни одна попытка не дала ответа

    def get_feedbacks(self, is_answered="false", date_from=None, date_to=None,
                      take: int = 5000, order: str = "dateAsc") -> list:
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
        """Отправляет ответ. Возвращает (успех, описание). Никогда не бросает исключение."""
        try:
            r = self._request("POST", "/api/v1/feedbacks/answer", json={"id": feedback_id, "text": text})
        except Exception as e:
            return False, f"исключение: {e}"
        if r is None:
            return False, "нет ответа от WB (обрыв связи)"
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
