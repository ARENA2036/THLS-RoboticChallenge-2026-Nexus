import json
import time
import sqlite3
import os
import requests
from dotenv import load_dotenv

# Load .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

class DigiKeyClient:
    """Client for the DigiKey ProductSearch API v4."""

    OAUTH_URL = "https://api.digikey.com/v1/oauth2/token"
    # Using production API by default
    API_BASE = "https://api.digikey.com/products/v4"
    CACHE_FILE = os.path.join(os.path.dirname(__file__), "components_cache.db")

    def __init__(self, client_id: str = None, client_secret: str = None, use_sandbox: bool = False):
        self.client_id = client_id or os.environ.get("DIGIKEY_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("DIGIKEY_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            # Try reloading in case env was set after import
            load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
            self.client_id = self.client_id or os.environ.get("DIGIKEY_CLIENT_ID")
            self.client_secret = self.client_secret or os.environ.get("DIGIKEY_CLIENT_SECRET")

        self.locale = os.environ.get("DIGIKEY_LOCALE", "US")
        self.currency = os.environ.get("DIGIKEY_CURRENCY", "USD")
        self.language = os.environ.get("DIGIKEY_LANGUAGE", "en")
        
        if use_sandbox:
            self.API_BASE = "https://sandbox-api.digikey.com/products/v4"

        self.token = None
        self.token_expiry = 0
        self._init_cache_db()

    def _init_cache_db(self):
        """Initialize the SQLite database for caching API responses."""
        with sqlite3.connect(self.CACHE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def _get_from_cache(self, key: str):
        """Retrieve a response from the local cache."""
        try:
            with sqlite3.connect(self.CACHE_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT response_json FROM api_cache WHERE cache_key = ?", (key,))
                result = cursor.fetchone()
                if result:
                    return json.loads(result[0])
        except Exception as e:
            print(f"Cache lookup failed for {key}: {e}")
        return None

    def _save_to_cache(self, key: str, response_dict: dict):
        """Save an API response to the local SQLite cache."""
        try:
            with sqlite3.connect(self.CACHE_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO api_cache (cache_key, response_json, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (key, json.dumps(response_dict))
                )
                conn.commit()
        except Exception as e:
            print(f"Failed to save to cache for {key}: {e}")

    def get_token(self) -> str:
        """Fetch or return cached OAuth2 access token via Client Credentials flow."""
        if not self.client_id or not self.client_secret:
            raise ValueError("DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET must be set.")

        if self.token and time.time() < self.token_expiry - 60:
            return self.token

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        response = requests.post(self.OAUTH_URL, data=data)
        response.raise_for_status()

        token_data = response.json()
        self.token = token_data.get("access_token")
        expires_in = int(token_data.get("expires_in", 3600))
        self.token_expiry = time.time() + expires_in

        return self.token

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": self.locale,
            "X-DIGIKEY-Locale-Currency": self.currency,
            "X-DIGIKEY-Locale-Language": self.language,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def search_keyword(self, keyword: str, limit: int = 10, offset: int = 0) -> dict:
        """
        Search for a part using a keyword, which supports fuzzy and exact matching.
        Hits: POST /search/keyword
        """
        cache_key = f"search:{keyword}:{limit}:{offset}"
        cached_response = self._get_from_cache(cache_key)
        if cached_response:
            return cached_response

        url = f"{self.API_BASE}/search/keyword"

        payload = {
            "Keywords": keyword,
            "Limit": min(limit, 50), # Max allowed is 50
            "Offset": offset,
            "FilterOptionsRequest": {
                "SearchOptions": [] # E.g., ["InStock", "HasDatasheet"] if we wanted to filter
            }
        }

        response = requests.post(url, headers=self._get_headers(), json=payload)
        
        if not response.ok:
            raise Exception(f"DigiKey Search API Error ({response.status_code}): {response.text}")

        result = response.json()
        self._save_to_cache(cache_key, result)
        return result

    def get_product_details(self, product_number: str) -> dict:
        """
        Retrieve expanded production information for a single product. 
        Note this works best with a DigiKey product number.
        Hits: GET /search/{productNumber}/productdetails
        """
        cache_key = f"details:{product_number}"
        cached_response = self._get_from_cache(cache_key)
        if cached_response:
            return cached_response

        # Endpoint requires path param to be URL-encoded if it contains spaces or slashes
        import urllib.parse
        encoded_product = urllib.parse.quote(product_number, safe='')
        url = f"{self.API_BASE}/search/{encoded_product}/productdetails"

        response = requests.get(url, headers=self._get_headers())
        
        if not response.ok:
             raise Exception(f"DigiKey Product Details API Error ({response.status_code}): {response.text}")

        result = response.json()
        self._save_to_cache(cache_key, result)
        return result
