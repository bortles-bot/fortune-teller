#!/usr/bin/env python3
"""
Crypto Arbitrage Monitor
Polls CoinGecko for prices, compares to Kalshi markets, reports findings.
"""

import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from kalshi import KalshiClient

COINGECKO_API = "https://api.coingecko.com/api/v3"

def get_crypto_prices():
    """Get current prices from CoinGecko"""
    try:
        resp = requests.get(
            f"{COINGECKO_API}/simple/price",
            params={
                "ids": "bitcoin,ethereum,dogecoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true"
            },
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "btc": data.get("bitcoin", {}).get("usd"),
            "eth": data.get("ethereum", {}).get("usd"),
            "doge": data.get("dogecoin", {}).get("usd"),
            "btc_24h": data.get("bitcoin", {}).get("usd_24h_change"),
            "eth_24h": data.get("ethereum", {}).get("usd_24h_change"),
            "doge_24h": data.get("dogecoin", {}).get("usd_24h_change"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_kalshi_15m_markets(client):
    """Get current 15-minute crypto markets"""
    markets = {}
    
    for series, coin in [("KXBTC15M", "btc"), ("KXETH15M", "eth")]:
        try:
            resp = client._request("GET", f"/trade-api/v2/markets?series_ticker={series}&limit=5&status=open")
            for m in resp.get("markets", []):
                if m.get("yes_bid", 0) > 0 or m.get("yes_ask", 0) < 100:
                    # Extract the strike price from rules or subtitle
                    rules = m.get("rules_primary", "")
                    subtitle = m.get("yes_sub_title", "")
                    
                    # Parse strike price
                    strike = None
                    if "Price to beat:" in subtitle:
                        try:
                            strike = float(subtitle.split("$")[1].replace(",", ""))
                        except:
                            pass
                    
                    markets[coin] = {
                        "ticker": m.get("ticker"),
                        "strike": strike,
                        "yes_bid": m.get("yes_bid", 0),
                        "yes_ask": m.get("yes_ask", 0),
                        "no_bid": m.get("no_bid", 0),
                        "no_ask": m.get("no_ask", 0),
                        "close_time": m.get("close_time"),
                        "volume": m.get("volume", 0),
                        "subtitle": subtitle,
                    }
                    break
        except Exception as e:
            markets[f"{coin}_error"] = str(e)
    
    return markets


def get_kalshi_daily_markets(client):
    """Get daily crypto range markets"""
    markets = {}
    
    for series, coin in [("KXDOGE", "doge"), ("KXBTC", "btc_daily")]:
        try:
            resp = client._request("GET", f"/trade-api/v2/markets?series_ticker={series}&limit=20&status=open")
            # Get markets with any volume or reasonable bid/ask
            active = [m for m in resp.get("markets", []) if m.get("volume", 0) > 0 or m.get("yes_bid", 0) > 0]
            if active:
                markets[coin] = [{
                    "ticker": m.get("ticker"),
                    "yes_bid": m.get("yes_bid", 0),
                    "yes_ask": m.get("yes_ask", 0),
                    "volume": m.get("volume", 0),
                    "subtitle": m.get("yes_sub_title", ""),
                } for m in active[:5]]
        except Exception as e:
            markets[f"{coin}_error"] = str(e)
    
    return markets


def calculate_fair_value(current_price, strike_price, time_to_expiry_minutes):
    """
    Simple fair value estimate for binary option.
    If current price > strike, YES should be >50%.
    The further above/below, the more extreme the probability.
    
    This is a naive model - real model would use volatility.
    """
    if strike_price is None or current_price is None:
        return None
    
    # Simple heuristic: % difference from strike maps to probability
    pct_diff = (current_price - strike_price) / strike_price * 100
    
    # Rough mapping: 1% above strike ≈ 60% chance, 2% ≈ 70%, etc.
    # This is very simplified - real model needs historical volatility
    if pct_diff > 0:
        # Price above strike - YES more likely
        fair_value = min(50 + pct_diff * 15, 95)  # Cap at 95
    else:
        # Price below strike - NO more likely
        fair_value = max(50 + pct_diff * 15, 5)  # Floor at 5
    
    return round(fair_value)


def analyze_arbitrage(prices, markets_15m):
    """Analyze for arbitrage opportunities"""
    opportunities = []
    
    for coin in ["btc", "eth"]:
        if coin not in markets_15m or coin not in prices or prices[coin] is None:
            continue
            
        market = markets_15m[coin]
        current_price = prices[coin]
        strike = market.get("strike")
        
        if strike is None:
            continue
        
        fair_value = calculate_fair_value(current_price, strike, 15)
        if fair_value is None:
            continue
        
        yes_ask = market.get("yes_ask", 100)
        yes_bid = market.get("yes_bid", 0)
        
        # Check for YES opportunity: fair value > ask price
        if fair_value > yes_ask + 5:  # 5 cent buffer
            opportunities.append({
                "type": "BUY_YES",
                "coin": coin.upper(),
                "ticker": market.get("ticker"),
                "current_price": current_price,
                "strike": strike,
                "fair_value": fair_value,
                "market_ask": yes_ask,
                "edge": fair_value - yes_ask,
                "reasoning": f"Price ${current_price:,.2f} vs strike ${strike:,.2f} suggests {fair_value}% YES, but market asks {yes_ask}¢"
            })
        
        # Check for NO opportunity: fair value < bid price (we can sell YES)
        if fair_value < yes_bid - 5:
            opportunities.append({
                "type": "SELL_YES",
                "coin": coin.upper(),
                "ticker": market.get("ticker"),
                "current_price": current_price,
                "strike": strike,
                "fair_value": fair_value,
                "market_bid": yes_bid,
                "edge": yes_bid - fair_value,
                "reasoning": f"Price ${current_price:,.2f} vs strike ${strike:,.2f} suggests {fair_value}% YES, but market bids {yes_bid}¢"
            })
    
    return opportunities


def format_report(prices, markets_15m, markets_daily, opportunities):
    """Format findings as a Discord message"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    lines = [f"🔮 **Crypto Arb Monitor** - {now}", ""]
    
    # Current prices
    lines.append("**Current Prices (CoinGecko):**")
    if prices.get("btc"):
        lines.append(f"• BTC: ${prices['btc']:,.2f} ({prices.get('btc_24h', 0):+.1f}% 24h)")
    if prices.get("eth"):
        lines.append(f"• ETH: ${prices['eth']:,.2f} ({prices.get('eth_24h', 0):+.1f}% 24h)")
    if prices.get("doge"):
        lines.append(f"• DOGE: ${prices['doge']:.4f} ({prices.get('doge_24h', 0):+.1f}% 24h)")
    lines.append("")
    
    # 15-minute markets
    lines.append("**15-Min Markets (Kalshi):**")
    for coin in ["btc", "eth"]:
        if coin in markets_15m:
            m = markets_15m[coin]
            strike = m.get('strike')
            if strike:
                current = prices.get(coin)
                diff = ((current - strike) / strike * 100) if current and strike else 0
                lines.append(f"• {coin.upper()}: Strike ${strike:,.2f} | Bid/Ask: {m['yes_bid']}/{m['yes_ask']}¢ | Vol: {m['volume']:,}")
                lines.append(f"  Current vs Strike: {diff:+.2f}%")
    lines.append("")
    
    # Arbitrage opportunities
    if opportunities:
        lines.append("🚨 **ARBITRAGE OPPORTUNITIES DETECTED:**")
        for opp in opportunities:
            lines.append(f"• **{opp['type']}** {opp['coin']}")
            lines.append(f"  {opp['reasoning']}")
            lines.append(f"  Estimated edge: {opp['edge']}¢")
        lines.append("")
    else:
        lines.append("✅ **No arbitrage opportunities detected.**")
        lines.append("Markets appear fairly priced relative to current spot prices.")
        lines.append("")
    
    return "\n".join(lines)


def main():
    """Main monitoring function"""
    # Get data
    prices = get_crypto_prices()
    if "error" in prices:
        print(f"Error fetching prices: {prices['error']}")
        return None
    
    client = KalshiClient()
    markets_15m = get_kalshi_15m_markets(client)
    markets_daily = get_kalshi_daily_markets(client)
    
    # Analyze
    opportunities = analyze_arbitrage(prices, markets_15m)
    
    # Format report
    report = format_report(prices, markets_15m, markets_daily, opportunities)
    
    return {
        "report": report,
        "prices": prices,
        "markets_15m": markets_15m,
        "opportunities": opportunities,
        "has_opportunities": len(opportunities) > 0
    }


if __name__ == "__main__":
    result = main()
    if result:
        print(result["report"])
        print("\n---")
        print(f"Opportunities found: {len(result['opportunities'])}")
