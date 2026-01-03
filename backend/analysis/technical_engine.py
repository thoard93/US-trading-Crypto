import pandas as pd
import pandas_ta as ta

class TechnicalAnalysis:
    @staticmethod
    def analyze_trend(df, aggressive_mode=True):
        """
        Performs technical analysis on a dataframe of OHLCV data.
        aggressive_mode=True enables scalping thresholds (RSI 10/90 instead of 30/70)
        Returns a dictionary with indicators and a basic signal.
        """
        if df is None or len(df) < 5:
            return {"error": "Insufficient data"}
        
        # 0. Ensure DatetimeIndex for VWAP compatibility
        # If index is currently RangeIndex (0,1,2...), set it to timestamp column
        if 'timestamp' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            except Exception as e:
                # If timestamp conversion fails, we proceed without VWAP
                pass

        # 1. Define Base Variables
        # Note: We re-fetch last_row LATER after adding indicators
        current_close = float(df.iloc[-1]['close'])
        
        # 2. Define Thresholds
        RSI_OVERSOLD = 35 if aggressive_mode else 30
        RSI_OVERBOUGHT = 65 if aggressive_mode else 70

        # 3. Scalping Mode: RSI(2) + EMA(9) for hyper-fast signals
        if aggressive_mode:
            if len(df) >= 2: df.ta.rsi(length=2, append=True)
            if len(df) >= 9: df.ta.ema(length=9, append=True)
            
            # Re-fetch row with new indicators
            last_row = df.iloc[-1]
            rsi_val = last_row.get('RSI_2', 50)
            ema_fast = last_row.get('EMA_9', current_close)
            
            # Scalping Thresholds (Extremely sensitive)
            if rsi_val < 10 and current_close > ema_fast: # Reversal Up
                 return {
                    "price": round(current_close, 8),
                    "rsi": round(rsi_val, 2),
                    "signal": "BUY",
                    "reason": f"⚡ SCALP BUY: RSI(2) < 10 & Price > EMA(9)",
                    "ema_status": "Above EMA9"
                 }
            if rsi_val > 90 and current_close < ema_fast: # Reversal Down
                 return {
                    "price": round(current_close, 8),
                    "rsi": round(rsi_val, 2),
                    "signal": "SELL",
                    "reason": f"⚡ SCALP SELL: RSI(2) > 90 & Price < EMA(9)",
                    "ema_status": "Below EMA9"
                 }

        # 4. Standard Mode: VWAP + RSI(14) calculation
        if len(df) >= 14:
            df.ta.rsi(length=14, append=True)
            try:
                # VWAP requires DatetimeIndex (handled in step 0)
                df.ta.vwap(append=True) 
            except:
                pass # Skip VWAP if index issues persist

        if len(df) >= 20:
            df.ta.ema(length=20, append=True)
        if len(df) >= 50:
            df.ta.ema(length=50, append=True)

        # Re-fetch last_row after ALL indicators added
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else last_row
        
        close = float(last_row['close'])
        prev_close = float(prev_row['close'])
        
        rsi = last_row.get('RSI_14', 50)
        vwap = last_row.get('VWAP_D', 0) 
        
        # 5. Low Data Handling (< 20 bars)
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

        # 6. Full Analysis (> 20 bars)
        ema_20 = last_row.get('EMA_20', close)
        prev_ema_20 = prev_row.get('EMA_20', prev_close)
        ema_50 = last_row.get('EMA_50', ema_20)

        signal = "NEUTRAL"
        reason = "No strong signal"
        
        # PRIORITY 0: Sniper Pullback (Research Strategy)
        # "Wait for pullback of 40-60% from migration high"
        if aggressive_mode:
            max_high = df['high'].max()
            pullback_target = max_high * 0.60 # 40% drop = 60% of High
            
            # If price is DEEP in the dip but showing some support (e.g., above EMA50 or RSI oversold)
            if close <= pullback_target:
                 # Check if we are not crashing to zero (RSI > 20 to avoid dead coins?)
                 # Video says "Target consistent small gains".
                 # We'll treat this as a strong setup.
                 signal = "BUY"
                 reason = f"📉 Sniper Entry: 40%+ Pullback from High ({max_high})"

        # PRIORITY 1: RSI Extremes
        if rsi < RSI_OVERSOLD:
            signal = "BUY"
            reason = f"🚀 Oversold (RSI < {RSI_OVERSOLD}) - Potential low entry"
        elif rsi > RSI_OVERBOUGHT:
            signal = "SELL"
            reason = f"⚠️ Overbought (RSI > {RSI_OVERBOUGHT}) - Potential local top"
        
        # PRIORITY 2: EMA Crossover (Momentum)
        elif prev_close < prev_ema_20 and close > ema_20:
            signal = "BUY"
            reason = "📈 Momentum: Price crossed above EMA20"
        elif prev_close > prev_ema_20 and close < ema_20:
            signal = "SELL"
            reason = "📉 Momentum: Price crossed below EMA20"
            
        # PRIORITY 3: Trend Detection
        elif close > ema_20 and ema_20 > ema_50:
            signal = "BULLISH"
            reason = "📈 Strong Uptrend: Price > EMA20 > EMA50"
        elif close < ema_20 and ema_20 < ema_50:
            signal = "BEARISH"
            reason = "📉 Downtrend: Price < EMA20 < EMA50"

        # VWAP Confirmation (Optional append)
        if signal == "BUY" and vwap > 0 and close > vwap:
             reason += " (VWAP Confirmed)"

        return {
            "price": round(close, 8),
            "rsi": round(rsi, 2),
            "signal": signal,
            "reason": reason,
            "ema_status": "Above" if close > ema_20 else "Below"
        }
