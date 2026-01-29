"""
PumpPortal WebSocket Client - Real-time new token detection for sniping.
Phase 70: Replacing /top-runners polling with instant new token events.

Connects to wss://pumpportal.fun/api/data and subscribes to new tokens.
This is the standard approach for 2026 Pump.fun sniping bots.
"""
import asyncio
import json
import logging
import time
import websockets
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Singleton instance
_client_instance = None

class PumpPortalClient:
    """
    Real-time WebSocket client for PumpPortal new token events.
    """
    
    WS_URL = "wss://pumpportal.fun/api/data"
    
    def __init__(self):
        self.ws = None
        self.running = False
        self._callbacks = []  # Registered callbacks for new tokens
        self._last_token_time = 0
        self._reconnect_delay = 1  # Exponential backoff
        self._token_buffer = []  # Buffer for rate limiting
        self._max_buffer = 50  # Don't spam callbacks
        
    def register_callback(self, callback: Callable):
        """Register a callback function for new token events."""
        self._callbacks.append(callback)
        logger.info(f"📡 Registered callback: {callback.__name__}")
        
    async def connect(self):
        """Connect to PumpPortal WebSocket and subscribe to new tokens."""
        while self.running:
            try:
                logger.info("🔌 Connecting to PumpPortal WebSocket...")
                
                async with websockets.connect(
                    self.WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 1  # Reset on successful connect
                    
                    # Subscribe to new token events
                    subscribe_msg = {"method": "subscribeNewToken"}
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("✅ Subscribed to subscribeNewToken")
                    
                    # Listen for events
                    async for message in ws:
                        try:
                            await self._handle_message(message)
                        except Exception as e:
                            logger.error(f"Message handling error: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"🔌 WebSocket closed: {e}, reconnecting in {self._reconnect_delay}s...")
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e}, reconnecting in {self._reconnect_delay}s...")
                
            # Exponential backoff for reconnects
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 30)  # Max 30s
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # New token event
            if 'mint' in data:
                # Rate limit: don't process more than 1 token per 100ms
                now = time.time()
                if now - self._last_token_time < 0.1:
                    return
                self._last_token_time = now
                
                token_data = self._parse_token(data)
                if token_data:
                    logger.info(f"🆕 NEW TOKEN: {token_data.get('symbol', 'Unknown')} | Mint: {token_data['mint'][:12]}...")
                    
                    # Fire all callbacks
                    for callback in self._callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(token_data)
                            else:
                                callback(token_data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            
        except json.JSONDecodeError:
            logger.debug(f"Non-JSON message: {message[:100]}")
    
    def _parse_token(self, data: dict) -> Optional[dict]:
        """Parse raw WebSocket data into standardized token format."""
        mint = data.get('mint')
        if not mint:
            return None
            
        # Standardize the token data to match what market_sniper expects
        return {
            'mint': mint,
            'symbol': data.get('symbol', data.get('name', 'NEW')),
            'name': data.get('name', ''),
            'usd_market_cap': data.get('marketCapSol', 0) * 200,  # Estimate USD from SOL
            'market_cap_sol': data.get('marketCapSol', 0),
            'score': 85,  # New tokens get high score (fresh = opportunity)
            'creator': data.get('traderPublicKey', ''),
            'signature': data.get('signature', ''),
            'initial_buy': data.get('initialBuy', 0),
            'bonding_curve': data.get('bondingCurveKey', ''),
            'is_new': True,  # Flag for sniper to know this is fresh
            'detected_at': time.time()
        }
    
    async def start(self):
        """Start the WebSocket client."""
        if self.running:
            logger.info("PumpPortal already running")
            return
            
        self.running = True
        logger.info("🚀 Starting PumpPortal WebSocket client...")
        await self.connect()
    
    def stop(self):
        """Stop the WebSocket client."""
        self.running = False
        if self.ws:
            asyncio.create_task(self.ws.close())
        logger.info("🛑 PumpPortal WebSocket stopped")
    
    async def get_recent_tokens(self, limit: int = 20) -> list:
        """Get recently detected tokens from buffer."""
        return self._token_buffer[-limit:]


def get_pump_portal_client() -> PumpPortalClient:
    """Get or create singleton client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = PumpPortalClient()
    return _client_instance


async def start_pump_portal():
    """Start the PumpPortal background task."""
    client = get_pump_portal_client()
    await client.start()


# Test script
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    async def test_callback(token_data):
        print(f"🎯 TEST CALLBACK: {token_data['symbol']} - ${token_data['usd_market_cap']:,.0f}")
    
    async def main():
        client = get_pump_portal_client()
        client.register_callback(test_callback)
        
        print("Starting PumpPortal WebSocket test...")
        print("Press Ctrl+C to stop")
        
        try:
            await client.start()
        except KeyboardInterrupt:
            client.stop()
    
    asyncio.run(main())
