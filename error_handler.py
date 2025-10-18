# error_handler.py
import os
import datetime
import traceback

def handle_browser_crash(driver, account_id, event_title, error):
    """
    ブラウザクラッシュ（予期せぬエラー）発生時に調査用の情報を保存する
    """
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    # ファイル名に使えない文字を置換
    safe_account_id = account_id.replace('@', '_').replace('.', '_')
    safe_event_title = "".join(c if c.isalnum() else "_" for c in event_title)[:30]
    
    base_filename = f"crash_{timestamp}_{safe_account_id}_{safe_event_title}"
    
    print("\n" + "="*20 + "!! CRASH REPORT !!" + "="*20)
    print(f"エラー発生時刻: {timestamp}")
    print(f"アカウントID: {account_id}")
    print(f"イベント: {event_title}")
    print(f"エラー内容: {error}")
    traceback.print_exc()

    if driver is None:
        print("WebDriverが利用不可能なため、詳細情報の保存はスキップします。")
        print("="*58)
        return base_filename

    # 1. スクリーンショットの保存
    try:
        ss_path = f"{base_filename}.png"
        driver.save_screenshot(ss_path)
        print(f"✅ スクリーンショットを保存しました: {ss_path}")
    except Exception as e:
        print(f"❌ スクリーンショットの保存に失敗しました: {e}")

    # 2. ページソース(HTML)の保存
    try:
        html_path = f"{base_filename}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"✅ ページソースを保存しました: {html_path}")
    except Exception as e:
        print(f"❌ ページソースの保存に失敗しました: {e}")
        
    # 3. ブラウザコンソールログの取得・保存
    try:
        logs = driver.get_log('browser')
        if logs:
            log_path = f"{base_filename}.log"
            with open(log_path, 'w', encoding='utf-8') as f:
                for log_entry in logs:
                    f.write(f"[{log_entry['timestamp']}] {log_entry['level']} - {log_entry['message']}\n")
            print(f"✅ ブラウザコンソールログを保存しました: {log_path}")
        else:
            print("ℹ️ ブラウザコンソールログはありませんでした。")
    except Exception as e:
        print(f"❌ ブラウザコンソールログの取得に失敗しました: {e}")
        
    print("="*58 + "\n")
    return base_filename