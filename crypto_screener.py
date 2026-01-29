#!/usr/bin/env python3
"""
HK Screener v4
- Fetches Binance Futures USDT-M perpetual contracts
- Cross-references with CoinGecko AND CoinMarketCap (OR logic)
- Calculates bounce from Q4 2025 lows
- 8 Market Cap Categories with new coin tracking
- Persistent notes per coin
"""

import requests
import time
import os
import json
import subprocess
import platform
import re
from datetime import datetime, timezone

# CoinMarketCap API Key
CMC_API_KEY = os.environ.get("CMC_API_KEY", "68c6b851ef0348bca072f6dff1f89c4d")

# File paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "coins_history.json")
NOTES_FILE = os.path.join(BASE_DIR, "coin_notes.json")

# Market Cap Categories (non-overlapping boundaries)
# Using > lower and <= upper for non-overlapping ranges
MCAP_CATEGORIES = [
    {"id": "micro", "name": "Micro Cap", "label": "$25M-$50M", "min": 25_000_000, "max": 50_000_000},
    {"id": "small", "name": "Small Cap", "label": "$50M-$100M", "min": 50_000_000, "max": 100_000_000},
    {"id": "low", "name": "Low Cap", "label": "$100M-$250M", "min": 100_000_000, "max": 250_000_000},
    {"id": "midlow", "name": "Mid-Low Cap", "label": "$250M-$500M", "min": 250_000_000, "max": 500_000_000},
    {"id": "mid", "name": "Mid Cap", "label": "$500M-$750M", "min": 500_000_000, "max": 750_000_000},
    {"id": "midhigh", "name": "Mid-High Cap", "label": "$750M-$1B", "min": 750_000_000, "max": 1_000_000_000},
    {"id": "high", "name": "High Cap", "label": "$1B-$1.5B", "min": 1_000_000_000, "max": 1_500_000_000},
    {"id": "mega", "name": "Mega Cap", "label": "$1.5B+", "min": 1_500_000_000, "max": float('inf')},
]


