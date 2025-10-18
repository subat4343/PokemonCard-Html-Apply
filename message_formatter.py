# message_formatter.py
import json
import os
import sys

from models import Event

def _load_templates():
    template_file = 'message_templates.json'
    if not os.path.exists(template_file):
        print(f"エラー: メッセージテンプレートファイル '{template_file}' が見つかりません。")
        sys.exit(1)
    try:
        with open(template_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"エラー: テンプレートファイル '{template_file}' の読み込みに失敗しました: {e}")
        sys.exit(1)

MESSAGE_TEMPLATES = _load_templates()

def _format_message(template_lines, params):
    if not template_lines: return "メッセージテンプレートが設定されていません。"
    message = "\n".join(template_lines)
    return message.format(**params)

def create_discovery_message(notification_method, event):
    template_lines = MESSAGE_TEMPLATES.get('discovery', {}).get(notification_method, [])
    params = {'title': event.title, 'url': event.url}
    return _format_message(template_lines, params)

def create_result_message(notification_method, event, player_id, success, apply_message):
    template_lines = MESSAGE_TEMPLATES.get('result', {}).get(notification_method, [])
    params = {
        'title': event.title,
        'player_id': player_id,
        'status_icon': '🎉' if success else '❌',
        'apply_message': apply_message
    }
    return _format_message(template_lines, params)

def create_monitoring_result_message(notification_method, event, account, success, message):
    template_lines = MESSAGE_TEMPLATES.get('monitoring_result', {}).get(notification_method, [])
    params = {
        'status_icon': '🎉' if success else '❌',
        'result_text': "応募に成功しました！" if success else "応募に失敗しました。",
        'title': event.title,
        'url': event.url,
        'player_id': account['id'],
        'message': message
    }
    return _format_message(template_lines, params)

def create_crash_report_message(notification_method, account_id, event_title, error, report_file_base):
    template_lines = MESSAGE_TEMPLATES.get('crash_report', {}).get(notification_method, [])
    params = {
        'account_id': account_id,
        'event_title': event_title,
        'error_message': str(error),
        'report_file_base': report_file_base
    }
    return _format_message(template_lines, params)