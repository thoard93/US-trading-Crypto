"""
Discord Alerter for Sniper Bot
Sends webhook notifications for buy/sell/timeout events
"""
import os
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class DiscordAlerter:
    """Lightweight Discord webhook alerter for trading events."""
    
    def __init__(self):
        self.webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        self.enabled = bool(self.webhook_url)
        if not self.enabled:
            logger.warning("Discord webhook not set - alerts disabled. Set DISCORD_WEBHOOK_URL in .env")
    
    def _send_embed(self, title: str, description: str, color: int, fields: list = None):
        """Send a Discord embed via webhook."""
        if not self.enabled:
            return False
            
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Sniper Bot"}
        }
        
        if fields:
            embed["fields"] = fields
        
        payload = {"embeds": [embed]}
        
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=5)
            return resp.status_code == 204
        except Exception as e:
            logger.debug(f"Discord alert failed: {e}")
            return False
    
    def alert_buy_success(self, symbol: str, mint: str, amount_sol: float, entry_mc: float, tx_sig: str = None):
        """Alert on successful buy."""
        fields = [
            {"name": "Amount", "value": f"{amount_sol:.4f} SOL", "inline": True},
            {"name": "Entry MC", "value": f"${entry_mc:,.0f}", "inline": True},
            {"name": "Mint", "value": f"`{mint[:12]}...`", "inline": False}
        ]
        if tx_sig:
            fields.append({"name": "TX", "value": f"[View](https://solscan.io/tx/{tx_sig})", "inline": True})
        
        self._send_embed(
            title=f"🎯 BOUGHT: {symbol}",
            description=f"Sniped early position",
            color=0x00ff00,  # Green
            fields=fields
        )
    
    def alert_buy_failed(self, symbol: str, mint: str, reason: str):
        """Alert on failed buy."""
        self._send_embed(
            title=f"⚠️ BUY FAILED: {symbol}",
            description=f"Reason: {reason}",
            color=0xff0000,  # Red
            fields=[{"name": "Mint", "value": f"`{mint[:12]}...`", "inline": False}]
        )
    
    def alert_sell_tier(self, symbol: str, mint: str, tier: int, multiplier: float, percentage: int, tx_sig: str = None):
        """Alert on tier profit taking."""
        fields = [
            {"name": "Tier", "value": f"#{tier}", "inline": True},
            {"name": "Growth", "value": f"{multiplier:.1f}x", "inline": True},
            {"name": "Sold", "value": f"{percentage}%", "inline": True}
        ]
        if tx_sig:
            fields.append({"name": "TX", "value": f"[View](https://solscan.io/tx/{tx_sig})", "inline": True})
        
        self._send_embed(
            title=f"💰 TIER SELL: {symbol}",
            description=f"Profit taking at {multiplier:.1f}x",
            color=0x00ff00,  # Green
            fields=fields
        )
    
    def alert_stop_loss(self, symbol: str, mint: str, loss_pct: float, current_mc: float):
        """Alert on stop-loss trigger."""
        self._send_embed(
            title=f"🚨 STOP-LOSS: {symbol}",
            description=f"Exited at -{loss_pct:.0f}% to protect capital",
            color=0xff6600,  # Orange
            fields=[
                {"name": "MC at Exit", "value": f"${current_mc:,.0f}", "inline": True},
                {"name": "Mint", "value": f"`{mint[:12]}...`", "inline": False}
            ]
        )
    
    def alert_trailing_stop(self, symbol: str, mint: str, peak_mc: float, exit_mc: float, profit_mult: float):
        """Alert on trailing stop trigger."""
        self._send_embed(
            title=f"📉 TRAILING STOP: {symbol}",
            description=f"Locked in {profit_mult:.1f}x gains",
            color=0x00ff00 if profit_mult > 1 else 0xff6600,
            fields=[
                {"name": "Peak MC", "value": f"${peak_mc:,.0f}", "inline": True},
                {"name": "Exit MC", "value": f"${exit_mc:,.0f}", "inline": True},
                {"name": "Profit", "value": f"{profit_mult:.2f}x", "inline": True}
            ]
        )
    
    def alert_timeout_sell(self, symbol: str, mint: str, age_minutes: float, growth: float):
        """Alert on stagnation timeout sell."""
        self._send_embed(
            title=f"⏰ TIMEOUT SELL: {symbol}",
            description=f"Recycling stagnant position after {age_minutes:.0f} minutes",
            color=0xffaa00,  # Amber
            fields=[
                {"name": "Hold Time", "value": f"{age_minutes:.0f} min", "inline": True},
                {"name": "Growth", "value": f"{growth:.2f}x", "inline": True},
                {"name": "Mint", "value": f"`{mint[:12]}...`", "inline": False}
            ]
        )
    
    def alert_graduation(self, symbol: str, mint: str, final_mc: float):
        """Alert when token graduates to Raydium."""
        self._send_embed(
            title=f"🎓 GRADUATED: {symbol}",
            description=f"Token migrated to Raydium! Using Jupiter for sells.",
            color=0x9900ff,  # Purple
            fields=[
                {"name": "Final MC", "value": f"${final_mc:,.0f}", "inline": True},
                {"name": "Mint", "value": f"`{mint[:12]}...`", "inline": False}
            ]
        )

# Singleton instance
_alerter_instance = None

def get_discord_alerter() -> DiscordAlerter:
    global _alerter_instance
    if _alerter_instance is None:
        _alerter_instance = DiscordAlerter()
    return _alerter_instance
