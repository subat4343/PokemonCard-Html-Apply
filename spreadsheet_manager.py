# spreadsheet_manager.py
import sys
import gspread
from gspread.utils import rowcol_to_a1
from datetime import datetime

from constants import (
    SS_LOCK_DATE_VALUE, SS_LOCK_STATUS_VALUE, EVENT_DETAIL_URL_PREFIX,
    SS_COL_ID, SS_COL_PASS, SS_COL_TYPE, SS_COL_PARTICIPANT, SS_COL_ACTION,
    SS_COL_PLAYER_NAME, SS_COL_EVENT_DATE, SS_COL_EVENT_STORE, 
    SS_COL_EVENT_TIME, SS_COL_EVENT_URL,
    SS_COL_PARTICIPATION_STATUS
)
from models import Event, Account, ScrapeResult

GCP_SERVICE_ACCOUNT_FILE = 'credentials.json'

class SpreadsheetManager:
    def __init__(self, config):
        try:
            gc = gspread.service_account(filename=GCP_SERVICE_ACCOUNT_FILE)
            
            account_book_name = config.get('account_book_name')
            account_sheet_name = config.get('account_sheet_name')
            account_spreadsheet = gc.open(account_book_name)
            self.account_sheet = account_spreadsheet.worksheet(account_sheet_name)
            self.account_headers = self.account_sheet.row_values(1)
            print(f"✅ アカウント管理シート '{account_book_name}/{account_sheet_name}' に接続しました。")

            event_book_name = config.get('event_book_name')
            event_sheet_name = config.get('event_sheet_name')
            event_spreadsheet = gc.open(event_book_name)
            self.event_sheet = event_spreadsheet.worksheet(event_sheet_name)
            self.event_headers = self.event_sheet.row_values(1)
            print(f"✅ イベント管理シート '{event_book_name}/{event_sheet_name}' に接続しました。")
        except Exception as e:
            print(f"❌ Googleスプレッドシート接続エラー: {e}")
            sys.exit(1)

    def get_event_list(self):
        try:
            title_col = self.event_headers.index('実施店舗') + 1
            url_col = self.event_headers.index('イベントURL') + 1
            date_col = self.event_headers.index('日付') + 1
            time_col = self.event_headers.index('時間') + 1 
        except ValueError as e:
            print(f"❌ イベント管理シートのヘッダーに {e} が見つかりません。")
            return []
            
        all_events_data = self.event_sheet.get_all_values()[1:]
        found_events = []
        for row in all_events_data:
            url = row[url_col - 1].strip()
            if url.startswith(EVENT_DETAIL_URL_PREFIX):
                title = row[title_col - 1].strip() or "タイトル不明"
                event_date = row[date_col - 1].strip() if len(row) >= date_col else ""
                event_time = row[time_col - 1].strip() if len(row) >= time_col else ""
                found_events.append(Event(title=title, url=url, date=event_date, time=event_time))
        return found_events

    def get_all_accounts(self):
        """アカウント管理シートから全てのアカウント情報を取得する"""
        try:
            id_col_idx = self.account_headers.index(SS_COL_ID)
            pass_col_idx = self.account_headers.index(SS_COL_PASS)
            type_col_idx = self.account_headers.index(SS_COL_TYPE)
            participant_col_idx = self.account_headers.index(SS_COL_PARTICIPANT)
            action_col_idx = self.account_headers.index(SS_COL_ACTION)
            date_col_idx = self.account_headers.index(SS_COL_EVENT_DATE)
            store_col_idx = self.account_headers.index(SS_COL_EVENT_STORE)
        except ValueError as e:
            print(f"❌ アカウント管理シートのヘッダーに '{e.args[0]}' が見つかりません。")
            return []
            
        all_accounts_data = self.account_sheet.get_all_values()[1:]
        accounts_list = []
        for i, row in enumerate(all_accounts_data):
            player_id = row[id_col_idx].strip()
            password = row[pass_col_idx].strip()
            
            if not player_id or not password:
                continue

            accounts_list.append(Account(
                id=player_id,
                password=password,
                type=row[type_col_idx].strip().lower() or 'general',
                participant=row[participant_col_idx].strip(),
                action=row[action_col_idx].strip(),
                row_num=i + 2,
                ss_event_date=row[date_col_idx].strip() or None,
                ss_event_store=row[store_col_idx].strip() or None
            ))
        return accounts_list

    def find_and_lock_account(self):
        try:
            date_col_idx = self.account_headers.index('日付')
            store_col_idx = self.account_headers.index('店舗')
            id_col_idx = self.account_headers.index(SS_COL_ID)
            pass_col_idx = self.account_headers.index(SS_COL_PASS)
            type_col_idx = self.account_headers.index(SS_COL_TYPE)
        except ValueError as e:
            print(f"❌ アカウント管理シートのヘッダーに {e} が見つかりません。")
            return None
        
        all_accounts = self.account_sheet.get_all_values()[1:]
        for i, row in enumerate(all_accounts):
            row_num = i + 2
            if not row[date_col_idx].strip():
                print(f"  -> {row_num}行目に空きアカウント候補を発見。ロックを試みます...")
                try:
                    self.account_sheet.batch_update([{
                        'range': f'{chr(ord("A")+date_col_idx)}{row_num}',
                        'values': [[SS_LOCK_DATE_VALUE]]
                    }, {
                        'range': f'{chr(ord("A")+store_col_idx)}{row_num}',
                        'values': [[SS_LOCK_STATUS_VALUE]]
                    }])
                    print(f"  -> アカウント '{row[id_col_idx]}' をロックしました。")
                    account_type_str = row[type_col_idx].lower()
                    if account_type_str not in ['general', 'senior']:
                        account_type_str = 'general'
                    return {'id': row[id_col_idx], 'pass': row[pass_col_idx], 'type': account_type_str, 'row_num': row_num}
                except gspread.exceptions.APIError as e:
                    print(f"  -> {row_num}行目のロック中にAPIエラーが発生しました: {e}。")
                    continue
        return None

    def update_account_result(self, row_num, success, event_info, message):
        """【監視モード用】応募結果をスプレッドシートに書き込む"""
        try:
            date_col_idx = self.account_headers.index('日付')
            store_col_idx = self.account_headers.index('店舗')
            time_col_idx = self.account_headers.index('時間')
            url_col_idx = self.account_headers.index('イベントURL')
            date_col_letter = chr(ord('A') + date_col_idx)
            store_col_letter = chr(ord('A') + store_col_idx)

            if success:
                # イベントに日付が設定されていない場合、応募成功日（今日）を代理で設定する
                event_date = event_info.date or (datetime.now().strftime('%Y/%m/%d') + " (日付不明)")
                update_data = [
                    event_date, event_info.title or '店舗名不明',
                    event_info.time or '',
                    event_info.url or ''
                ]
                end_col_letter = chr(ord('A') + url_col_idx)
                self.account_sheet.update(f'{date_col_letter}{row_num}:{end_col_letter}{row_num}', [update_data])
                print(f"  -> {row_num}行目を応募成功情報で更新しました。")
            else:
                self.account_sheet.batch_update([{
                    'range': f'{date_col_letter}{row_num}', 'values': [['']]
                }, {
                    'range': f'{store_col_letter}{row_num}', 'values': [[f"応募失敗: {message}"]]
                }])
                print(f"  -> {row_num}行目のロックを解除し、失敗メッセージを記録しました。")
        except (ValueError, gspread.exceptions.APIError) as e:
            print(f"❌ {row_num}行目の結果更新中にエラーが発生しました: {e}")

    def update_account_info(self, row_num, result: ScrapeResult):
        """【整理モード用】スクレイピング結果に基づいてアカウント情報を汎用的に更新する"""
        try:
            update_data = result.data or {}
            
            # 更新対象のデータと、それに対応するヘッダー名をマッピング
            data_to_header_map = {
                'participant': SS_COL_PARTICIPANT,
                'playerName': SS_COL_PLAYER_NAME,
                'accountType': SS_COL_TYPE,
                'eventDate': SS_COL_EVENT_DATE,
                'eventStore': SS_COL_EVENT_STORE,
                'eventTime': SS_COL_EVENT_TIME,
                'eventUrl': SS_COL_EVENT_URL,
                'participationStatus': SS_COL_PARTICIPATION_STATUS
            }

            batch_update_payload = []
            
            # マッピングを元に、更新するセルの位置と値を特定する
            for data_key, header_name in data_to_header_map.items():
                value_to_write = update_data.get(data_key)
                # データが存在する場合のみ更新リストに追加
                if value_to_write is not None:
                    try:
                        col_index = self.account_headers.index(header_name) + 1
                        cell_a1 = rowcol_to_a1(row_num, col_index)
                        batch_update_payload.append({'range': cell_a1, 'values': [[value_to_write]]})
                    except ValueError:
                        print(f"  -> 警告: ヘッダー '{header_name}' が見つからないため、更新をスキップします。")

            # 更新データがある場合のみAPIを呼び出す
            if batch_update_payload:
                self.account_sheet.batch_update(batch_update_payload)
                print(f"  -> {row_num}行目を更新しました (ステータス: {result.status})")
        except (ValueError, gspread.exceptions.APIError) as e:
            print(f"❌ {row_num}行目の更新中にエラーが発生しました: {e}")

    def unlock_account_with_error(self, row_num, error_message):
        """エラー発生時にアカウントのロックまたは情報を更新し、エラーメッセージを記録する"""
        try:
            date_col_idx = self.account_headers.index(SS_COL_EVENT_DATE)
            store_col_idx = self.account_headers.index(SS_COL_EVENT_STORE)
            date_col_letter = chr(ord('A') + date_col_idx)
            store_col_letter = chr(ord('A') + store_col_idx)
            self.account_sheet.batch_update([{
                'range': f'{date_col_letter}{row_num}', 'values': [['']]
            }, {
                'range': f'{store_col_letter}{row_num}', 'values': [[f"エラー発生: {error_message}"]]
            }])
            print(f"  -> {row_num}行目をクリアし、エラーメッセージを記録しました。")
            
        except (ValueError, gspread.exceptions.APIError) as e:
            print(f"❌ {row_num}行目のエラー解除処理中にさらにエラーが発生しました: {e}")