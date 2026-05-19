# Архитектура Админ-панели MaxIDBot

## Цель

Админ-панель нужна для управления пользователями, рассылками, аналитикой и системным состоянием MaxIDBot. На первом этапе фиксируется архитектура и инфраструктурные требования, без внедрения runtime-кода панели в существующего бота.

## Стек

| Компонент | Назначение |
|-----------|------------|
| FastAPI (async) | Backend API и серверные HTML endpoints панели |
| PostgreSQL | Основная база данных пользователей, рассылок, событий и аудита |
| Redis | Брокер и transient-хранилище для очередей, rate-limit и статусов задач |
| Celery | Фоновые задачи для массовых рассылок и долгих операций |
| Jinja2 + HTMX | Серверный frontend без тяжелого SPA, частичные обновления интерфейса |

## Модули панели

### Users

- Поиск пользователей по `user_id`, имени, username или статусу.
- Фильтрация по подписке, активности, бану и дате последнего действия.
- Просмотр статуса подписки и счетчиков использования.
- Управление доступом: ban/unban с записью в `admin_audit`.

### Broadcasts

- Конструктор сообщений для рассылок.
- Сегментация аудитории: все пользователи, подписанные, неподписанные, активные, неактивные, не заблокированные.
- Очередь доставки через Celery.
- Anti-flood ограничение MAX API: не более 30 запросов в секунду через единый адаптер.
- Отслеживание статуса доставки: pending, running, completed, failed, cancelled.

### Analytics

- DAU/WAU по событиям активности.
- Общий размер базы пользователей.
- Активность по кнопкам и ключевым сценариям бота.
- Агрегация событий из `events_log` без хранения лишних персональных данных.

### System

- Просмотр логов сервера и фоновых задач.
- Проверка статуса API MAX.
- Управление конфигом панели через безопасные переменные окружения.
- Отображение состояния Redis, Celery worker и PostgreSQL.

## Схема БД

### users

Основная таблица пользователей бота и панели.

| Поле | Тип | Назначение |
|------|-----|------------|
| id | bigserial primary key | Внутренний ID записи |
| user_id | bigint unique not null | ID пользователя в MAX |
| username | varchar(255) null | Username, если доступен |
| first_name | varchar(255) null | Имя пользователя |
| last_name | varchar(255) null | Фамилия пользователя |
| usage_count | integer not null default 0 | Количество полезных запросов |
| is_subscribed | boolean not null default false | Последний известный статус подписки |
| is_banned | boolean not null default false | Флаг блокировки администратором |
| last_check | timestamptz null | Время последней проверки подписки |
| last_activity_at | timestamptz null | Последняя активность пользователя |
| created_at | timestamptz not null | Дата первой регистрации |
| updated_at | timestamptz not null | Дата последнего обновления |

### broadcasts

Таблица рассылок и их агрегированного состояния.

| Поле | Тип | Назначение |
|------|-----|------------|
| id | bigserial primary key | ID рассылки |
| title | varchar(255) not null | Внутреннее название рассылки |
| message_text | text not null | Текст сообщения |
| segment | varchar(100) not null | Целевая аудитория |
| status | varchar(50) not null | pending/running/completed/failed/cancelled |
| total_count | integer not null default 0 | Всего получателей |
| delivered_count | integer not null default 0 | Успешно доставлено |
| failed_count | integer not null default 0 | Ошибок доставки |
| created_by | bigint not null | OWNER_ID администратора |
| started_at | timestamptz null | Дата старта рассылки |
| finished_at | timestamptz null | Дата завершения рассылки |
| created_at | timestamptz not null | Дата создания |
| updated_at | timestamptz not null | Дата обновления |

### events_log

Журнал событий бота, панели и аналитики.

| Поле | Тип | Назначение |
|------|-----|------------|
| id | bigserial primary key | ID события |
| user_id | bigint null | Пользователь MAX, если событие связано с ним |
| event_type | varchar(100) not null | Тип события: button_click, sticker, forward, subscription_check |
| source | varchar(50) not null | bot/admin/celery/system |
| payload | jsonb null | Технические детали события |
| created_at | timestamptz not null | Время события |

### admin_audit

Аудит действий администратора в панели.

| Поле | Тип | Назначение |
|------|-----|------------|
| id | bigserial primary key | ID записи аудита |
| admin_id | bigint not null | OWNER_ID из `.env` |
| action | varchar(100) not null | Действие администратора |
| entity_type | varchar(100) not null | Тип объекта: user, broadcast, config |
| entity_id | varchar(255) null | ID объекта |
| metadata | jsonb null | Детали изменения |
| created_at | timestamptz not null | Время действия |

## Инфраструктурные правила

- Все обращения к MAX API выполняются через единый async-адаптер с централизованным rate-limit 30 rps.
- Массовые рассылки выполняются только через Celery worker и не блокируют polling бота.
- Доступ к панели разрешен только владельцу, чей `OWNER_ID` указан в `.env`.
- PostgreSQL становится основной БД для админ-панели; существующая SQLite-логика бота не меняется до отдельного этапа миграции.
- Redis используется как брокер Celery и вспомогательное хранилище статусов фоновых задач.
