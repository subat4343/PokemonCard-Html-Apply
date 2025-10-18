# main.py
import sys
import time
import concurrent.futures
import threading
import traceback
from datetime import datetime, date
import queue
import os

from constants import MYPAGE_EVENT_LIST_URL
from config_loader import load_config
from driver_setup import setup_driver
from apply_worker import apply_for_event_task, LoginManager, event_search_worker
from spreadsheet_manager import SpreadsheetManager
from error_handler import handle_browser_crash
from notifier import send_notification
from message_formatter import ( # create_result_message は現在未使用
    create_monitoring_result_message,
    create_crash_report_message
)
from screenshot_taker import take_full_page_screenshot

# --- アカウント整理モード用のimport ---
from pokemon_card_scraper import scrape_and_process_account_action
from models import ScrapeResult
from config_generator import generate_config_files
from notification_builder import create_organizer_summary_message
# ------------------------------------

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from event_checker import extract_event_details_from_mypage

# --- HTTP監視モード用のimport ---
try:
    import requests
    from http_worker import (
        HttpLoginManager, 
        execute_apply_http,
        _check_for_events_http as check_for_events_http # 内部関数としてインポート
    )
except ImportError:
    # requests等がインストールされていない場合、HTTPモードは利用不可
    pass

def main_config_mode(config, shutdown_flag):
    accounts = config.get('accounts', [])
    if not accounts: return
    for i, account in enumerate(accounts):
        if shutdown_flag.is_set(): break
        search_driver = None
        try:
            from event_checker import check_for_events
            search_driver = setup_driver(headless=config['headless'])
            events = check_for_events(search_driver, config['target_url'], config['wait_timeout'])
            if not events: continue
            threads, completion_flag = [], threading.Event()
            for event_info in events:
                thread = threading.Thread(target=apply_for_event_task, args=(account, event_info, completion_flag, shutdown_flag, config))
                threads.append(thread)
                thread.start()
            for thread in threads: thread.join()
        except Exception as e:
            handle_browser_crash(search_driver, account['id'], "イベント検索中", e)
        finally:
            if search_driver: search_driver.quit()

def main_spreadsheet_mode(config, shutdown_flag):
    try:
        ss_manager = SpreadsheetManager(config)
        events = ss_manager.get_event_list()
        if not events: return
        while not shutdown_flag.is_set():
            account = ss_manager.find_and_lock_account()
            if not account: break
            threads, result_queue = [], queue.Queue(maxsize=1)
            completion_flag = threading.Event()
            for event_info in events:
                thread = threading.Thread(target=apply_for_event_task, args=(account, event_info, completion_flag, shutdown_flag, config, result_queue))
                threads.append(thread)
                thread.start()
                time.sleep(5) #ドライバを一気に起動するとクラッシュするため、待機時間を入れる
            for thread in threads: thread.join()
            successful_event = result_queue.get_nowait() if not result_queue.empty() else None
            if successful_event: ss_manager.update_account_result(account['row_num'], True, successful_event, "成功")
            else: ss_manager.update_account_result(account['row_num'], False, None, "時間切れ/失敗")
    except Exception as e:
        print(f"SpreadsheetManagerの初期化に失敗しました: {e}")

