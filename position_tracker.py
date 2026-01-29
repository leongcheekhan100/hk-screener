#!/usr/bin/env python3
"""
Binance Futures Position Tracker
- Fetches open positions with PnL
- Calculates funding fees paid/received per position
- Shows total long/short/net position sizes
- Trade history
"""

import os
import json
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
BASE_URL = 'https://fapi.binance.com'

def get_signature(params):
    """Generate HMAC SHA256 signature"""
    query_string = urlencode(params)
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

def api_request(endpoint, params=None, signed=True):
    """Make authenticated API request"""
    if params is None:
        params = {}

    headers = {'X-MBX-APIKEY': API_KEY}

    if signed:
        params['timestamp'] = int(time.time() * 1000)
        params['signature'] = get_signature(params)

    url = f"{BASE_URL}{endpoint}"
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code != 200:
        print(f"API Error: {response.status_code} - {response.text}")
        return None

    return response.json()

def get_account_balance():
    """Get futures account balance"""
    data = api_request('/fapi/v2/balance')
    if not data:
        return []

    # Filter to show only non-zero balances
    balances = []
    for b in data:
        balance = float(b.get('balance', 0))
        available = float(b.get('availableBalance', 0))
        if balance != 0:
            balances.append({
                'asset': b['asset'],
                'balance': balance,
                'availableBalance': available,
                'unrealizedProfit': float(b.get('crossUnPnl', 0))
            })
    return balances

def get_positions():
    """Get all open positions"""
    data = api_request('/fapi/v2/positionRisk')
    if not data:
        return []

    positions = []
    for p in data:
        position_amt = float(p.get('positionAmt', 0))
        if position_amt != 0:  # Only include positions with actual size
            entry_price = float(p.get('entryPrice', 0))
            mark_price = float(p.get('markPrice', 0))
            unrealized_pnl = float(p.get('unRealizedProfit', 0))

            positions.append({
                'symbol': p['symbol'],
                'positionAmt': position_amt,
                'entryPrice': entry_price,
                'markPrice': mark_price,
                'unrealizedProfit': unrealized_pnl,
                'liquidationPrice': float(p.get('liquidationPrice', 0)),
                'leverage': int(p.get('leverage', 1)),
                'marginType': p.get('marginType', 'cross'),
                'isolatedMargin': float(p.get('isolatedMargin', 0)),
                'notional': abs(float(p.get('notional', 0))),
                'side': 'LONG' if position_amt > 0 else 'SHORT',
                'updateTime': int(p.get('updateTime', 0))
            })

    return positions

def get_trade_history(symbol, limit=100):
    """Get trade history for a symbol"""
    params = {'symbol': symbol, 'limit': limit}
    data = api_request('/fapi/v1/userTrades', params)
    return data or []

def get_position_open_time(symbol, position_amt):
    """Find when the current position was opened by analyzing trade history"""
    trades = get_trade_history(symbol, 500)
    if not trades:
        return None

    # Sort by time descending
    trades.sort(key=lambda x: x['time'], reverse=True)

    # Walk backwards to find position open time
    cumulative_qty = 0
    target_qty = abs(position_amt)
    position_side = 'BUY' if position_amt > 0 else 'SELL'

    for trade in trades:
        qty = float(trade['qty'])
        side = trade['side']

        # If this trade is in the same direction as position
        if side == position_side:
            cumulative_qty += qty
            if cumulative_qty >= target_qty * 0.99:  # Allow small rounding
                return trade['time']

    # Fallback: return oldest trade time
    if trades:
        return trades[-1]['time']
    return None

def get_funding_fees(symbol=None, start_time=None, limit=1000):
    """Get funding fee history"""
    params = {
        'incomeType': 'FUNDING_FEE',
        'limit': limit
    }
    if symbol:
        params['symbol'] = symbol
    if start_time:
        params['startTime'] = start_time

    data = api_request('/fapi/v1/income', params)
    return data or []

