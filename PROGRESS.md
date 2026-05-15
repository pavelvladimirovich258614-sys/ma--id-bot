# Прогресс внедрения проверки подписки

- [x] 1. Обновить `requirements.txt` (+ `httpx`, `aiosqlite`)
- [x] 2. Обновить `config.py` (+ `CHANNEL_ID`, `CHANNEL_LINK`, `SUBSCRIPTION_TEXT`, `API_BASE`)
- [x] 3. Создать `database/__init__.py` и `database/storage.py` (`init_db`, `get_user`, `update_user`)
- [x] 4. Создать `middleware/__init__.py` и `middleware/subscription.py` (`@require_subscription`, кэш 5 мин)
- [x] 5. Создать `keyboards/subscription.py` (inline-кнопка-ссылка)
- [x] 6. Обновить `handlers/callbacks.py` (+ `@require_subscription`, fallback regex `max.ru/id\d+_biz`)
- [x] 7. Обновить `handlers/messages.py` (+ `@require_subscription`)
- [x] 8. Обновить `bot.py` (`await init_db()` перед polling)
- [x] 9. Обновить `.env` / `README` (новые переменные)
- [x] 10. Тест: первый запрос без подписки проходит
- [x] 11. Тест: второй запрос без подписки блокируется с кнопкой
- [x] 12. Тест: повторная подписка восстанавливает доступ
