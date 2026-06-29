import hashlib
import os
import tempfile
from datetime import datetime
from typing import Optional

import bcrypt
import requests

from src.logger import get_logger

logger = get_logger("coros_client")

COROS_API_BASE = "https://teameuapi.coros.com"
AUTH_URL = f"{COROS_API_BASE}/account/login"
ACTIVITIES_URL = f"{COROS_API_BASE}/activity/query"
DOWNLOAD_URL = f"{COROS_API_BASE}/activity/detail/download"
DASHBOARD_URL = f"{COROS_API_BASE}/dashboard/query"
ANALYSE_DETAIL_URL = f"{COROS_API_BASE}/analyse/dayDetail/query"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Origin": "https://training.coros.com",
    "Referer": "https://training.coros.com/",
    "Content-Type": "application/json",
}

SPORT_TYPE_RUNNING = 100
SPORT_TYPE_TRAIL_RUNNING = 101
SPORT_TYPES_RUN = {SPORT_TYPE_RUNNING, SPORT_TYPE_TRAIL_RUNNING}

# Ошибка аутентификации Coros (Coros authentication error)
class CorosAuthError(Exception):
    pass

# Ошибка API Coros (Coros API error)
class CorosAPIError(Exception):
    pass

# Хэш пароля Coros: MD5 + bcrypt (Coros password hash: MD5 + bcrypt)
def _coros_hash(password: str) -> tuple[str, str]:
    password_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    salt = bcrypt.gensalt(rounds=10)
    hashed = bcrypt.hashpw(password_md5.encode("utf-8"), salt)
    return hashed.decode("utf-8"), salt.decode("utf-8")

# Клиент для неофициального API Coros Training Hub (Coros Training Hub API client)
class CorosClient:
    def __init__(self, email: str, password: str, timeout: int = 30):
        self.email = email
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.accesstoken: Optional[str] = None
        self.user_id: Optional[str] = None

    # Аутентификация на Coros API (Coros API authentication)
    def authenticate(self) -> bool:
        hashed, salt = _coros_hash(self.password)
        payload = {
            "account": self.email,
            "accountType": 2,
            "p1": hashed,
            "p2": salt,
        }
        try:
            resp = self.session.post(AUTH_URL, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != "0000":
                raise CorosAuthError(f"Auth failed: {data.get('message', 'Unknown error')}")
            self.accesstoken = data["data"]["accessToken"]
            self.user_id = str(data["data"]["userId"])
            self.session.cookies["CPL-coros-token"] = self.accesstoken
            logger.info("Coros auth successful for %s", self.email)
            return True
        except requests.RequestException as e:
            raise CorosAuthError(f"Network error: {e}") from e

    # Заголовки авторизации для API-запросов (Authorization headers for API requests)
    def _auth_headers(self) -> dict:
        return {
            "accesstoken": self.accesstoken,
            "yfheader": f'{{"userId":"{self.user_id}"}}',
        }

    # Получить список активностей с пагинацией (Get activity list with pagination)
    def list_activities(self, limit: int = 50, since: Optional[datetime] = None) -> list[dict]:
        if not self.accesstoken:
            raise CorosAPIError("Not authenticated")
        limit = min(limit, 200)
        params = {"size": limit, "pageNumber": 1, "modeList": ""}
        resp = self.session.get(ACTIVITIES_URL, params=params, headers=self._auth_headers(), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "0000":
            raise CorosAPIError(f"API error: {data.get('message')}")

        total_pages = data.get("data", {}).get("totalPage", 1)
        all_items = list(data.get("data", {}).get("dataList", []))

        for page in range(2, total_pages + 1):
            params["pageNumber"] = page
            resp = self.session.get(ACTIVITIES_URL, params=params, headers=self._auth_headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") == "0000":
                all_items.extend(data.get("data", {}).get("dataList", []))

        since_ts = since.timestamp() if since else 0
        activities = []
        for act in all_items:
            sport_type = act.get("sportType", 999)
            if sport_type not in SPORT_TYPES_RUN:
                continue
            start_ts = act.get("startTime")
            if not start_ts:
                continue
            if since_ts and start_ts <= since_ts:
                continue
            activities.append({
                "id": str(act["labelId"]),
                "name": act.get("name", ""),
                "sport_type": sport_type,
                "start_time": datetime.fromtimestamp(start_ts),
                "end_time": datetime.fromtimestamp(act.get("endTime", start_ts)),
                "distance_m": float(act.get("distance", 0)),
                "duration_s": act.get("workoutTime", 0),
            })
        return activities

    # Получить данные дашборда — HRV за последние 7 дней (Get dashboard data — HRV for last 7 days)
    def get_dashboard(self) -> dict:
        if not self.accesstoken:
            raise CorosAPIError("Not authenticated")
        resp = self.session.get(DASHBOARD_URL, headers=self._auth_headers(), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "0000":
            raise CorosAPIError(f"Dashboard API error: {data.get('message')}")
        return data.get("data", {})

    # Получить ежедневные метрики за период (Get daily health metrics for date range)
    def get_daily_metrics(self, start_day: str, end_day: str) -> list[dict]:
        if not self.accesstoken:
            raise CorosAPIError("Not authenticated")
        params = {"startDay": start_day, "endDay": end_day}
        resp = self.session.get(ANALYSE_DETAIL_URL, params=params, headers=self._auth_headers(), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "0000":
            raise CorosAPIError(f"Analyse API error: {data.get('message')}")
        return data.get("data", [])

    # Скачать FIT-файл активности (Download activity FIT file)
    def download_fit(self, activity_id: str, sport_type: int, output_path: str) -> bool:
        if not self.accesstoken:
            raise CorosAPIError("Not authenticated")
        params = {"labelId": activity_id, "sportType": sport_type, "fileType": 4}
        resp = self.session.get(DOWNLOAD_URL, params=params, headers=self._auth_headers(), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "0000":
            logger.warning("Download API error for %s: %s", activity_id, data.get("message"))
            return False
        file_url = data.get("data", {}).get("fileUrl")
        if not file_url:
            return False
        file_resp = self.session.get(file_url, timeout=self.timeout)
        file_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(file_resp.content)
        return True