def main_monitoring_mode(config, shutdown_flag):
    print("--- 監視モードを開始します (速度最優先アーキテクチャ) ---")
    try:
        ss_manager = SpreadsheetManager(config)
    except Exception as e:
        print(f"SpreadsheetManagerの初期化に失敗しました: {e}")
        return

    while not shutdown_flag.is_set():
        print("\n" + "="*60)
        account = ss_manager.find_and_lock_account()
        if not account:
            shutdown_flag.wait(60)
            continue
        
        print(f"アカウント: {account['id']} ({account['row_num']}行目) の処理サイクルを開始します。")
        login_manager, search_thread = None, None
        found_event = None # finallyブロックで参照できるようスコープを広げる
        try:
            login_manager = LoginManager(account, config)
            event_queue = queue.Queue()
            search_thread = threading.Thread(
                target=event_search_worker,
                args=(event_queue, config, shutdown_flag),
                daemon=True
            )
            search_thread.start()
            print(f"[{account['id']}] 監視ワーカースレッドを開始。キューを待機中...")

            found_event = event_queue.get() 
            
            if found_event is None or shutdown_flag.is_set():
                ss_manager.unlock_account_with_error(account['row_num'], "検索スレッド異常終了")
                continue

            print(f"[{account['id']}] ★★★ キューからイベントを取得！直ちに応募開始 -> {found_event.title}")
            
            success, message = login_manager.execute_apply(found_event)

            if success:
                print(f"🎉 応募成功: {account['id']}")
                try:
                    screenshot_path = None
                    login_manager.driver.get(MYPAGE_EVENT_LIST_URL)
                    WebDriverWait(login_manager.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "section.eventListForm")))
                    time.sleep(2)
                    extracted_details = extract_event_details_from_mypage(login_manager.driver)
                    if extracted_details:
                        details_for_spreadsheet = extracted_details
                    else:
                        print("警告: マイページからの詳細取得に失敗。検索時の情報で記録します。")
                    filename = f"applied_{account['id'].replace('@', '_').replace('.', '_')}.png"
                    ss_success, result = take_full_page_screenshot(login_manager.driver, filename)
                    if ss_success: screenshot_path = result
                except Exception as e:
                    print(f"❌ SS撮影または詳細情報取得の過程でエラー: {e}")
                    message += f"\n(注意: SS撮影/詳細取得に失敗)"
                
                ss_manager.update_account_result(account['row_num'], True, found_event, message)
            else:
                print(f"❌ 応募失敗: {account['id']}。スクリーンショットを撮影します。")
                screenshot_path = None
                try:
                    filename = f"failed_applied_{account['id'].replace('@', '_').replace('.', '_')}.png"
                    ss_success, result = take_full_page_screenshot(login_manager.driver, filename)
                    if ss_success: screenshot_path = result
                except Exception as e:
                    message += f"\n(注意: 失敗時のSS撮影に失敗 - {e})"
                ss_manager.update_account_result(account['row_num'], False, None, message)

            result_message = create_monitoring_result_message(config['notification_method'], found_event, account, success, message)
            send_notification(config, result_message, screenshot_path)
            if screenshot_path and os.path.exists(screenshot_path): os.remove(screenshot_path)

        except Exception as e:
            event_title = found_event.title if found_event else "イベント発見前"
            report_base = handle_browser_crash(login_manager.driver if login_manager else None, account['id'], event_title, e)
            ss_manager.unlock_account_with_error(account['row_num'], f"{e.__class__.__name__}")
            error_message = create_crash_report_message(config['notification_method'], account['id'], event_title, e, report_base)
            error_ss_path = f"{report_base}.png"
            if os.path.exists(error_ss_path):
                send_notification(config, error_message, error_ss_path)
                os.remove(error_ss_path)
            else:
                send_notification(config, error_message)
        finally:
            if login_manager: login_manager.shutdown()
            if search_thread and search_thread.is_alive():
                search_thread.join(timeout=10)
            print(f"アカウント {account['id']} の処理サイクルを完了しました。")

