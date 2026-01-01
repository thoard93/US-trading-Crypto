import pandas as pd
import pandas_ta as ta

class TechnicalAnalysis:
    @staticmethod
    def analyze_trend(df):
        """
        Performs technical analysis on a dataframe of OHLCV data.
        Returns a dictionary with indicators and a basic signal.
        """
        if df is None or len(df) < 50:
            print(f"Insufficient data for analysis: {len(df) if df is not None else 0} rows")
            return {"error": "Insufficient data"}

        # Calculate Indicators
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.macd(append=True)

        last_row = df.iloc[-1]
        
        # Simple Short-term Logic
        rsi = last_row['RSI_14']
        ema_20 = last_row['EMA_20']
        ema_50 = last_row['EMA_50']
        close = last_row['close']

        signal = "NEUTRAL"
        reason = "No strong signal"

        if rsi < 30:
            signal = "BUY"
            reason = "🚀 Oversold (RSI < 30) - Potential low entry"
        elif rsi > 70:
            signal = "SELL"
            reason = "⚠️ Overbought (RSI > 70) - Potential local top"
        elif close > ema_20 and ema_20 > ema_50:
            signal = "BULLISH"
            reason = "📈 Strong Uptrend: Price > EMA20 > EMA50"
        elif close < ema_20 and ema_20 < ema_50:
            signal = "BEARISH"
            reason = "📉 Downtrend: Price < EMA20 < EMA50"

        return {
            "price": round(close, 4),
            "rsi": round(rsi, 2),
            "signal": signal,
            "reason": reason,
            "ema_status": "Above" if close > ema_20 else "Below"
        }
