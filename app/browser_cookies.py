import os
import json
import base64
import sqlite3
import shutil
import tempfile
import ctypes
import time
import logging
from ctypes import wintypes
from typing import List, Dict, Any, Tuple, Optional

if os.name == 'nt':
    import winreg
else:
    winreg = None

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

# Win32 DPAPI structures (standard cryptography, identical to yt-dlp)
crypt32 = ctypes.WinDLL('crypt32.dll') if os.name == 'nt' else None
kernel32 = ctypes.WinDLL('kernel32.dll') if os.name == 'nt' else None


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


# Browser catalog
BROWSER_DEFINITIONS = {
    'yandex': {
        'name': 'Яндекс Браузер',
        'type': 'chromium',
        'process': 'browser.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'Yandex\YandexBrowser\User Data',
    },
    'edge': {
        'name': 'Microsoft Edge',
        'type': 'chromium',
        'process': 'msedge.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'Microsoft\Edge\User Data',
    },
    'chrome': {
        'name': 'Google Chrome',
        'type': 'chromium',
        'process': 'chrome.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'Google\Chrome\User Data',
    },
    'brave': {
        'name': 'Brave Browser',
        'type': 'chromium',
        'process': 'brave.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'BraveSoftware\Brave-Browser\User Data',
    },
    'opera': {
        'name': 'Opera',
        'type': 'chromium',
        'process': 'opera.exe',
        'root_var': 'APPDATA',
        'subpath': r'Opera Software\Opera Stable',
    },
    'operagx': {
        'name': 'Opera GX',
        'type': 'chromium',
        'process': 'opera.exe',
        'root_var': 'APPDATA',
        'subpath': r'Opera Software\Opera GX Stable',
    },
    'vivaldi': {
        'name': 'Vivaldi',
        'type': 'chromium',
        'process': 'vivaldi.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'Vivaldi\User Data',
    },
    'chromium': {
        'name': 'Chromium',
        'type': 'chromium',
        'process': 'chromium.exe',
        'root_var': 'LOCALAPPDATA',
        'subpath': r'Chromium\User Data',
    },
    'firefox': {
        'name': 'Mozilla Firefox',
        'type': 'gecko',
        'process': 'firefox.exe',
        'root_var': 'APPDATA',
        'subpath': r'Mozilla\Firefox\Profiles',
    },
    'waterfox': {
        'name': 'Waterfox',
        'type': 'gecko',
        'process': 'waterfox.exe',
        'root_var': 'APPDATA',
        'subpath': r'Waterfox\Profiles',
    },
    'librewolf': {
        'name': 'LibreWolf',
        'type': 'gecko',
        'process': 'librewolf.exe',
        'root_var': 'APPDATA',
        'subpath': r'LibreWolf\Profiles',
    },
}


def get_browser_user_data_path(browser_key: str) -> Optional[str]:
    defn = BROWSER_DEFINITIONS.get(browser_key)
    if not defn:
        return None
    base = os.environ.get(defn['root_var'], '')
    if not base:
        return None
    full = os.path.join(base, defn['subpath'])
    return full if os.path.exists(full) else None


def detect_installed_browsers() -> List[Tuple[str, str]]:
    """Returns list of (browser_key, display_name) for installed browsers that have user data."""
    installed = []
    for key, defn in BROWSER_DEFINITIONS.items():
        path = get_browser_user_data_path(key)
        if path:
            installed.append((key, defn['name']))
    return installed


