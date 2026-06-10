#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СТОРОЖ НЕГАТИВА → TELEGRAM (почти в реальном времени)

Каждый запуск проверяет неотвеченные отзывы и шлёт в Telegram оповещение о новых
отзывах с оценкой 1–NEGATIVE_MAX_RATING. Каждый отзыв оповещается один раз
(память — в alerted.json).

Ставится на частый запуск (каждые 15 минут, см. plist).
"""
import os
import json
import html
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

import config as C
from wb_api import WBFeedbacks, fb_id, fb_rating, fb_name, fb_text, fb_product

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Негатив = оценка от 1 до этого значения. Поставь 2, если тройку не считать негативом.
NEGATIVE_MAX_RATING = 3

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ALERTED_PATH = BASE_DIR / "alerted.json"
CHUNK = 5  # сколько отзывов в одном сообщении (чтобы не упереться в лимит длины Telegram)


def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Не заданы TELEGRAM_TOKEN / TELEGRAM_CHAT_ID в .env")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    if not r.ok:
        print("Ошибка Telegram:", r.status_code, r.text[:300])
        return False
    return True


def load_alerted() -> set:
    if ALERTED_PATH.exists():
        try:
            return set(json.loads(ALERTED_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def save_alerted(s: set):
    ALERTED_PATH.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")


def build_message(chunk: list) -> str:
    lines = [f"<b>⚠️ Новый негатив: {len(chunk)} шт.</b>", ""]
    for fb in chunk:
        nm, name = fb_product(fb)
        rating = fb_rating(fb)
        user = fb_name(fb) or "без имени"
        txt = fb_text(fb)
        stars = "★" * rating + "☆" * (5 - rating)
        lines.append(f"<b>{html.escape(name or 'товар')}</b> (арт. {html.escape(str(nm))})")
        lines.append(f"{stars} ({rating})  •  {html.escape(user)}")
        if txt:
            short = txt if len(txt) <= 500 else txt[:500] + "…"
            lines.append(f"«{html.escape(short)}»")
        lines.append("")
    return "\n".join(lines).strip()


def main():
    wb = WBFeedbacks(C.WB_TOKEN)
    alerted = load_alerted()

    try:
        feedbacks = wb.get_unanswered()
    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Не удалось получить отзывы: {e}")
        return

    new_negs = [fb for fb in feedbacks
                if 1 <= fb_rating(fb) <= NEGATIVE_MAX_RATING and fb_id(fb) not in alerted]

    if not new_negs:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Новых негативных отзывов нет")
        return

    ok_ids = []
    for i in range(0, len(new_negs), CHUNK):
        chunk = new_negs[i:i + CHUNK]
        if send_telegram(build_message(chunk)):
            ok_ids.extend(fb_id(fb) for fb in chunk)
        else:
            break

    for fid in ok_ids:
        alerted.add(fid)
    save_alerted(alerted)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Отправлено оповещений: {len(ok_ids)}")


if __name__ == "__main__":
    main()
