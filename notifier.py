# notifier.py
import requests
import json
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    TextMessage,
    PushMessageRequest
)

def _send_discord_message(webhook_url, message, image_path=None):
    """(内部用) Discordにメッセージと画像(オプション)を送信する"""
    if not webhook_url or not webhook_url.startswith('https://discord.com/api/webhooks/'):
        print("Discord通知スキップ: Webhook URLが正しく設定されていません。")
        return

    try:
        if image_path:
            # 画像付きで送信 (multipart/form-data)
            with open(image_path, 'rb') as f:
                payload_json = {'content': message.strip()}
                files = {
                    'file': (image_path, f, 'image/png'),
                    'payload_json': (None, json.dumps(payload_json), 'application/json')
                }
                response = requests.post(webhook_url, files=files)
        else:
            # テキストのみで送信 (application/json)
            main_content = {"content": message.strip()}
            response = requests.post(
                webhook_url,
                data=json.dumps(main_content),
                headers={'Content-Type': 'application/json'}
            )
        
        if 200 <= response.status_code < 300:
            print("Discordにメッセージを送信しました。")
        else:
            print(f"Discordへのメッセージ送信に失敗しました。ステータスコード: {response.status_code}")
            print(f"  詳細: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Discordへのメッセージ送信中にエラーが発生しました: {e}")
    except FileNotFoundError:
        print(f"Discord通知エラー: 画像ファイルが見つかりません ({image_path})")


def _send_line_message(token, group_id, message):
    """(内部用) 指定された単一のグループIDにプッシュメッセージを送信する"""
    if not token or not group_id:
        print("LINE通知スキップ: トークンまたはグループIDがありません。")
        return

    configuration = Configuration(access_token=token)
    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        push_message_request = PushMessageRequest(
            to=group_id,
            messages=[TextMessage(text=message.strip())]
        )
        try:
            messaging_api.push_message(push_message_request)
            print(f"LINEグループ (ID: {group_id[:10]}...) にメッセージを送信しました。")
        except Exception as e:
            error_body = getattr(e, 'body', 'N/A')
            error_status = getattr(e, 'status', 'N/A')
            print(f"LINEへのメッセージ送信に失敗しました。")
            print(f"  ステータス: {error_status}")
            print(f"  詳細: {error_body}")

def send_notification(config, message, image_path=None):
    """
    設定に基づいて適切な通知先にメッセージを送信する
    :param config: config_loader.pyで読み込まれた設定辞書
    :param message: 送信するメッセージ文字列
    :param image_path: (オプション) Discord用。送信する画像のファイルパス
    """
    method = config.get('notification_method', 'none').lower()

    if not message:
        print("通知スキップ: メッセージが空です。")
        return

    if method == 'discord':
        _send_discord_message(config.get('webhook_url'), message, image_path)
    elif method == 'line':
        # LINEは画像送信に非対応なため、メッセージのみ送信
        _send_line_message(config.get('token'), config.get('group_id'), message)
    elif method != 'none':
        print(f"警告: 不明な通知方法 '{method}' が指定されています。通知をスキップします。")