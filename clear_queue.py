import requests

instance = '7700610961'
token = 'ec40236de3f943ffb076cea5b564af4f19610819453f41c8bf'
base = f'https://api.green-api.com/waInstance{instance}'

count = 0
skip_ids = set()

while True:
    try:
        r = requests.get(f'{base}/receiveNotification/{token}', timeout=10)
        if not r.text or r.text == 'null':
            break
        data = r.json()
        if not data:
            break
        rid = data.get('receiptId')
        if not rid:
            break
        if rid in skip_ids:
            print(f'Уведомление {rid} застряло, пропускаем')
            break
        try:
            d = requests.delete(f'{base}/deleteNotification/{rid}/{token}', timeout=5)
            count += 1
            print(f'Удалено: {rid}')
        except Exception as e:
            print(f'Не удалось удалить {rid}: {e}')
            skip_ids.add(rid)
            break
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f'Ошибка: {e}')
        break

print(f'Готово. Удалено: {count}')
