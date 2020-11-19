# Сервис интересов пользователя

Данный документ содержит описание работы и информацию о развертке микросервиса, предназначенного для хранения информации об интересах пользователя и отправляющего данные об изменениях интересов сервису ранжирования.

Название: `uis`

Структура сервиса:

| Файл                 | Описание                                                          |
| -------------------- | ----------------------------------------------------------------- |
| `uis.py`             | Код микросервиса                                                  |
| `config.yml`         | Конфигурационный файл со строкой подключения к RabbitMQ и MongoDB |
| `run.sh`             | Файл для запуска сервиса из Docker контейнера                     |
| `requirements.txt`   | Верхнеуровневые зависимости                                       |
| `Dockerfile`         | Описание сборки контейнера сервиса                                |
| `docker-compose.yml` | Изолированная развертка сервиса вместе с (RabbitMQ, MongoDB)      |
| `README.md`          | Описание микросервиса                                             |

## API

### RPC

Новая анкета или обновление данных по анкете:

```bat
n.rpc.uis.create_new_q(<questionnaire>)

Args: questionnaire = [user_id, [tag_1, tag_2, ..., tag_m]]
Returns: nothing
Dispatch to the `ranking`: [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}]
```

Добавление, отмена лайка:

```bat
n.rpc.uis.add_like(like_data)
n.rpc.uis.cancel_like(like_data)

Args: like_data = [user_id, event_id]
Returns: nothing
Dispatch to the `ranking`: [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}]
```

Добавление в избранное, удаление из избранного:

```bat
n.rpc.uis.add_fav(fav_data)
n.rpc.uis.cancel_fav(fav_data)

Args: fav_data = [user_id, event_id]
Returns: nothing
Dispatch to the `ranking`: [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}]
```

Получить интересы пользователей по id:

```bat
n.rpc.uis.get_weights_by_id(user_id)

Args: user_id - id of the user
Returns: {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}
```

Получить булевский список:

```bat
n.rpc.uis.get_bool_list(user_id)

Args: user_id - id of the user
Returns: [True, False, False, ...] if user is presented in db and None otherwise
```

Сохранить булевский список:

```bat
n.rpc.uis.save_bool_list(user_id, bool_list)

Args: 
    user_id - id of the user,
    bool_list - list like [True, False, False, ...]
Returns: nothing
```

### HTTP

Новая анкета или обновление данных по анкете:

```rst
POST http://localhost:8000/newq HTTP/1.1
Content-Type: application/json

[user_id, [
    'tag_1', 'tag_2', ..., 'tag_m'
]]
```

Добавление лайка:

```rst
POST http://localhost:8000/got_like HTTP/1.1
Content-Type: application/json

[user_id, event_id]
```

Отмена лайка:

```rst
POST http://localhost:8000/cancel_like HTTP/1.1
Content-Type: application/json

[user_id, event_id]
```

Добавление в избранное:

```rst
POST http://localhost:8000/got_fav HTTP/1.1
Content-Type: application/json

[user_id, event_id]
```

Удаление из избранного:

```rst
POST http://localhost:8000/cancel_fav HTTP/1.1
Content-Type: application/json

[user_id, event_id]
```

Получить интересы пользователей по id:

```rst
GET http://localhost:8000/get_weights/<id> HTTP/1.1
```

## Развертывание и запуск

### Локальный запуск

Для локального запуска микросервиса требуется запустить контейнер с RabbitMQ и MongoDB.

```bat
docker-compose up -d
```

Затем из папки микросервиса вызвать

```bat
nameko run uis
```

Для проверки `rpc` запустите в командной строке:

```bat
nameko shell
```

После чего откроется интерактивная Python среда и обратитесь к сервису одной из команд, представленных выше в разделе `rpc`.

### Запуск в контейнере

Чтобы запустить микросервис в контейнере вызовите команду:

```bat
docker-compose up
```

> если вы не хотите просмотривать логи, добавьте флаг `-d` в конце

Микросервис запустится вместе с RabbitMQ и MongoDB в контейнерах.

> Во всех случаях запуска вместе с MongoDB также разворачивается mongo-express - инструмент, с помощью которого можно просматривать и изменять содержимое подключенной базы (подключение в контейнерах сконфигурировано и производится автоматически). Сервис хостится локально на порту 8081.
