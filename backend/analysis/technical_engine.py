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
        
        # RSI Thresholds based on mode
        RSI_OVERSOLD = 35 if aggressive_mode else 30
        RSI_OVERBOUGHT = 65 if aggressive_mode else 70
        
        # Calculate Indicators (Need at least 14 for RSI, but we can compute what we have)
        if len(df) >= 14:
            df.ta.rsi(length=14, append=True)
        if len(df) >= 20:
            df.ta.ema(length=20, append=True)
        if len(df) >= 50:
            df.ta.ema(length=50, append=True)
        
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else last_row
        close = last_row['close']
        prev_close = prev_row['close']
        
        # Minimum 14 bars for RSI-only analysis
        if len(df) < 14:
            return {
                "price": round(close, 8),
                "rsi": "N/A",
                "signal": "NEUTRAL",
                "reason": f"Warming up engine ({len(df)}/14 bars for RSI)",
                "ema_status": "N/A"
            }
        
        rsi = last_row.get('RSI_14', 50)  # Default to neutral if not computed
        
        # 14-20 bars: RSI-only analysis
        if len(df) < 20:
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

