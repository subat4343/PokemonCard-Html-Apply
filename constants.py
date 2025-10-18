# constants.py
BASE_URL = "https://players.pokemon-card.com"
LOGIN_URL = f"{BASE_URL}/login"
LOGIN_PLAYER_URL = f"{BASE_URL}/login_player"
MYPAGE_URL = f"{BASE_URL}/mypage"
MYPAGE_EVENT_LIST_URL = f"{BASE_URL}/mypage/myevent/list"
MYPAGE_RESULT_SEARCH_URL = f"{BASE_URL}/mypage/event_result"
EVENT_DETAIL_URL_PREFIX = f"{BASE_URL}/event/detail/"
EVENT_PARTICIPATION_URL = f"{BASE_URL}/event_participation"

# --- スプレッドシート関連の定数 ---
# 監視モード用ロック値
SS_LOCK_DATE_VALUE = '1900-01-01'
SS_LOCK_STATUS_VALUE = '【処理中】'

# アカウント管理シートの列名
SS_COL_ID = 'ID'
SS_COL_PASS = 'PASS'
SS_COL_TYPE = '区分'
SS_COL_PARTICIPANT = '参加者'
SS_COL_ACTION = '参加者' # アクション指示も '参加者' 列を使用
SS_COL_PLAYER_NAME = 'プレイヤー名'
SS_COL_EVENT_DATE = '日付'
SS_COL_EVENT_STORE = '店舗'
SS_COL_EVENT_TIME = '時間'
SS_COL_EVENT_URL = 'イベントURL'
SS_COL_PARTICIPATION_STATUS = '参加ステータス'