def main_http_monitoring_mode(config, shutdown_flag):
    """【HTTPリクエスト版】監視モード"""
    print("--- 監視モードを開始します (HTTPリクエスト/最速アーキテクチャ) ---")
    try:
        ss_manager = SpreadsheetManager(config)
    except Exception as e:
        print(f"SpreadsheetManagerの初期化に失敗しました: {e}")
        return

    search_session = None
    try:
        # --- (1) 監視ループ ---
        search_session = requests.Session()
        search_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        })

        found_event = None
        while not shutdown_flag.is_set():
            print("[HTTP Search] イベントを検索中...")
            events = check_for_events_http(search_session, config)
            if events:
                found_event = events[0]
                print(f"[HTTP Search] ★★★ イベント発見！応募処理を開始します -> {found_event.title}")
                break
            time.sleep(config['interval'])

        if not found_event or shutdown_flag.is_set():
            print("[HTTP Search] イベントが見つからないか、停止信号を受け取ったため終了します。")
            return

        # --- (2) アカウント応募処理ループ ---
        while not shutdown_flag.is_set():
            account = ss_manager.find_and_lock_account()
            if not account:
                print("応募可能なアカウントが見つかりませんでした。60秒待機します。")
                shutdown_flag.wait(60)
                continue

            log_prefix = f"[{account['id']}]"
            print(f"{log_prefix} の処理サイクルを開始します。")
            login_manager = None
            try:
                # 1. ログイン
                login_manager = HttpLoginManager(account, config)

                # 2. 応募リクエスト
                success, message = execute_apply_http(
                    login_manager.session,
                    found_event,
                    account['type'],
                    config
                )

                # 3. 結果処理
                if success:
                    print(f"🎉 {log_prefix} 応募成功: {account['id']}")
                    ss_manager.update_account_result(account['row_num'], True, found_event, message)
                else:
                    print(f"❌ {log_prefix} 応募失敗: {account['id']}")
                    ss_manager.update_account_result(account['row_num'], False, None, message)

                result_message = create_monitoring_result_message(
                    config['notification_method'], found_event, account, success, message
                )
                send_notification(config, result_message)

            except Exception as e:
                print(f"❌ {log_prefix} 処理中に致命的なエラーが発生しました: {e}")
                traceback.print_exc()
                ss_manager.unlock_account_with_error(account['row_num'], f"{e.__class__.__name__}")
                error_message = create_crash_report_message(
                    config['notification_method'], account['id'], found_event.title, e, "N/A (HTTP Mode)"
                )
                send_notification(config, error_message)
            finally:
                if login_manager:
                    login_manager.shutdown()
                print(f"{log_prefix} の処理サイクルを完了しました。")

    except Exception as e:
        print(f"HTTP監視モードの実行中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        if search_session:
            search_session.close()
        print("--- HTTP監視モードを終了します ---")


def process_single_account_for_organizer(args):
    """【整理モード用】単一アカウントの処理を並列実行するためのワーカー関数"""
    account, config, ss_manager, i, total = args
    log_prefix = f"[{i+1}/{total}] ID: {account.id}"
    print(f"--- {log_prefix} ({account.row_num}行目) の処理を開始 ---")
    
    driver = None
    try:
        driver = setup_driver(headless=config['headless'])
        threading.current_thread().driver = driver
        result = scrape_and_process_account_action(driver, account, config)

        # サイト上に応募可能な空きがあり、かつスプシに未来の予定が残っている場合、その予定をクリアする
        should_clear_schedule = False
        if result.status == 'available' and account.ss_event_date:
            try:
                # スプレッドシートの日付をdateオブジェクトに変換して今日より未来か判定
                event_date_obj = datetime.strptime(account.ss_event_date.replace('/', '-'), '%Y-%m-%d').date()
                if event_date_obj > date.today():
                    print(f"  -> サイト上に予定なし。スプレッドシートの未来の予定({account.ss_event_date})をクリアします。")
                    should_clear_schedule = True
            except ValueError:
                # 日付形式が不正な場合は何もしない
                print(f"  -> スプレッドシートの日付形式({account.ss_event_date})が不正なため、クリア処理をスキップ。")

        if should_clear_schedule:
            # プレイヤー名など基本情報は維持しつつ、イベント関連情報のみをクリアする
            updated_data = result.data.copy() if result.data else {}
            updated_data.update({
                'eventDate': '', 'eventStore': '', 'eventTime': '',
                'eventUrl': '', 'participationStatus': ''
            })
            clear_result = ScrapeResult(status='available', data=updated_data)
            ss_manager.update_account_info(account.row_num, clear_result)
        else:
            ss_manager.update_account_info(account.row_num, result)

        # 親プロセスに結果を返す
        if result.status == 'available':
            # 'participant'は結果に含まれないため、元のaccountオブジェクトから引き継ぐ
            result.data['participant'] = account.participant
            return 'available', result.data
        elif result.status == 'scheduled':
            result.data['participant'] = account.participant
            return 'scheduled', result.data
        else:
            return 'error', None

    except Exception as e:
        print(f"アカウント {account.id} の処理中に予期せぬエラー: {e}")
        traceback.print_exc()
        ss_manager.unlock_account_with_error(account.row_num, f"処理エラー: {e.__class__.__name__}")
        return 'error', None
    finally:
        if driver:
            driver.quit()
        print(f"--- {log_prefix} の処理を完了 ---")

def main_organizer_mode(config, shutdown_flag):
    """
    全アカウントの状態をチェックし、スプレッドシートを更新後、
    応募可能なアカウントで設定ファイルを生成するモード。
    """
    print("--- アカウント整理モードを開始します ---")
    ss_manager = None
    try:
        ss_manager = SpreadsheetManager(config)
        all_accounts = ss_manager.get_all_accounts()
        if not all_accounts:
            print("スプレッドシートからアカウント情報が取得できませんでした。")
            return

        print(f"全 {len(all_accounts)} 件のアカウントを処理します。")
        
        tasks = [(acc, config, ss_manager, i, len(all_accounts)) for i, acc in enumerate(all_accounts)]
        
        final_results = []
        max_workers = config.get('max_concurrent_browsers', 2)
        print(f"最大 {max_workers} のブラウザで並列処理を開始します。")

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        active_futures = set()
        try:
            future_to_task = {executor.submit(process_single_account_for_organizer, task): task for task in tasks}
            active_futures = set(future_to_task.keys())
            for future in concurrent.futures.as_completed(future_to_task):
                if shutdown_flag.is_set(): # Ctrl+Cが押されたかをチェック
                    print("\n停止信号を検知したため、並列処理を中断します。")
                    break 
                try:
                    final_results.append(future.result())
                    active_futures.remove(future)
                except Exception as exc:
                    print(f'タスク実行中に例外が発生: {exc}')
                except KeyboardInterrupt:
                    print("\n[main] CtrlCを検知。全スレッドに停止信号を送ります...")
                    shutdown_flag.set()
        finally:
            # Ctrl+Cが押されていたら、タスクの完了を待たずにシャットダウン
            if shutdown_flag.is_set():
                print("実行中のブラウザを強制終了しています...")
                # 実行中のスレッドに紐付いたdriverを終了させる
                for thread in threading.enumerate():
                    if hasattr(thread, 'driver') and thread.driver:
                        thread.driver.quit()
                executor.shutdown(wait=False)
            else:
                executor.shutdown(wait=True)

        print("\n--- 全アカウントの並列処理が完了しました ---")
        
        # 結果を集計
        available_accounts_for_config = [data for status, data in final_results if status == 'available' and data]
        scheduled_events_summary = [data for status, data in final_results if status == 'scheduled' and data]
        
        # 設定ファイルの生成
        if available_accounts_for_config:
            generate_config_files(available_accounts_for_config, config.get('config_output_basename', 'config'))

        # サマリー通知の送信
        print("\n最終通知を準備しています...")
        summary_messages = create_organizer_summary_message(scheduled_events_summary)
        for message in summary_messages:
            send_notification(config, message)
            time.sleep(1) # 連投制限対策
        
        print("全ての処理が完了しました。")

    except Exception as e:
        print(f"アカウント整理モードの実行中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        print("--- アカウント整理モードを終了します ---")

def main():
    print("--- ポケモンカード イベント自動応募プログラム ---")
    config = load_config()
    shutdown_flag = threading.Event()
    try:
        mode = config.get('operation_mode', 0)
        if mode == 1:
            main_monitoring_mode(config, shutdown_flag)
        elif mode == 2:
            main_organizer_mode(config, shutdown_flag)
        elif mode == 3:
            main_http_monitoring_mode(config, shutdown_flag)
        elif mode == 0:
            print("モード: 0 (通常モード)")
            if config['data_source'] == 'spreadsheet':
                main_spreadsheet_mode(config, shutdown_flag)
            elif config['data_source'] == 'config':
                main_config_mode(config, shutdown_flag)
        else: print(f"エラー: 不明なOperationMode '{mode}'")
    except KeyboardInterrupt:
        print("\n[main] CtrlCを検知。全スレッドに停止信号を送ります...")
        shutdown_flag.set()
        time.sleep(3)
    print("\n" + "="*60 + "\nプログラムを終了します。\n" + "="*60)

if __name__ == '__main__':
    main()