def calculate_position_funding(symbol, start_time):
    """Calculate total funding fees for a position since it was opened"""
    funding_data = get_funding_fees(symbol, start_time)

    total_funding = 0
    funding_count = 0

    for f in funding_data:
        total_funding += float(f.get('income', 0))
        funding_count += 1

    return {
        'totalFunding': total_funding,
        'fundingCount': funding_count
    }

def get_all_orders(symbol=None, limit=50):
    """Get recent orders"""
    params = {'limit': limit}
    if symbol:
        params['symbol'] = symbol

    data = api_request('/fapi/v1/allOrders', params)
    if not data:
        return []

    # Filter to recent filled orders
    orders = []
    for o in data:
        if o.get('status') == 'FILLED':
            orders.append({
                'symbol': o['symbol'],
                'side': o['side'],
                'type': o['type'],
                'price': float(o.get('avgPrice', 0)),
                'qty': float(o.get('executedQty', 0)),
                'time': o.get('updateTime', 0),
                'realizedPnl': float(o.get('realizedPnl', 0)) if 'realizedPnl' in o else 0
            })

    return sorted(orders, key=lambda x: x['time'], reverse=True)[:20]

def get_income_history(limit=50):
    """Get recent income history (PnL, funding, commission)"""
    params = {'limit': limit}
    data = api_request('/fapi/v1/income', params)
    if not data:
        return []

    income = []
    for i in data:
        income.append({
            'symbol': i.get('symbol', ''),
            'incomeType': i['incomeType'],
            'income': float(i['income']),
            'asset': i['asset'],
            'time': i['time']
        })

    return sorted(income, key=lambda x: x['time'], reverse=True)

