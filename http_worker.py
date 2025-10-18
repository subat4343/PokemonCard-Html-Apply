# http_worker.py
import requests
import time
import traceback
import json
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from constants import BASE_URL, LOGIN_PLAYER_URL, EVENT_PARTICIPATION_URL
from models import Event

# --- HTTPリクエスト版 ワーカースレッド ---

class HttpLoginManager:
    """
    HTTPリクエスト(requests)を使用してログインセッションを管理するクラス。
    """
    def __init__(self, account, config):
        self.account = account
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'X-Accept-Version': 'v1',
            'Origin': BASE_URL,
        })
        self.log_prefix = f"[HTTP: {self.account['id']}]"

        print(f"{self.log_prefix} 初期化処理を開始します。")
        success, message = self._login()
        if not success:
            self.shutdown()
            raise Exception(f"{self.log_prefix} 初期ログインに失敗しました: {message}")
        print(f"{self.log_prefix} ログインに成功しました。")

    def _login(self):
        """
        /login_player エンドポイントに認証情報をPOSTし、
        レスポンスから認証トークン(JWT)を取得してセッションに設定する。
        """
        try:
            # HARファイルの解析に基づき、キー名を player_id と password に設定
            login_payload = {
                'player_id': self.account['id'],
                'password': self.account['pass'],
            }

            res = self.session.post(LOGIN_PLAYER_URL, data=login_payload, timeout=self.config['wait_timeout'])
            res.raise_for_status()
            res_json = res.json()
            
            if res_json.get('code') == 200 and res_json.get('token'):
                # 認証トークンをヘッダーに設定
                self.session.headers.update({
                    'X-Authentication': res_json['token'],
                    'X-Authentication-Deadline': res_json['token_deadline'],
                })
                return True, "ログイン成功"
            else:
                return False, f"ログイン失敗: {res_json.get('message', '不明なエラー')}"
        except requests.exceptions.RequestException as e:
            return False, f"ログインリクエスト中にエラー: {e}"
        except json.JSONDecodeError:
            return False, f"ログインレスポンスの解析に失敗(JSON不正)。"
        except Exception as e:
            return False, f"ログイン処理中に予期せぬエラー: {e}"

    def shutdown(self):
        """セッションをクローズする"""
        self.session.close()
        print(f"{self.log_prefix} 終了処理が完了しました。")


def _check_for_events_http(session, config):
    """
    イベント検索APIを直接叩いて、応募可能なイベントを検出する
    """
    api_url = "https://players.pokemon-card.com/event_search"
    params = {
        "keyword": config.get("keyword", ""),               # 検索キーワード
        "prefecture[]": config.get("prefecture_list", [13]), # 都道府県リスト
        "offset": 0,
        "accepting": "true",                                # 募集中イベントのみ
        "order": 1,
    }

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        ),
        "X-Accept-Version": "v1",
        "X-Authentication": "null",
        "X-Authentication-Deadline": "null",
    }

    try:
        res = session.get(api_url, params=params, headers=headers, timeout=config["wait_timeout"])
        
        # API仕様上、イベントが存在しない場合は404を返す
        if res.status_code == 404:
            print("[HTTP Search] イベントなし (404)")
            return []

        res.raise_for_status()
        data = res.json()

        if data.get("code") != 200:
            print(f"[HTTP Search] APIエラー応答: {data}")
            return []

        found_events = []
        for e in data.get("event", []):
            title = e.get("event_title")
            event_id = e.get("event_holding_id")
            status_code = e.get("entryStatusCode")
            full = e.get("fullOccupiedFlg")

            # 先着受付中 (2) かつ 満席でない (0)
            if status_code == 2 and full == 1:
                url = f"https://players.pokemon-card.com/event/{event_id}"
                found_events.append(Event(title=title, url=url))
                print(f"[HTTP Search] ✅ 募集中イベント検出: {title}")

        if not found_events:
            print("[HTTP Search] 該当イベントなし")

        return found_events

    except requests.exceptions.RequestException as e:
        print(f"[HTTP Search] 通信エラー: {e}")
        return []
    except json.JSONDecodeError:
        print("[HTTP Search] JSON解析エラー: レスポンスが不正")
        return []
    except Exception as e:
        print(f"[HTTP Search] 予期しないエラー: {e}")
        return []


def _get_apply_payload_http(session, event_info, config):
    """
    イベント詳細ページを解析し、応募に必要なペイロード情報を抽出する。
    ※注意: この部分はサイトのHTML構造に強く依存します。
    """
    log_prefix = f"[HTTP Parser: {event_info.title[:15]}]"
    try:
        print(f"{log_prefix} イベントページから応募情報を抽出中...")
        res = session.get(event_info.url, timeout=config['wait_timeout'])
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')

        # 応募ボタンがなければ終了
        if not soup.select_one("div#anchor4 button.c-btn-primary"):
            return None, "応募ボタンが見つかりませんでした（時間差で埋まった可能性）"

        # 隠しフォームフィールドから応募情報を抽出
        form = soup.select_one('form[action="/event_participation"]')
        if not form:
            return None, "応募情報を含むフォームが見つかりません。"

        payload = {}
        for input_tag in form.select('input[type="hidden"]'):
            name = input_tag.get('name')
            value = input_tag.get('value')
            if name and value is not None:
                payload[name] = value

        # 必須と思われるキーが存在するかチェック
        if 'event_holding_id' not in payload:
            return None, "必須パラメータ 'event_holding_id' がページから抽出できませんでした。"

        return payload, "ペイロード抽出成功"

    except requests.exceptions.RequestException as e:
        return None, f"ページ取得中にエラー: {e}"
    except Exception:
        traceback.print_exc()
        return None, "ページ解析中に予期せぬエラー"

def execute_apply_http(session, event_info, account_type, config):
    """
    【HTTPリクエスト版】イベントページを解析してペイロードを作成し、応募リクエストを送信する。
    """
    log_prefix = f"[HTTP Apply: {event_info.title[:15]}]"
    try:
        apply_payload, msg = _get_apply_payload_http(session, event_info, config)
        if not apply_payload:
            return False, msg

        print(f"{log_prefix} 応募リクエストを送信中...")
        apply_res = session.post(EVENT_PARTICIPATION_URL, data=apply_payload, timeout=config['wait_timeout'])
        apply_res.raise_for_status()
        res_json = apply_res.json()

        if res_json.get('code') == 200:
            return True, res_json.get('message', '応募が完了しました！')
        else:
            return False, f"応募エラー: {res_json.get('message', '不明なエラー')}"

    except requests.exceptions.RequestException as e:
        return False, f"応募リクエスト中にエラー: {e}"
    except json.JSONDecodeError:
        return False, "応募レスポンスの解析に失敗(JSON不正)。"
    except Exception as e:
        traceback.print_exc()
        return False, f"応募実行中に予期せぬエラー: {e.__class__.__name__}"