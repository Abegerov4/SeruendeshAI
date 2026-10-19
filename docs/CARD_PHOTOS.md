# Фото карточек в SeaweedFS / S3

Фотографии хранятся в бакете `place-photos`, ссылки привязаны к точному ID места
в отдельном `photos.json`. Исходный каталог не меняется. API накладывает фото
при старте, сохраняя контракт `photo.url`, `author`, `license`, `page`, `source`.
Работает и с обычным, и с canonical-каталогом. Фото из этого реестра имеют
приоритет над исходными; без записи сохраняется прежнее фото/заглушка.

## Запуск из корня проекта

1. Скопируйте `.env.example` в `.env`, если файла ещё нет. Добавьте
   `S3_ACCESS_KEY_ID` и `S3_SECRET_ACCESS_KEY` (случайный секрет не короче 16 символов).
2. Для локального браузера установите
   `S3_PUBLIC_BASE_URL=http://localhost:9000/place-photos`.
3. Запустите:

```sh
docker compose -f compose.yaml -f compose.photos.yaml up --build -d
```

S3: http://localhost:9000 (внутри Docker — `http://seaweedfs:8333`).
Используется официальный образ `chrislusf/seaweedfs:4.48`, режим `weed mini`.
Административные порты не публикуются. Compose требует непустые ключи, чтобы
SeaweedFS не стартовал в режиме без авторизации.
Инициализация ждёт успешного авторизованного запроса S3 и создаёт бакет идемпотентно. Анонимно
разрешено только чтение `cards/*`; листинг и запись закрыты. Корневые ключи
получают только SeaweedFS и операторские команды, веб-приложению они не нужны.
Файлы и реестр сохраняются в именованных Docker volumes после перезапуска.

## Прикрепить фото

Создайте папку `photo-import` в корне и положите в неё `baiterek.jpg`.
Возьмите **реальный ID** из активного каталога/API; в canonical-режиме используйте
canonical ID. Загрузите фотографию, которую имеете право публиковать:

```sh
docker compose -f compose.yaml -f compose.photos.yaml run --rm photos upload \
  --poi-id 'REPLACE_WITH_REAL_POI_ID' --file /imports/baiterek.jpg \
  --author 'Имя фотографа' --license 'CC BY 4.0' \
  --page 'https://example.org/original-photo'
docker compose -f compose.yaml -f compose.photos.yaml restart app
```

Это операторская команда: ID нужно проверить перед загрузкой. Неизвестный ID
не создаёт новое место и не отображается. Поддерживаются JPEG/PNG/WebP до 12 MiB;
результат — JPEG до 1920 px с исправленной ориентацией и без EXIF/GPS.
Ключ зависит от содержимого: повторная загрузка одинакового фото идемпотентна.
Замена фото обновляет только привязку; старый объект остаётся для последующей
ручной очистки. Одновременные загрузки сериализуются блокировкой реестра.

## Размещение и резервное копирование

`localhost` работает только на вашем компьютере. Для телефона, Telegram и
публичного сайта задайте `S3_PUBLIC_BASE_URL=https://photos.example.org/place-photos`
и направьте HTTPS reverse proxy этого домена на порт 9000. Не используйте
`http://seaweedfs:8333` в браузерных URL. Порты master/filer/admin не открывайте наружу.
Обычному `<img>` не требуется CORS; загрузка из браузера здесь не реализована.

Бэкапьте оба volume: `seaweedfs-data` и `card-photo-manifest`. `docker compose down`
их сохраняет; `down -v` удаляет. Проверяйте восстановление обоих вместе.
Это одноузловая конфигурация без репликации. Не кладите приватные фото в `cards/`.

SeaweedFS — поддерживаемое S3-совместимое хранилище (Apache-2.0):
[релизы](https://github.com/seaweedfs/seaweedfs/releases),
[режим mini](https://github.com/seaweedfs/seaweedfs/wiki/Quick-Start-with-weed-mini),
[политики бакетов](https://github.com/seaweedfs/seaweedfs/wiki/S3-Bucket-Policies).
Версия закреплена; обновляйте её после проверки релизных заметок и резервной копии.
Операторский инструмент использует стандартный S3 через boto3: для другого
провайдера задайте `S3_ENDPOINT_URL`, AWS credentials, `AWS_DEFAULT_REGION`,
`S3_BUCKET` и `CARD_PHOTOS_FILE`. Политика публичного чтения должна соответствовать
правилам провайдера; `init` управляет политикой целиком только выделенного бакета.
API требует лишь реестр и `S3_PUBLIC_BASE_URL`, SDK/ключи ему не нужны.

Дополнение предназначено для корневого `compose.yaml`. Railway сам не запускает
Compose: там нужны отдельное S3-хранилище и доставка реестра в приложение.

## Если уже запускали прежний вариант с MinIO

Замените переменные `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` на новые S3-переменные
выше. Остановите старый контейнер MinIO перед запуском SeaweedFS: оба используют
порт хоста 9000. Новый volume `seaweedfs-data` изолирован от старого `minio-data`;
форматы данных несовместимы, подключать старый volume к SeaweedFS нельзя.
Старый volume эта конфигурация не удаляет.

Если фото уже загружались, перенесите объекты бакета через S3 (например, rclone)
с сохранением ключей `cards/*` или повторите загрузку исходников. Реестр привязок
`card-photo-manifest` сохраняется, но до переноса объектов ссылки будут давать 404.
Если старый вариант не запускали, миграция не нужна.

## Проверка кода

В тестовом Python-окружении установите `infra/photos/requirements.txt` и `pytest`,
затем запустите `python -m pytest -c backend/pyproject.toml infra/photos/tests/test_card_photos.py`.
Тесты проверяют контракт фото, обработку изображений, политику бакета и сохранение
старой привязки при сбое S3. Для проверки реального хранилища после запуска Compose
загрузите фото командой выше и откройте полученный URL из ответа API в браузере.

### Интеграционный тест в Docker

Используйте отдельный проект `seru-photos-check` и тестовые значения
`S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` в окружении. Порт 9000 должен быть свободен.
Команды ниже создают только тестовые объекты и отдельные тома:

```sh
docker compose -p seru-photos-check -f compose.yaml -f compose.photos.yaml up --build -d photos-init
docker compose -p seru-photos-check -f compose.yaml -f compose.photos.yaml -f compose.photos-test.yaml run --build --rm photos seed
docker compose -p seru-photos-check -f compose.yaml -f compose.photos.yaml restart seaweedfs
docker compose -p seru-photos-check -f compose.yaml -f compose.photos.yaml -f compose.photos-test.yaml run --rm --no-deps photos verify
```

Проверяются реальная загрузка, чтение фото по ссылке карточки, размер и EXIF,
повторная инициализация/загрузка, запрет анонимных PUT/DELETE/List и чтения
`private/*`, сохранение объектов и реестра после перезапуска.
`--no-deps` исключает повторную инициализацию политики при проверке сохранности.
Проверка выполнена 19 октября 2026: seed, verify после перезапуска и verify
через опубликованный порт хоста прошли на Docker Desktop (Linux containers).
После проверки удалите **только тестовый проект** и его тома:

```sh
docker compose -p seru-photos-check -f compose.yaml -f compose.photos.yaml down -v
```
