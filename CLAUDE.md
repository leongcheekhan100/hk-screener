# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Crypto Market Screener v3 - A Python CLI tool that screens Binance Futures perpetual contracts, cross-references market data from CoinGecko and CoinMarketCap, and calculates bounce metrics from Q4 2025 lows.

## Commands

```bash
# Run the screener
python3 crypto_screener.py
```

## Architecture

- `crypto_screener.py` - Single-file CLI tool
  - Fetches Binance Futures USDT-M perpetual contracts
  - Cross-references with CoinGecko AND CoinMarketCap (OR logic for data merging)
  - Calculates bounce from Q4 2025 lows (Nov-Dec 2025)
  - Filters by FDV > $100M
  - Tracks new coins joining the dashboard across runs

- `coins_history.json` - Persists coin list between runs to detect new additions

## Data Flow

1. Load previous coin history from `coins_history.json`
2. Fetch Binance Futures 24hr ticker data (USDT-M perpetuals)
3. Fetch market data from CoinGecko (top 500 coins)
4. Fetch market data from CoinMarketCap (top 500 coins)
5. Merge data sources with OR logic (fill missing fields)
6. Filter coins with FDV > $100M
7. Fetch Q4 2025 daily klines to find lowest price
8. Calculate bounce percentage from low
9. Output table + JavaScript data for HTML visualization

## Output

- Console table sorted by 30-day change (descending)
- JavaScript variables (`reportGeneratedAt`, `newCoins`, `cryptoData`) for embedding in HTML

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CMC_API_KEY` | CoinMarketCap API key | Has built-in default |

## Requirements

- Python 3.6+
- `requests` library
- Internet connectivity to Binance, CoinGecko, and CoinMarketCap APIs
