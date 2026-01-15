#!/usr/bin/env python3
"""
Crypto Market Screener v3
- Fetches Binance Futures USDT-M perpetual contracts
- Cross-references with CoinGecko AND CoinMarketCap (OR logic)
- Calculates bounce from Q4 2025 lows
- Filters by FDV > $100M
- Tracks new coins joining the dashboard
"""

import requests
import time
import os
import json
from datetime import datetime, timezone

# CoinMarketCap API Key
CMC_API_KEY = os.environ.get("CMC_API_KEY", "68c6b851ef0348bca072f6dff1f89c4d")

# History file to track coins across runs
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coins_history.json")

def load_coin_history():
    """Load previous coin list from history file"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get("coins", []))
    except Exception as e:
        print(f"   Warning: Could not load history file: {e}")
    return set()

def save_coin_history(coins):
    """Save current coin list to history file"""
    try:
        data = {
            "last_updated": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "coins": sorted(list(coins))
        }
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"   Warning: Could not save history file: {e}")

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

    # Convert to symbol-keyed dict
    cg_by_symbol = {}
    for coin in all_coins:
        symbol = coin.get("symbol", "").upper()
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

    # Start with all CoinGecko data
    for symbol, data in cg_data.items():
        merged[symbol] = data.copy()

    # Add CMC data for symbols not in CoinGecko OR where CoinGecko has missing data
    for symbol, cmc_info in cmc_data.items():
        if symbol not in merged:
            merged[symbol] = cmc_info.copy()
        else:
            # Fill in missing fields from CMC
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

def main():
    print("=" * 100)
    print("CRYPTO MARKET SCREENER v3 - Real-Time Data")
    print("Data Sources: Binance Futures + CoinGecko + CoinMarketCap")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 100)

    # Load previous coin history
    print("\n[1/6] Loading coin history...")
    previous_coins = load_coin_history()
    print(f"   Previous run had {len(previous_coins)} coins")

    # Step 2: Fetch Binance Futures data
    print("\n[2/6] Fetching Binance Futures USDT-M perpetual data...")
    binance_data = fetch_binance_futures_data()

    usdt_perps = {}
    for ticker in binance_data:
        symbol = ticker.get("symbol", "")
        if symbol.endswith("USDT") and not symbol.endswith("_PERP"):
            volume_usd = float(ticker.get("quoteVolume", 0))
            base_symbol = symbol.replace("USDT", "")

            # Handle 1000-prefixed symbols
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

    # Step 3: Fetch market data from both sources
    print("\n[3/6] Fetching market data (FDV, MCap, 24h & 30d change)...")
    cg_data = fetch_coingecko_data()
    cmc_data = fetch_coinmarketcap_data()

    # Merge with OR logic
    print("\n[4/6] Merging data...")
    merged_data = merge_market_data(cg_data, cmc_data)

    # Filter and merge with Binance data
    print("\n[5/6] Applying FDV filter (>$100M)...")
    filtered_coins = []

    for symbol, binance_info in usdt_perps.items():
        lookup_symbol = binance_info.get("lookup_symbol", symbol)
        market_info = merged_data.get(lookup_symbol)

        if market_info and market_info.get("fdv"):
            fdv = market_info["fdv"]
            market_cap = market_info.get("market_cap") or 0

            if fdv > 100_000_000:
                # Use Binance 24h change as primary, fallback to CG/CMC
                change_24h = binance_info.get("change_24h_binance")
                if change_24h == 0 and market_info.get("price_change_24h"):
                    change_24h = market_info.get("price_change_24h")

                filtered_coins.append({
                    "symbol": symbol,
                    "price": binance_info["price"],
                    "binance_vol_24h_m": binance_info["volume_24h_usd"] / 1_000_000,
                    "market_cap_m": market_cap / 1_000_000 if market_cap else 0,
                    "fdv_m": fdv / 1_000_000,
                    "change_24h": change_24h or 0,
                    "change_30d": market_info.get("price_change_30d") or 0,
                })

    print(f"   {len(filtered_coins)} coins match FDV criteria")

    # Step 6: Fetch Q4 2025 lows
    print("\n[6/6] Fetching Q4 2025 lows (this may take a minute)...")
    final_data = []
    total = len(filtered_coins)

    for i, coin in enumerate(filtered_coins):
        symbol = coin["symbol"]
        current_price = coin["price"]

        if (i + 1) % 20 == 0 or i == 0:
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

        final_data.append(coin)

        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    # Detect new coins
    current_coins = set(coin["symbol"] for coin in final_data)
    new_coins = current_coins - previous_coins if previous_coins else set()

    # Mark new coins
    for coin in final_data:
        coin["is_new"] = coin["symbol"] in new_coins

    # Save current coins to history
    save_coin_history(current_coins)

    # Sort by 30-day change descending
    final_data.sort(key=lambda x: x["change_30d"], reverse=True)

    print(f"   {len(final_data)} coins in final list")
    print(f"   {len(new_coins)} NEW coins detected")
    if new_coins:
        print(f"   New coins: {', '.join(sorted(new_coins))}")

    # Print results table
    print("\n" + "=" * 130)
    print("RESULTS: Binance Futures USDT-M | FDV >$100M")
    print("Sorted by 30-Day Change % (Descending)")
    print("=" * 130)

    print(f"{'Symbol':<12} {'Price':>12} {'MCap':>10} {'FDV':>10} {'24h Vol':>10} {'D1%':>8} {'30D%':>8} {'Q4 Low':>12} {'Bounce':>8} {'New':>5}")
    print(f"{'':12} {'(USD)':>12} {'(M)':>10} {'(M)':>10} {'(M)':>10} {'':>8} {'':>8} {'(USD)':>12} {'(%)':>8} {'':>5}")
    print("-" * 130)

    for row in final_data:
        price_str = f"${row['price']:,.4f}" if row['price'] < 1 else f"${row['price']:,.2f}"
        mcap_str = f"${row['market_cap_m']:,.0f}M" if row['market_cap_m'] > 0 else "N/A"
        fdv_str = f"${row['fdv_m']:,.0f}M"
        vol_str = f"${row['binance_vol_24h_m']:,.0f}M"
        d1_str = f"{row['change_24h']:+.1f}%"
        d30_str = f"{row['change_30d']:+.1f}%"
        new_str = "NEW" if row.get('is_new') else ""

        if row.get('q4_low'):
            low_str = f"${row['q4_low']:,.4f}" if row['q4_low'] < 1 else f"${row['q4_low']:,.2f}"
            bounce_str = f"+{row['bounce_from_low']:.0f}%"
        else:
            low_str = "N/A"
            bounce_str = "N/A"

        print(f"{row['symbol']:<12} {price_str:>12} {mcap_str:>10} {fdv_str:>10} {vol_str:>10} {d1_str:>8} {d30_str:>8} {low_str:>12} {bounce_str:>8} {new_str:>5}")

    print("-" * 130)
    print(f"Total: {len(final_data)} coins | New coins this run: {len(new_coins)}")
    print("=" * 130)

    # Export data for HTML
    print("\n// JavaScript data for HTML (copy this):")
    report_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f'const reportGeneratedAt = "{report_time}";')

    # Export new coins list
    new_coins_list = sorted(list(new_coins))
    print(f'const newCoins = new Set({json.dumps(new_coins_list)});')

    print("const cryptoData = [")
    for row in final_data:
        bounce = row.get('bounce_from_low')
        bounce_val = f"{bounce:.2f}" if bounce is not None else "null"
        q4_low = row.get('q4_low')
        q4_low_val = f"{q4_low}" if q4_low is not None else "null"
        low_date = row.get('q4_low_date')
        low_date_val = f'"{low_date}"' if low_date else "null"
        is_new = "true" if row.get('is_new') else "false"
        print(f'    {{ symbol: "{row["symbol"]}", price: {row["price"]}, mcap: {row["market_cap_m"]:.0f}, fdv: {row["fdv_m"]:.0f}, volume: {row["binance_vol_24h_m"]:.1f}, d1: {row["change_24h"]:.2f}, d30: {row["change_30d"]:.2f}, q4Low: {q4_low_val}, lowDate: {low_date_val}, bounce: {bounce_val}, isNew: {is_new} }},')
    print("];")

    return final_data

if __name__ == "__main__":
    main()
