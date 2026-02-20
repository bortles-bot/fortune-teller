#!/usr/bin/env python3
"""
Kalshi Trading API Client
Requires: pip install cryptography requests
"""

import json
import time
import base64
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

CONFIG_PATH = Path(__file__).parent / "config.json"

class KalshiClient:
    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path) as f:
            self.config = json.load(f)
        
        self.key_id = self.config["key_id"]
        self.base_url = self.config["demo_url"] if self.config.get("use_demo") else self.config["base_url"]
        
        with open(self.config["private_key_path"], "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
    
    def _sign(self, text: str) -> str:
        """Sign text with RSA-PSS"""
        message = text.encode('utf-8')
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256.digest_size
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def _headers(self, method: str, path: str) -> Dict[str, str]:
        """Generate signed headers for a request"""
        timestamp = str(int(time.time() * 1000))
        # Strip query params for signing
        path_clean = path.split('?')[0]
        msg = timestamp + method.upper() + path_clean
        signature = self._sign(msg)
        
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, path: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make an authenticated request"""
        url = self.base_url + path
        headers = self._headers(method, path)
        
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=data)
        elif method.upper() == "POST":
            resp = requests.post(url, headers=headers, json=data)
        elif method.upper() == "DELETE":
            resp = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        if not resp.ok:
            print(f"Error {resp.status_code}: {resp.text}", file=__import__('sys').stderr)
            resp.raise_for_status()
        return resp.json() if resp.text else {}
    
    # === Account ===
    
    def get_balance(self) -> Dict[str, Any]:
        """Get account balance"""
        return self._request("GET", "/trade-api/v2/portfolio/balance")
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        return self._request("GET", "/trade-api/v2/portfolio/positions")
    
    def get_orders(self, status: str = "resting") -> Dict[str, Any]:
        """Get orders (resting, canceled, executed)"""
        return self._request("GET", f"/trade-api/v2/portfolio/orders?status={status}")
    
    # === Markets ===
    
    def get_events(self, limit: int = 20, status: str = "open") -> Dict[str, Any]:
        """Get events (collections of markets)"""
        return self._request("GET", f"/trade-api/v2/events?limit={limit}&status={status}")
    
    def get_markets(self, event_ticker: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Get markets, optionally filtered by event"""
        path = f"/trade-api/v2/markets?limit={limit}"
        if event_ticker:
            path += f"&event_ticker={event_ticker}"
        return self._request("GET", path)
    
    def get_market(self, ticker: str) -> Dict[str, Any]:
        """Get a specific market by ticker"""
        return self._request("GET", f"/trade-api/v2/markets/{ticker}")
    
    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        """Get orderbook for a market"""
        return self._request("GET", f"/trade-api/v2/markets/{ticker}/orderbook")
    
    # === Trading ===
    
    def place_order(
        self,
        ticker: str,
        side: str,  # "yes" or "no"
        action: str,  # "buy" or "sell"
        count: int,
        type: str = "market",  # "market" or "limit"
        price: Optional[int] = None,  # in cents (1-99)
    ) -> Dict[str, Any]:
        """
        Place an order.
        - ticker: market ticker
        - side: "yes" or "no"
        - action: "buy" or "sell"
        - count: number of contracts
        - type: "market" or "limit"
        - price: limit price in cents (1-99), required for limit orders
        """
        order = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": type,
        }
        if type == "limit" and price is not None:
            order["yes_price"] = price if side == "yes" else None
            order["no_price"] = price if side == "no" else None
        
        return self._request("POST", "/trade-api/v2/portfolio/orders", order)
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order"""
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}")


def main():
    """CLI interface"""
    import sys
    
    client = KalshiClient()
    
    if len(sys.argv) < 2:
        print("Usage: kalshi.py <command> [args]")
        print("Commands: balance, positions, orders, events, markets, market <ticker>, orderbook <ticker>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "balance":
        print(json.dumps(client.get_balance(), indent=2))
    elif cmd == "positions":
        print(json.dumps(client.get_positions(), indent=2))
    elif cmd == "orders":
        print(json.dumps(client.get_orders(), indent=2))
    elif cmd == "events":
        print(json.dumps(client.get_events(), indent=2))
    elif cmd == "markets":
        event = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(client.get_markets(event), indent=2))
    elif cmd == "market":
        if len(sys.argv) < 3:
            print("Usage: kalshi.py market <ticker>")
            sys.exit(1)
        print(json.dumps(client.get_market(sys.argv[2]), indent=2))
    elif cmd == "orderbook":
        if len(sys.argv) < 3:
            print("Usage: kalshi.py orderbook <ticker>")
            sys.exit(1)
        print(json.dumps(client.get_orderbook(sys.argv[2]), indent=2))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
