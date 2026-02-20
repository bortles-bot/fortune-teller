# Fortune Teller 🔮

Kalshi prediction market trading client.

## Setup

1. Install dependencies:
   ```bash
   pip install cryptography requests
   ```

2. Copy `config.template.json` to `config.json` and fill in your credentials:
   ```bash
   cp config.template.json config.json
   ```

3. Add your Kalshi API private key (get from https://kalshi.com/account/profile)

## Usage

```bash
# Account
python kalshi.py balance      # Check balance
python kalshi.py positions    # View positions
python kalshi.py orders       # View resting orders

# Markets
python kalshi.py events       # List events
python kalshi.py markets      # List markets
python kalshi.py markets <event_ticker>  # Markets for specific event
python kalshi.py market <ticker>         # Market details
python kalshi.py orderbook <ticker>      # Order book
```

## API

```python
from kalshi import KalshiClient

client = KalshiClient()

# Read operations
client.get_balance()
client.get_positions()
client.get_orders()
client.get_events()
client.get_markets(event_ticker=None)
client.get_market(ticker)
client.get_orderbook(ticker)

# Trading
client.place_order(
    ticker="KXMARKET-TICKER",
    side="yes",        # or "no"
    action="buy",      # or "sell"
    count=10,          # number of contracts
    type="limit",      # or "market"
    price=50           # cents (1-99), for limit orders
)
client.cancel_order(order_id)
```

## Arbitrage Monitor

```bash
python arb_monitor.py
```

Polls CoinGecko for BTC/ETH/DOGE prices and compares against Kalshi 15-minute markets to identify potential arbitrage opportunities.

**What it checks:**
- Current spot prices vs Kalshi strike prices
- Market bid/ask vs estimated fair value
- Reports opportunities with estimated edge

**Data sources:**
- Prices: CoinGecko API (free)
- Markets: Kalshi API (authenticated)

## Notes

- Prices are in cents (1-99)
- Balance/exposure values from API are in cents
- Demo environment: set `use_demo: true` in config
