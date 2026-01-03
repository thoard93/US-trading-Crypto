import pandas as pd
import pandas_ta as ta

class TechnicalAnalysis:
    @staticmethod
    def analyze_trend(df, aggressive_mode=True):
        """
        Performs technical analysis on a dataframe of OHLCV data.
        aggressive_mode=True enables scalping thresholds (RSI 35/65 instead of 30/70)
        Returns a dictionary with indicators and a basic signal.
        """
        if df is None or len(df) < 5:
            return {"error": "Insufficient data"}
        
        # Scalping Mode: RSI(2) + EMA(9) for hyper-fast signals
        if aggressive_mode:
            if len(df) >= 2: df.ta.rsi(length=2, append=True)
            if len(df) >= 9: df.ta.ema(length=9, append=True)
            rsi_val = last_row.get('RSI_2', 50)
            ema_fast = last_row.get('EMA_9', close)
            
            # Scalping Thresholds (Extremely sensitive)
            if rsi_val < 10 and close > ema_fast: # Reversal Up
                 return {
                    "price": round(close, 8),
                    "rsi": round(rsi_val, 2),
                    "signal": "BUY",
                    "reason": f"⚡ SCALP BUY: RSI(2) < 10 & Price > EMA(9)",
                    "ema_status": "Above EMA9"
                 }
            if rsi_val > 90 and close < ema_fast: # Reversal Down
                 return {
                    "price": round(close, 8),
                    "rsi": round(rsi_val, 2),
                    "signal": "SELL",
                    "reason": f"⚡ SCALP SELL: RSI(2) > 90 & Price < EMA(9)",
                    "ema_status": "Below EMA9"
                 }

        # Standard Mode: VWAP + RSI(14)
        if len(df) >= 14:
            df.ta.vwap(append=True) # Volume Weighted Average Price
            
        vwap = last_row.get('VWAP_D', 0) # Daily VWAP
        
        # 14-20 bars: Basic RSI check
        if len(df) < 20:
             # Syntax Verified
            signal = "NEUTRAL"
            reason = "Collecting more data for trend analysis"
            
            if rsi < RSI_OVERSOLD:
                signal = "BUY"
                reason = f"🚀 Oversold (RSI < {RSI_OVERSOLD}) - Potential low entry"
            elif rsi > RSI_OVERBOUGHT:
                signal = "SELL"
                reason = f"⚠️ Overbought (RSI > {RSI_OVERBOUGHT}) - Potential local top"
            
            return {
                "price": round(close, 8),
                "rsi": round(rsi, 2),
                "signal": signal,
                "reason": reason,
                "ema_status": "N/A"
            }
        ema_20 = last_row.get('EMA_20', close)
        prev_ema_20 = prev_row.get('EMA_20', prev_close)
        ema_50 = last_row.get('EMA_50', ema_20)  # Fallback to EMA_20 if no EMA_50

        signal = "NEUTRAL"
        reason = "No strong signal"

        # PRIORITY 1: RSI Extremes
        if rsi < RSI_OVERSOLD:
            signal = "BUY"
            reason = f"🚀 Oversold (RSI < {RSI_OVERSOLD}) - Potential low entry"
        elif rsi > RSI_OVERBOUGHT:
            signal = "SELL"
            reason = f"⚠️ Overbought (RSI > {RSI_OVERBOUGHT}) - Potential local top"
        
        # PRIORITY 2: EMA Crossover (Momentum)
        elif prev_close < prev_ema_20 and close > ema_20:
            # Price crossed ABOVE EMA20 = Bullish Momentum
            signal = "BUY"
            reason = "📈 Momentum: Price crossed above EMA20"
        elif prev_close > prev_ema_20 and close < ema_20:
            # Price crossed BELOW EMA20 = Bearish Momentum
            signal = "SELL"
            reason = "📉 Momentum: Price crossed below EMA20"
            
        # PRIORITY 3: Trend Detection (for info)
        elif close > ema_20 and ema_20 > ema_50:
            signal = "BULLISH"
            reason = "📈 Strong Uptrend: Price > EMA20 > EMA50"
        elif close < ema_20 and ema_20 < ema_50:
            signal = "BEARISH"
            reason = "📉 Downtrend: Price < EMA20 < EMA50"

        return {
            "price": round(close, 8),
            "rsi": round(rsi, 2),
            "signal": signal,
            "reason": reason,
            "ema_status": "Above" if close > ema_20 else "Below"
        }