def main():
    print("=" * 80)
    print("BINANCE FUTURES POSITION TRACKER")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)

    # Get account balance
    print("\n[1/5] Fetching account balance...")
    balances = get_account_balance()
    total_balance = sum(b['balance'] for b in balances if b['asset'] == 'USDT')
    total_available = sum(b['availableBalance'] for b in balances if b['asset'] == 'USDT')
    total_unrealized = sum(b['unrealizedProfit'] for b in balances if b['asset'] == 'USDT')
    print(f"   USDT Balance: ${total_balance:,.2f}")
    print(f"   Available: ${total_available:,.2f}")
    print(f"   Unrealized PnL: ${total_unrealized:,.2f}")

    # Get positions
    print("\n[2/5] Fetching open positions...")
    positions = get_positions()
    print(f"   Found {len(positions)} open positions")

    # Calculate position metrics
    total_long_notional = 0
    total_short_notional = 0
    total_unrealized_pnl = 0

    for p in positions:
        if p['side'] == 'LONG':
            total_long_notional += p['notional']
        else:
            total_short_notional += p['notional']
        total_unrealized_pnl += p['unrealizedProfit']

    net_notional = total_long_notional - total_short_notional

    print(f"   Total Long: ${total_long_notional:,.2f}")
    print(f"   Total Short: ${total_short_notional:,.2f}")
    print(f"   Net Position: ${net_notional:,.2f} ({'LONG' if net_notional > 0 else 'SHORT' if net_notional < 0 else 'NEUTRAL'})")

    # Get funding fees for each position
    print("\n[3/5] Calculating funding fees per position...")
    for p in positions:
        symbol = p['symbol']
        position_amt = p['positionAmt']

        # Find position open time
        open_time = get_position_open_time(symbol, position_amt)
        p['openTime'] = open_time

        # Calculate funding since position opened
        funding_info = calculate_position_funding(symbol, open_time)
        p['totalFunding'] = funding_info['totalFunding']
        p['fundingCount'] = funding_info['fundingCount']

        # Calculate total PnL (unrealized + funding)
        p['totalPnl'] = p['unrealizedProfit'] + p['totalFunding']

        print(f"   {symbol}: Funding ${p['totalFunding']:+,.2f} ({p['fundingCount']} payments)")

        time.sleep(0.5)  # Rate limiting - increased for many positions

    # Get recent trades
    print("\n[4/5] Fetching recent trade history...")
    recent_trades = []
    for p in positions[:5]:  # Limit to first 5 positions
        trades = get_trade_history(p['symbol'], 10)
        recent_trades.extend(trades[:5])
        time.sleep(0.3)

    recent_trades = sorted(recent_trades, key=lambda x: x['time'], reverse=True)[:20]
    print(f"   Found {len(recent_trades)} recent trades")

    # Get income history
    print("\n[5/5] Fetching income history...")
    income_history = get_income_history(50)
    print(f"   Found {len(income_history)} income records")

    # Calculate totals
    total_funding_all = sum(p['totalFunding'] for p in positions)
    total_pnl_all = sum(p['totalPnl'] for p in positions)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Account Balance:     ${total_balance:,.2f}")
    print(f"Available Balance:   ${total_available:,.2f}")
    print(f"Open Positions:      {len(positions)}")
    print(f"Total Long Size:     ${total_long_notional:,.2f}")
    print(f"Total Short Size:    ${total_short_notional:,.2f}")
    print(f"Net Position Size:   ${abs(net_notional):,.2f} {'LONG' if net_notional > 0 else 'SHORT' if net_notional < 0 else 'NEUTRAL'}")
    print(f"Unrealized PnL:      ${total_unrealized_pnl:+,.2f}")
    print(f"Total Funding:       ${total_funding_all:+,.2f}")
    print(f"Total PnL:           ${total_pnl_all:+,.2f}")
    print("=" * 80)

    # Generate JSON data for dashboard
    report_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    dashboard_data = {
        'reportTime': report_time,
        'account': {
            'balance': total_balance,
            'availableBalance': total_available,
            'unrealizedProfit': total_unrealized,
        },
        'summary': {
            'totalLongNotional': total_long_notional,
            'totalShortNotional': total_short_notional,
            'netNotional': net_notional,
            'totalUnrealizedPnl': total_unrealized_pnl,
            'totalFunding': total_funding_all,
            'totalPnl': total_pnl_all,
            'positionCount': len(positions)
        },
        'positions': positions,
        'recentTrades': [{
            'symbol': t['symbol'],
            'side': t['side'],
            'price': float(t['price']),
            'qty': float(t['qty']),
            'quoteQty': float(t['quoteQty']),
            'realizedPnl': float(t.get('realizedPnl', 0)),
            'commission': float(t['commission']),
            'time': t['time']
        } for t in recent_trades],
        'incomeHistory': income_history
    }

    # Save to JSON file
    json_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'position_data.json')
    with open(json_file, 'w') as f:
        json.dump(dashboard_data, f, indent=2)
    print(f"\nData saved to: {json_file}")

    # Update HTML dashboard
    update_dashboard(dashboard_data)

    return dashboard_data

def update_dashboard(data):
    """Update the HTML dashboard with new data"""
    import subprocess
    import platform

    html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'position_dashboard.html')

    if os.path.exists(html_file):
        # Read HTML file
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Replace data
        js_data = f"const dashboardData = {json.dumps(data)};"

        start_marker = 'const dashboardData = '
        end_marker = '};'

        start_idx = html_content.find(start_marker)
        if start_idx != -1:
            end_idx = html_content.find(end_marker, start_idx) + len(end_marker)
            html_content = html_content[:start_idx] + js_data + html_content[end_idx:]

        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"Dashboard updated: {html_file}")

        # Open in browser
        print("Opening dashboard in browser...")
        if platform.system() == 'Darwin':
            subprocess.run(['open', html_file], check=True)
        elif platform.system() == 'Windows':
            os.startfile(html_file)
        else:
            subprocess.run(['xdg-open', html_file], check=True)

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("Error: Missing API keys. Please set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        exit(1)

    main()