def unprotect_dpapi(encrypted_data: bytes) -> bytes:
    if not crypt32 or not kernel32:
        return b""
    in_blob = DATA_BLOB(len(encrypted_data), ctypes.cast(encrypted_data, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    if crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        return res
    return b""


def get_chromium_master_key(local_state_path: str) -> Optional[bytes]:
    if not os.path.exists(local_state_path):
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        enc_key = base64.b64decode(data["os_crypt"]["encrypted_key"])
        if enc_key.startswith(b"DPAPI"):
            enc_key = enc_key[5:]
        return unprotect_dpapi(enc_key)
    except Exception:
        return None


def get_browser_cookie_db_path(browser_key: str) -> Tuple[Optional[str], Optional[str]]:
    """Returns (db_path, local_state_path)."""
    defn = BROWSER_DEFINITIONS.get(browser_key)
    if not defn:
        return None, None
    user_data = get_browser_user_data_path(browser_key)
    if not user_data:
        return None, None

    if defn['type'] == 'gecko':
        if os.path.exists(user_data):
            for d in os.listdir(user_data):
                candidate = os.path.join(user_data, d, "cookies.sqlite")
                if os.path.exists(candidate):
                    return candidate, None
        return None, None

    local_state = os.path.join(user_data, "Local State")
    candidates = [
        os.path.join(user_data, "Default", "Network", "Cookies"),
        os.path.join(user_data, "Network", "Cookies"),
        os.path.join(user_data, "Default", "Cookies"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c, local_state

    # Check numbered profiles
    try:
        for item in os.listdir(user_data):
            if item.startswith("Profile "):
                c = os.path.join(user_data, item, "Network", "Cookies")
                if os.path.exists(c):
                    return c, local_state
    except OSError:
        pass

    return None, local_state


def soft_restart_chrome_and_copy(db_path: str, tmp_db: str, tmp_wal: str) -> bool:
    """
    Safely copies Chrome cookies database without killing or restarting any processes.
    Strictly avoids taskkill to protect active user sessions and external apps (e.g. Discord).
    """
    try:
        shutil.copy2(db_path, tmp_db)
        if os.path.exists(db_path + "-wal"):
            try:
                shutil.copy2(db_path + "-wal", tmp_wal)
            except Exception:
                pass
        return True
    except (PermissionError, OSError):
        logger.debug("[BrowserCookies] Chrome SQLite database is locked by running browser. Skipping Chrome copy without process interruption.")
        return False


def extract_cookies_live(browser_key: str, domain_filter: str = "") -> List[Dict[str, Any]]:
    """
    Extracts fresh cookies from the specified browser.
    """
    defn = BROWSER_DEFINITIONS.get(browser_key)
    if not defn:
        return []

    db_path, local_state = get_browser_cookie_db_path(browser_key)
    if not db_path:
        return []

    is_gecko = defn['type'] == 'gecko'
    master_key = get_chromium_master_key(local_state) if (local_state and not is_gecko) else None

    with tempfile.TemporaryDirectory() as td:
        tmp_db = os.path.join(td, "cookies_temp.db")
        tmp_wal = tmp_db + "-wal"
        copied = False

        # Safe standard file copy
        try:
            shutil.copy2(db_path, tmp_db)
            if os.path.exists(db_path + "-wal"):
                try:
                    shutil.copy2(db_path + "-wal", tmp_wal)
                except (PermissionError, OSError):
                    pass
            copied = True
        except (PermissionError, OSError):
            copied = False

        # If locked and browser is Chrome, soft-restart Chrome to copy
        if not copied and browser_key == 'chrome':
            copied = soft_restart_chrome_and_copy(db_path, tmp_db, tmp_wal)

        if not copied or not os.path.exists(tmp_db):
            return []

        cookies = []
        try:
            conn = sqlite3.connect(tmp_db)
            cur = conn.cursor()

            if is_gecko:
                query = "SELECT host, name, value, path, expiry, isSecure FROM moz_cookies"
                params = []
                if domain_filter:
                    query += " WHERE host LIKE ?"
                    params.append(f"%{domain_filter}%")
                cur.execute(query, params)
                for row in cur.fetchall():
                    cookies.append({
                        "domain": row[0],
                        "name": row[1],
                        "value": row[2],
                        "path": row[3],
                        "expires": row[4],
                        "secure": bool(row[5])
                    })
            else:
                aesgcm = AESGCM(master_key) if (master_key and AESGCM) else None
                query = "SELECT host_key, name, encrypted_value, path, expires_utc, is_secure FROM cookies"
                params = []
                if domain_filter:
                    query += " WHERE host_key LIKE ?"
                    params.append(f"%{domain_filter}%")
                cur.execute(query, params)
                for row in cur.fetchall():
                    val = row[2]
                    decrypted_val = ""
                    if val:
                        if val.startswith(b"v10") and aesgcm:
                            try:
                                decrypted_val = aesgcm.decrypt(val[3:15], val[15:], None).decode("utf-8", errors="replace")
                            except Exception:
                                pass
                        elif val.startswith(b"v20"):
                            # Chrome 127+ App-Bound encryption
                            continue
                        else:
                            try:
                                decrypted_val = unprotect_dpapi(val).decode("utf-8", errors="replace")
                            except Exception:
                                pass

                    if decrypted_val:
                        chrom_ts = row[4]
                        unix_ts = int((chrom_ts - 11644473600000000) / 1000000) if chrom_ts > 11644473600000000 else 0
                        cookies.append({
                            "domain": row[0],
                            "name": row[1],
                            "value": decrypted_val,
                            "path": row[3],
                            "expires": unix_ts,
                            "secure": bool(row[5])
                        })
            conn.close()
        except Exception:
            return []

        return cookies


COOKIE_CACHE_TTL = 300.0  # 5 minutes in seconds
COOKIE_META_FILE = os.path.join(tempfile.gettempdir(), "umd_cookies", "cookie_cache_meta.json")


def _load_cookie_cache_meta() -> dict:
    if os.path.exists(COOKIE_META_FILE):
        try:
            with open(COOKIE_META_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cookie_cache_meta(meta: dict):
    try:
        os.makedirs(os.path.dirname(COOKIE_META_FILE), exist_ok=True)
        with open(COOKIE_META_FILE, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
    except Exception:
        pass


def get_cached_cookiefile(browser_key: str) -> Tuple[Optional[str], int]:
    """
    Returns (path_to_cookiefile, count) if valid cached cookiefile exists and is younger than 5 minutes (300s).
    If an attempt was recently made (< 5 min) and produced 0 cookies, returns (None, -1) to prevent repeated restart attempts.
    """
    now = time.time()
    meta = _load_cookie_cache_meta()
    b_meta = meta.get(browser_key)
    if b_meta and isinstance(b_meta, dict):
        path = b_meta.get('path', '')
        count = b_meta.get('count', 0)
        ts = b_meta.get('time', 0.0)
        last_attempt = b_meta.get('last_attempt', 0.0)
        if path and os.path.exists(path) and (now - ts < COOKIE_CACHE_TTL) and count > 0:
            logger.debug(f"[BrowserCookies] Using cached cookies for '{browser_key}' (age: {now - ts:.1f}s / TTL: {COOKIE_CACHE_TTL}s)")
            return path, count
        if now - last_attempt < COOKIE_CACHE_TTL:
            logger.debug(f"[BrowserCookies] Recent extraction attempt for '{browser_key}' was < {COOKIE_CACHE_TTL}s ago. Skipping restart.")
            return None, -1
    return None, 0


def generate_netscape_cookiefile(browser_key: str, output_path: Optional[str] = None, force_refresh: bool = False) -> Tuple[Optional[str], int]:
    """
    Extracts live cookies from the specified browser and writes a Netscape cookies.txt file.
    Caches the generated cookiefile for 5 minutes (300 seconds) so that multiple downloads
    or restarts do not repeatedly close or relaunch the browser.
    Returns (path_to_cookiefile, count_of_cookies).
    """
    if not force_refresh:
        cached_path, cached_count = get_cached_cookiefile(browser_key)
        if cached_path and cached_count > 0:
            return cached_path, cached_count
        if cached_count == -1:
            # Cooldown active for this browser
            return None, 0

    cookies = extract_cookies_live(browser_key)
    if not cookies:
        # Cache failed / empty attempt for 5 minutes to prevent repeated browser restarts
        meta = _load_cookie_cache_meta()
        if browser_key not in meta or not isinstance(meta[browser_key], dict):
            meta[browser_key] = {}
        meta[browser_key]['last_attempt'] = time.time()
        meta[browser_key]['count'] = 0
        _save_cookie_cache_meta(meta)
        return None, 0

    if not output_path:
        tmp_dir = os.path.join(tempfile.gettempdir(), "umd_cookies")
        os.makedirs(tmp_dir, exist_ok=True)
        output_path = os.path.join(tmp_dir, f"{browser_key}_live_cookies.txt")

    lines = [
        "# Netscape HTTP Cookie File",
        f"# Live exported from {browser_key.capitalize()} without browser shutdown",
        ""
    ]
    for c in cookies:
        domain = str(c.get("domain", "")).replace("\r", "").replace("\n", "").replace("\t", "").strip()
        if not domain:
            continue
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(c.get("path", "/")).replace("\r", "").replace("\n", "").replace("\t", "").strip() or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", 0) or 2147483647))
        name = str(c.get("name", "")).replace("\r", "").replace("\n", "").replace("\t", "").strip()
        value = str(c.get("value", "")).replace("\r", "").replace("\n", "").replace("\t", "")
        if not name:
            continue
        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Persist cache metadata for 5 minutes TTL
    meta = _load_cookie_cache_meta()
    meta[browser_key] = {
        'path': output_path,
        'count': len(cookies),
        'time': time.time(),
        'last_attempt': time.time()
    }
    _save_cookie_cache_meta(meta)

    return output_path, len(cookies)


def get_best_browser_cookiefile(preferred_browser: str = 'none', force_refresh: bool = False) -> Tuple[Optional[str], int, str]:
    """
    Returns (path_to_cookiefile, count_of_cookies, browser_display_name).
    Uses 5-minute cache to avoid repeated browser soft-restarts.
    Tries preferred_browser first. If 0 cookies, checks other installed browsers.
    """
    installed = detect_installed_browsers()
    installed_dict = dict(installed)

    # 1. Try preferred browser
    if preferred_browser and preferred_browser != 'none' and preferred_browser in installed_dict:
        cf, count = generate_netscape_cookiefile(preferred_browser, force_refresh=force_refresh)
        if cf and count > 0:
            return cf, count, installed_dict[preferred_browser]

    # 2. Check other installed browsers as fallback
    for b_key, b_name in installed:
        if b_key == preferred_browser or b_key == 'none':
            continue
        cf, count = generate_netscape_cookiefile(b_key, force_refresh=force_refresh)
        if cf and count > 0:
            return cf, count, b_name

    return None, 0, ''
