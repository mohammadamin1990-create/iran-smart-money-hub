"""
TSETMC Market Watch & Client Type Data Ingestion Client.
Parses live snapshots, real vs. legal client flows, order books, and historical data.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
import requests
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Standard Sector Names Mapping for Tehran Stock Exchange (TSETMC Industry Codes)
SECTOR_MAP: Dict[str, str] = {
    "10": "زراعت و خدمات وابسته",
    "13": "استخراج زغال سنگ",
    "14": "استخراج نفت و گاز",
    "23": "استخراج کانه‌های فلزی",
    "25": "فرآورده‌های نفتی و کک",
    "27": "فلزات اساسی",
    "28": "ساخت محصولات فلزی",
    "29": "ماشین‌آلات و تجهیزات",
    "31": "دستگاه‌های برقی",
    "34": "خودرو و ساخت قطعات",
    "38": "قند و شکر",
    "40": "دباغی و چرم",
    "42": "لاستیک و پلاستیک",
    "43": "مواد و محصولات دارویی",
    "44": "محصولات شیمیایی",
    "47": "خرده‌فروشی",
    "49": "کاشی و سرامیک",
    "50": "سیمان، آهک و گچ",
    "53": "سیمان، آهک و گچ",
    "54": "سایر محصولات کانی غیرفلزی",
    "56": "سرمایه‌گذاری‌ها",
    "57": "بانک‌ها و موسسات اعتباری",
    "58": "سایر واسطه‌گری‌های مالی",
    "60": "حمل و نقل، انبارداری و ارتباطات",
    "64": "مخابرات",
    "68": "صندوق‌های سرمایه‌گذاری قابل معامله (ETF)",
    "70": "فعالیت‌های کمکی به نهادهای مالی واسط",
    "72": "رایانه و فعالیت‌های وابسته",
    "73": "اطلاعات و ارتباطات",
    "74": "خدمات فنی و مهندسی",
}


class TSETMCClient:
    """
    Client for fetching real-time market snapshots, order books, and real/legal trade statistics from TSETMC.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "fa,en-US;q=0.9,en;q=0.8",
    }

    # Public TSETMC data URLs
    MARKET_WATCH_URL = "http://old.tsetmc.com/tsev2/data/MarketWatchPlus.aspx?h=0&r=0"
    CLIENT_TYPE_URL = "http://old.tsetmc.com/tsev2/data/ClientTypeAll.aspx"
    CDN_MARKET_MAP_URL = "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketMap?market=0&size=1370&sector=0&typeSelected=1"

    def __init__(self, timeout: int = 8, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.trust_env = False  # Direct connection without external proxy interference
        self.session.proxies = {"http": None, "https": None}
        self.session.headers.update(self.HEADERS)

    def fetch_market_watch(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Fetches the complete market watch snapshot.
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (instruments_df, order_book_df)
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(self.MARKET_WATCH_URL, timeout=self.timeout)
                response.encoding = "utf-8"
                if response.status_code == 200 and "@" in response.text:
                    return self._parse_market_watch(response.text)
                else:
                    logger.warning(f"MarketWatch returned status {response.status_code}, attempt {attempt}/{self.max_retries}")
            except Exception as e:
                logger.warning(f"Failed to fetch MarketWatch (attempt {attempt}/{self.max_retries}): {e}")
            time.sleep(1)

        logger.error("All attempts to fetch MarketWatch failed.")
        return pd.DataFrame(), pd.DataFrame()

    def _parse_market_watch(self, raw_text: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Parses raw text from MarketWatchPlus.aspx.
        """
        parts = raw_text.split("@")
        if len(parts) < 3:
            return pd.DataFrame(), pd.DataFrame()

        # Part 0: Market instrument statistics
        inst_records = []
        raw_insts = parts[2].split(";") if len(parts) > 2 else parts[0].split(";")

        for line in raw_insts:
            fields = line.strip().split(",")
            if len(fields) >= 23:
                try:
                    inscode = str(fields[0])
                    iid = str(fields[1])
                    symbol = str(fields[2])  # e.g. فولاد
                    name = str(fields[3])    # e.g. فولاد مبارکه اصفهان
                    time_last = str(fields[4])
                    first_price = float(fields[5]) if fields[5] else 0.0
                    close_price = float(fields[6]) if fields[6] else 0.0  # قیمت پایانی
                    last_price = float(fields[7]) if fields[7] else 0.0   # آخرین معامله
                    trades_count = int(fields[8]) if fields[8] else 0
                    volume = float(fields[9]) if fields[9] else 0.0
                    value = float(fields[10]) if fields[10] else 0.0
                    low_price = float(fields[11]) if fields[11] else 0.0
                    high_price = float(fields[12]) if fields[12] else 0.0
                    yesterday_price = float(fields[13]) if fields[13] else 0.0
                    eps = float(fields[14]) if fields[14] else 0.0
                    base_volume = float(fields[15]) if fields[15] else 0.0
                    market_flow = str(fields[17]) if len(fields) > 17 else ""
                    sector_code = str(fields[18]) if len(fields) > 18 else ""
                    max_allowed_price = float(fields[19]) if len(fields) > 19 and fields[19] else 0.0
                    min_allowed_price = float(fields[20]) if len(fields) > 20 and fields[20] else 0.0
                    total_shares = float(fields[21]) if len(fields) > 21 and fields[21] else 0.0

                    sector_name = SECTOR_MAP.get(sector_code, f"گروه {sector_code}" if sector_code else "نامشخص")

                    # Price change percentages
                    pct_change_last = ((last_price - yesterday_price) / yesterday_price * 100.0) if yesterday_price > 0 else 0.0
                    pct_change_close = ((close_price - yesterday_price) / yesterday_price * 100.0) if yesterday_price > 0 else 0.0

                    inst_records.append({
                        "inscode": inscode,
                        "iid": iid,
                        "symbol": symbol,
                        "name": name,
                        "time_last": time_last,
                        "first_price": first_price,
                        "close_price": close_price,
                        "last_price": last_price,
                        "yesterday_price": yesterday_price,
                        "pct_change_last": round(pct_change_last, 2),
                        "pct_change_close": round(pct_change_close, 2),
                        "trades_count": trades_count,
                        "volume": volume,
                        "value": value,
                        "low_price": low_price,
                        "high_price": high_price,
                        "eps": eps,
                        "base_volume": base_volume,
                        "market_flow": market_flow,
                        "sector_code": sector_code,
                        "sector_name": sector_name,
                        "max_allowed_price": max_allowed_price,
                        "min_allowed_price": min_allowed_price,
                        "total_shares": total_shares,
                    })
                except Exception as ex:
                    logger.debug(f"Error parsing ticker line: {ex}")
                    continue

        instruments_df = pd.DataFrame(inst_records)

        # Part 1 / 3: Order book depth
        order_records = []
        raw_orders = parts[3].split(";") if len(parts) > 3 else []
        for line in raw_orders:
            fields = line.strip().split(",")
            if len(fields) >= 8:
                try:
                    order_records.append({
                        "inscode": str(fields[0]),
                        "rank": int(fields[1]) if fields[1] else 1,
                        "buy_count": int(fields[2]) if fields[2] else 0,
                        "sell_count": int(fields[3]) if fields[3] else 0,
                        "buy_vol": float(fields[4]) if fields[4] else 0.0,
                        "sell_vol": float(fields[5]) if fields[5] else 0.0,
                        "buy_price": float(fields[6]) if fields[6] else 0.0,
                        "sell_price": float(fields[7]) if fields[7] else 0.0,
                    })
                except Exception:
                    continue

        order_book_df = pd.DataFrame(order_records)
        return instruments_df, order_book_df

    def fetch_client_type(self) -> pd.DataFrame:
        """
        Fetches Real vs Legal (حقیقی و حقوقی) trade counts and volumes for all tickers.
        Returns:
            pd.DataFrame: Client type data indexed by inscode.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(self.CLIENT_TYPE_URL, timeout=self.timeout)
                response.encoding = "utf-8"
                if response.status_code == 200:
                    records = []
                    lines = response.text.strip().split(";")
                    for line in lines:
                        fields = line.strip().split(",")
                        if len(fields) >= 9:
                            try:
                                inscode = str(fields[0])
                                buy_count_real = int(fields[1]) if fields[1] else 0
                                buy_count_legal = int(fields[2]) if fields[2] else 0
                                sell_count_real = int(fields[3]) if fields[3] else 0
                                sell_count_legal = int(fields[4]) if fields[4] else 0
                                buy_vol_real = float(fields[5]) if fields[5] else 0.0
                                buy_vol_legal = float(fields[6]) if fields[6] else 0.0
                                sell_vol_real = float(fields[7]) if fields[7] else 0.0
                                sell_vol_legal = float(fields[8]) if fields[8] else 0.0

                                records.append({
                                    "inscode": inscode,
                                    "buy_count_real": buy_count_real,
                                    "buy_count_legal": buy_count_legal,
                                    "sell_count_real": sell_count_real,
                                    "sell_count_legal": sell_count_legal,
                                    "buy_vol_real": buy_vol_real,
                                    "buy_vol_legal": buy_vol_legal,
                                    "sell_vol_real": sell_vol_real,
                                    "sell_vol_legal": sell_vol_legal,
                                })
                            except Exception:
                                continue

                    return pd.DataFrame(records)
                else:
                    logger.warning(f"ClientType returned status {response.status_code}, attempt {attempt}/{self.max_retries}")
            except Exception as e:
                logger.warning(f"Failed to fetch ClientType (attempt {attempt}/{self.max_retries}): {e}")
            time.sleep(1)

        logger.error("All attempts to fetch ClientType failed.")
        return pd.DataFrame()

    def get_full_market_snapshot(self) -> pd.DataFrame:
        """
        Merges Market Watch data with Client Type (Real/Legal) data to produce a unified DataFrame.
        """
        instruments_df, _ = self.fetch_market_watch()
        if instruments_df.empty:
            logger.warning("Empty instruments data returned from MarketWatch.")
            return pd.DataFrame()

        client_df = self.fetch_client_type()
        if client_df.empty:
            logger.warning("Empty client type data returned. Proceeding with zeroed client fields.")
            for col in [
                "buy_count_real", "buy_count_legal", "sell_count_real", "sell_count_legal",
                "buy_vol_real", "buy_vol_legal", "sell_vol_real", "sell_vol_legal"
            ]:
                instruments_df[col] = 0
            return instruments_df

        merged = pd.merge(instruments_df, client_df, on="inscode", how="left")

        # Fill NAs for instruments without client type data
        for col in [
            "buy_count_real", "buy_count_legal", "sell_count_real", "sell_count_legal",
            "buy_vol_real", "buy_vol_legal", "sell_vol_real", "sell_vol_legal"
        ]:
            merged[col] = merged[col].fillna(0)

        return merged