def load_coin_history():
    """Load previous coin lists from history file (per category)"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                # Support both old format (single list) and new format (per category)
                if "categories" in data:
                    return {cat: set(coins) for cat, coins in data["categories"].items()}
                elif "coins" in data:
                    # Old format - treat as "all" category
                    return {"all": set(data["coins"])}
    except Exception as e:
        print(f"   Warning: Could not load history file: {e}")
    return {}


def save_coin_history(category_coins):
    """Save current coin lists to history file (per category)"""
    try:
        data = {
            "last_updated": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "categories": {cat: sorted(list(coins)) for cat, coins in category_coins.items()}
        }
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"   Warning: Could not save history file: {e}")


def load_coin_notes():
    """Load coin notes from JSON file"""
    try:
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"   Warning: Could not load notes file: {e}")
    return {}


def save_coin_notes(notes):
    """Save coin notes to JSON file"""
    try:
        with open(NOTES_FILE, 'w') as f:
            json.dump(notes, f, indent=2)
    except Exception as e:
        print(f"   Warning: Could not save notes file: {e}")


def fetch_binance_futures_data():
    """Fetch 24hr ticker data from Binance Futures"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_q4_low(symbol, retries=3):
    """Fetch the lowest price between Nov 1 - Dec 31, 2025 from Binance Futures"""
    url = "https://fapi.binance.com/fapi/v1/klines"

    start_time = int(datetime(2025, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_time = int(datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

    params = {
        "symbol": f"{symbol}USDT",
        "interval": "1d",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 62
    }

    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 429:
                time.sleep(2)
                continue
            if response.status_code != 200:
                return None, None

            data = response.json()
            if not data:
                return None, None

            lows = [float(candle[3]) for candle in data]
            low_price = min(lows)
            low_idx = lows.index(low_price)
            low_timestamp = data[low_idx][0] / 1000
            low_date = datetime.fromtimestamp(low_timestamp, tz=timezone.utc).strftime('%Y-%m-%d')

            return low_price, low_date
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)

    return None, None


def fetch_coingecko_data():
    """Fetch market data from CoinGecko (FDV, MCap, 24h & 30d change)"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    all_coins = []

    print("   Fetching from CoinGecko...")
    for page in range(1, 6):  # Top 500 coins
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100,
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "24h,30d"
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 429:
                print(f"   CoinGecko rate limited, waiting 60s...")
                time.sleep(60)
                response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            all_coins.extend(data)
            time.sleep(1.5)
        except Exception as e:
            print(f"   CoinGecko error on page {page}: {e}")
            break

    # Convert to symbol-keyed dict (keep highest market cap on collision)
    cg_by_symbol = {}
    for coin in all_coins:
        symbol = coin.get("symbol", "").upper()
        market_cap = coin.get("market_cap") or 0

        if symbol in cg_by_symbol:
            existing_mcap = cg_by_symbol[symbol].get("market_cap") or 0
            if market_cap <= existing_mcap:
                continue

        cg_by_symbol[symbol] = {
            "fdv": coin.get("fully_diluted_valuation"),
            "market_cap": coin.get("market_cap"),
            "price_change_24h": coin.get("price_change_percentage_24h"),
            "price_change_30d": coin.get("price_change_percentage_30d_in_currency"),
            "name": coin.get("name"),
        }

    print(f"   CoinGecko: {len(cg_by_symbol)} coins")
    return cg_by_symbol


def fetch_coinmarketcap_data():
    """Fetch market data from CoinMarketCap (FDV, MCap, 24h & 30d change)"""
    if not CMC_API_KEY:
        print("   CoinMarketCap: Skipped (no API key)")
        return {}

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }
    params = {
        "start": 1,
        "limit": 500,
        "convert": "USD",
        "sort": "market_cap",
        "sort_dir": "desc"
    }

    print("   Fetching from CoinMarketCap...")
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 401:
            print("   CoinMarketCap: Invalid API key")
            return {}
        if response.status_code == 429:
            print("   CoinMarketCap: Rate limited")
            return {}

        response.raise_for_status()
        data = response.json()

        if data.get("status", {}).get("error_code"):
            print(f"   CoinMarketCap error: {data['status'].get('error_message')}")
            return {}

        coins = data.get("data", [])

        cmc_by_symbol = {}
        for coin in coins:
            symbol = coin.get("symbol", "").upper()
            quote = coin.get("quote", {}).get("USD", {})
            market_cap = quote.get("market_cap") or 0

            if symbol in cmc_by_symbol:
                existing_mcap = cmc_by_symbol[symbol].get("market_cap") or 0
                if market_cap <= existing_mcap:
                    continue

            cmc_by_symbol[symbol] = {
                "fdv": quote.get("fully_diluted_market_cap"),
                "market_cap": quote.get("market_cap"),
                "price_change_24h": quote.get("percent_change_24h"),
                "price_change_30d": quote.get("percent_change_30d"),
                "name": coin.get("name"),
            }

        print(f"   CoinMarketCap: {len(cmc_by_symbol)} coins")
        return cmc_by_symbol

    except Exception as e:
        print(f"   CoinMarketCap error: {e}")
        return {}


def merge_market_data(cg_data, cmc_data):
    """Merge CoinGecko and CoinMarketCap data with OR logic."""
    merged = {}

    for symbol, data in cg_data.items():
        merged[symbol] = data.copy()

    for symbol, cmc_info in cmc_data.items():
        if symbol not in merged:
            merged[symbol] = cmc_info.copy()
        else:
            if merged[symbol].get("fdv") is None and cmc_info.get("fdv") is not None:
                merged[symbol]["fdv"] = cmc_info["fdv"]
            if merged[symbol].get("market_cap") is None and cmc_info.get("market_cap") is not None:
                merged[symbol]["market_cap"] = cmc_info["market_cap"]
            if merged[symbol].get("price_change_24h") is None and cmc_info.get("price_change_24h") is not None:
                merged[symbol]["price_change_24h"] = cmc_info["price_change_24h"]
            if merged[symbol].get("price_change_30d") is None and cmc_info.get("price_change_30d") is not None:
                merged[symbol]["price_change_30d"] = cmc_info["price_change_30d"]

    print(f"   Merged: {len(merged)} unique coins")
    return merged


def categorize_coin(market_cap):
    """Determine which category a coin belongs to based on market cap."""
    for cat in MCAP_CATEGORIES:
        if cat["min"] < market_cap <= cat["max"]:
            return cat["id"]
    return None


def main():
    print("=" * 100)
    print("HK SCREENER v4 - Real-Time Data")
    print("Data Sources: Binance Futures + CoinGecko + CoinMarketCap")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 100)

    # Load previous coin history and notes
    print("\n[1/7] Loading coin history and notes...")
    previous_coins = load_coin_history()
    coin_notes = load_coin_notes()
    print(f"   Previous history: {sum(len(v) for v in previous_coins.values())} coins across {len(previous_coins)} categories")
    print(f"   Loaded {len(coin_notes)} coin notes")

    # Fetch Binance Futures data
    print("\n[2/7] Fetching Binance Futures USDT-M perpetual data...")
    binance_data = fetch_binance_futures_data()

    usdt_perps = {}
    for ticker in binance_data:
        symbol = ticker.get("symbol", "")
        if symbol.endswith("USDT") and not symbol.endswith("_PERP"):
            volume_usd = float(ticker.get("quoteVolume", 0))
            base_symbol = symbol.replace("USDT", "")

            lookup_symbol = base_symbol
            if base_symbol.startswith("1000"):
                lookup_symbol = base_symbol[4:]

            usdt_perps[base_symbol] = {
                "symbol": base_symbol,
                "lookup_symbol": lookup_symbol,
                "price": float(ticker.get("lastPrice", 0)),
                "volume_24h_usd": volume_usd,
                "change_24h_binance": float(ticker.get("priceChangePercent", 0)),
            }

    print(f"   Found {len(usdt_perps)} USDT-M perpetual pairs")

    # Fetch market data from both sources
    print("\n[3/7] Fetching market data (FDV, MCap, 24h & 30d change)...")
    cg_data = fetch_coingecko_data()
    cmc_data = fetch_coinmarketcap_data()

    # Merge with OR logic
    print("\n[4/7] Merging data...")
    merged_data = merge_market_data(cg_data, cmc_data)

    # Categorize coins into 8 market cap categories
    print("\n[5/7] Categorizing coins into 8 market cap tiers...")
    category_coins = {cat["id"]: [] for cat in MCAP_CATEGORIES}

    for symbol, binance_info in usdt_perps.items():
        lookup_symbol = binance_info.get("lookup_symbol", symbol)
        market_info = merged_data.get(lookup_symbol)

        if market_info:
            fdv = market_info.get("fdv") or 0
            market_cap = market_info.get("market_cap") or 0

            change_24h = binance_info.get("change_24h_binance")
            if change_24h == 0 and market_info.get("price_change_24h"):
                change_24h = market_info.get("price_change_24h")

            coin_data = {
                "symbol": symbol,
                "price": binance_info["price"],
                "binance_vol_24h_m": binance_info["volume_24h_usd"] / 1_000_000,
                "market_cap_m": market_cap / 1_000_000 if market_cap else 0,
                "fdv_m": fdv / 1_000_000 if fdv else 0,
                "change_24h": change_24h or 0,
                "change_30d": market_info.get("price_change_30d") or 0,
            }

            # Categorize by market cap
            cat_id = categorize_coin(market_cap)
            if cat_id:
                category_coins[cat_id].append(coin_data)

    # Print category counts
    for cat in MCAP_CATEGORIES:
        count = len(category_coins[cat["id"]])
        print(f"   {cat['name']} ({cat['label']}): {count} coins")

    # Fetch Q4 2025 lows for all coins
    print("\n[6/7] Fetching Q4 2025 lows (this may take a few minutes)...")

    all_coins_to_process = []
    for cat_id, coins in category_coins.items():
        for coin in coins:
            coin["_category"] = cat_id
            all_coins_to_process.append(coin)

    total = len(all_coins_to_process)
    print(f"   Processing {total} coins across all categories...")

    for i, coin in enumerate(all_coins_to_process):
        symbol = coin["symbol"]
        current_price = coin["price"]

        if (i + 1) % 50 == 0 or i == 0:
            print(f"   Processing {i + 1}/{total}...")

        low_price, low_date = fetch_q4_low(symbol)

        if low_price and low_price > 0:
            bounce_pct = ((current_price - low_price) / low_price) * 100
            coin["q4_low"] = low_price
            coin["q4_low_date"] = low_date
            coin["bounce_from_low"] = bounce_pct
        else:
            coin["q4_low"] = None
            coin["q4_low_date"] = None
            coin["bounce_from_low"] = None

        if (i + 1) % 10 == 0:
            time.sleep(0.3)

    # Rebuild category_coins with processed data and detect new coins
    print("\n[7/7] Detecting new coins and sorting...")

    current_category_coins = {cat["id"]: set() for cat in MCAP_CATEGORIES}
    final_category_data = {cat["id"]: [] for cat in MCAP_CATEGORIES}
    new_coins_by_category = {cat["id"]: set() for cat in MCAP_CATEGORIES}

    for coin in all_coins_to_process:
        cat_id = coin["_category"]
        symbol = coin["symbol"]
        del coin["_category"]

        current_category_coins[cat_id].add(symbol)

        # Check if coin is new to this category
        prev_cat_coins = previous_coins.get(cat_id, set())
        is_new = symbol not in prev_cat_coins
        coin["is_new"] = is_new

        if is_new:
            new_coins_by_category[cat_id].add(symbol)

        final_category_data[cat_id].append(coin)

    # Sort each category by 30-day change descending
    for cat_id in final_category_data:
        final_category_data[cat_id].sort(key=lambda x: x["change_30d"], reverse=True)

    # Save updated history
    save_coin_history(current_category_coins)

    # Print summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    total_coins = sum(len(coins) for coins in final_category_data.values())
    total_new = sum(len(coins) for coins in new_coins_by_category.values())
    print(f"Total coins: {total_coins}")
    print(f"New coins this run: {total_new}")

    for cat in MCAP_CATEGORIES:
        cat_id = cat["id"]
        count = len(final_category_data[cat_id])
        new_count = len(new_coins_by_category[cat_id])
        new_str = f" ({new_count} NEW)" if new_count > 0 else ""
        print(f"   {cat['name']}: {count} coins{new_str}")
        if new_coins_by_category[cat_id]:
            print(f"      New: {', '.join(sorted(new_coins_by_category[cat_id]))}")

    # Generate JavaScript data
    report_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    def format_coin_js(row, notes):
        bounce = row.get('bounce_from_low')
        bounce_val = f"{bounce:.2f}" if bounce is not None else "null"
        q4_low = row.get('q4_low')
        q4_low_val = f"{q4_low}" if q4_low is not None else "null"
        low_date = row.get('q4_low_date')
        low_date_val = f'"{low_date}"' if low_date else "null"
        is_new = "true" if row.get('is_new') else "false"
        note = notes.get(row["symbol"], "").replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        symbol = row["symbol"].replace('\\', '\\\\').replace('"', '\\"')
        return f'    {{ symbol: "{symbol}", price: {row["price"]}, mcap: {row["market_cap_m"]:.0f}, fdv: {row["fdv_m"]:.0f}, volume: {row["binance_vol_24h_m"]:.1f}, d1: {row["change_24h"]:.2f}, d30: {row["change_30d"]:.2f}, q4Low: {q4_low_val}, lowDate: {low_date_val}, bounce: {bounce_val}, isNew: {is_new}, notes: "{note}" }}'

    # Build JavaScript code block
    js_lines = []
    js_lines.append(f'const reportGeneratedAt = "{report_time}";')

    # Categories metadata
    js_lines.append("const mcapCategories = [")
    for cat in MCAP_CATEGORIES:
        new_list = sorted(list(new_coins_by_category[cat["id"]]))
        js_lines.append(f'    {{ id: "{cat["id"]}", name: "{cat["name"]}", label: "{cat["label"]}", newCoins: {json.dumps(new_list)} }},')
    js_lines.append("];")

    # Data for each category
    for cat in MCAP_CATEGORIES:
        cat_id = cat["id"]
        var_name = f"{cat_id}Data"
        js_lines.append(f"const {var_name} = [")
        for row in final_category_data[cat_id]:
            js_lines.append(format_coin_js(row, coin_notes) + ",")
        js_lines.append("];")

    # Coin notes object
    js_lines.append(f"const coinNotes = {json.dumps(coin_notes)};")
    js_lines.append("")

    js_code = "\n".join(js_lines)

    # Update HTML file
    html_file = os.path.join(BASE_DIR, "crypto_screener_v2.html")
    if os.path.exists(html_file):
        print(f"\nUpdating HTML file...")
        try:
            # Read the new HTML template
            with open(html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Find the script tag and replace just the data section
            start_marker = 'const reportGeneratedAt = "'
            end_marker = 'const coinNotes = {};'

            start_idx = html_content.find(start_marker)
            end_idx = html_content.find(end_marker)

            if start_idx != -1 and end_idx != -1:
                end_idx += len(end_marker)
                html_content = html_content[:start_idx] + js_code.strip() + html_content[end_idx:]

            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)

            print(f"   HTML file updated: {html_file}")

            # Auto-open HTML file
            print(f"   Opening HTML in browser...")
            if platform.system() == 'Darwin':
                subprocess.run(['open', html_file], check=True)
            elif platform.system() == 'Windows':
                os.startfile(html_file)
            else:
                subprocess.run(['xdg-open', html_file], check=True)

        except Exception as e:
            print(f"   Warning: Could not update HTML file: {e}")
    else:
        print(f"\n   Warning: HTML file not found at {html_file}")

    return final_category_data


if __name__ == "__main__":
    main()
