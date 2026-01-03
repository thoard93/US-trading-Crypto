import pandas as pd
import pandas_ta as ta

class TechnicalAnalysis:
    @staticmethod
    def analyze_trend(df, aggressive_mode=True):
        """
        Performs technical analysis on a dataframe of OHLCV data.
        aggressive_mode=True enables scalping thresholds & SMC Logic.
        Returns a dictionary with indicators and a signal.
        """
        if df is None or len(df) < 5:
            return {"error": "Insufficient data"}
        
        # 0. Ensure DatetimeIndex for VWAP compatibility
        if 'timestamp' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            except Exception:
                pass

        # 1. Base Variables
        current_close = float(df.iloc[-1]['close'])
        
        # 2. Add Indicators
        # RSI 14 (Standard)
        if len(df) >= 14:
            df.ta.rsi(length=14, append=True)
            try:
                df.ta.vwap(append=True) # VWAP requires DatetimeIndex
            except:
                pass 

        # EMAs (Trend)
        if len(df) >= 20: df.ta.ema(length=20, append=True)
        if len(df) >= 50: df.ta.ema(length=50, append=True)

        # Scalping Indicators (RSI 2 + EMA 9)
        if aggressive_mode:
            if len(df) >= 2: df.ta.rsi(length=2, append=True)
            if len(df) >= 9: df.ta.ema(length=9, append=True)

        # 3. Fetch Latest Data Row
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else last_row
        
        close = float(last_row['close'])
        prev_close = float(prev_row['close'])
        
        # Safe Getters
        rsi = last_row.get('RSI_14', 50)
        vwap = last_row.get('VWAP_D', 0) 
        ema_20 = last_row.get('EMA_20', close)
        ema_50 = last_row.get('EMA_50', close)
        
        # Scalping Vars
        rsi_fast = last_row.get('RSI_2', 50)
        ema_fast = last_row.get('EMA_9', close)

        # Thresholds
        RSI_OVERSOLD = 35 if aggressive_mode else 30
        RSI_OVERBOUGHT = 65 if aggressive_mode else 70

        # --- SIGNAL LOGIC PRIORITY ---
        signal = "NEUTRAL"
        reason = "No strong signal"
        confidence = 0

        # PRIORITY 1: SMC / Fair Value Gaps (The "Sniper" Setup)
        # Looking for bullish FVG retests
        if aggressive_mode and len(df) >= 3:
            # Candles: 1 (Oldest), 2, 3 (Latest/Current)
            # Actually pattern is usually previous completed candles. 
            # Let's look at the gap between Candle -3 High and Candle -1 Low relative to NOW.
            
            c1_high = df['high'].iloc[-3]
            c3_low = df['low'].iloc[-1] # Current candle low
            
            # This is a bit simplistic for live FVG. 
            # Developing FVG: Candle -2 had a huge pump, leaving a gap between -3 High and -1 Low.
            # We want to buy if Price Retraces INTO a formed FVG.
            
            # Let's check if a FVG *exists* from previous candles (e.g. Candle -4 High vs Candle -2 Low)
            # And current price is inside it.
            if len(df) >= 5:
                # Check for FVG formed recently
                fvg_detected = False
                fvg_zone = (0,0)
                
                # Check FVG formed by Candle -3 (Gap between -4 High and -2 Low)
                c4_high = df['high'].iloc[-4]
                c2_low = df['low'].iloc[-2]
                
                if c2_low > c4_high: # Gap exists
                    fvg_detected = True
                    fvg_zone = (c4_high, c2_low) # Bottom, Top
                
                if fvg_detected:
                    gap_bottom, gap_top = fvg_zone
                    # Retest Logic: Current Close is INSIDE the gap
                    if gap_bottom <= close <= gap_top:
                        signal = "BUY"
                        reason = f"🏰 SMC: Bullish FVG Retest (Gap {gap_bottom:.4f}-{gap_top:.4f})"
                        confidence = 90 # Highest Priority

        # PRIORITY 2: Deep Pullback "Sniper" (Research Phase)
        if aggressive_mode and confidence < 90:
            max_high = df['high'].max()
            pullback_target = max_high * 0.60 # 40% Drop
            if close <= pullback_target:
                 # Ensure we aren't catching a falling knife blindly; check RSI not dead
                 if rsi > 20: 
                    signal = "BUY"
                    reason = f"📉 Sniper Entry: 40%+ Pullback ({close:.4f} < {pullback_target:.4f})"
                    confidence = 85

        if aggressive_mode and confidence < 80:
            # BUY: Dip in Uptrend (Price > EMA 50) + Oversold RSI(2)
            if rsi_fast < 15 and close > ema_50: 
                signal = "BUY"
                reason = "⚡ Scalp: Trend Pullback (Price > EMA50 & RSI(2) < 15)"
                confidence = 75
            elif rsi_fast > 90 and close < ema_fast:
                signal = "SELL"
                reason = "⚡ Scalp: RSI(2) > 90 & Price < EMA9"
                confidence = 75

        # PRIORITY 4: Standard Indicators (RSI / Trends)
        if confidence < 70:
            if rsi < RSI_OVERSOLD:
                signal = "BUY"
                reason = f"🚀 Oversold (RSI {rsi:.0f})"
            elif rsi > RSI_OVERBOUGHT:
                signal = "SELL"
                reason = f"⚠️ Overbought (RSI {rsi:.0f})"
            elif close > ema_20 and ema_20 > ema_50:
                signal = "BULLISH"
                reason = "📈 Strong Uptrend"
            elif close < ema_20 and ema_20 < ema_50:
                signal = "BEARISH"
                reason = "📉 Downtrend"

        return {
            "price": round(close, 8),
            "rsi": round(rsi, 2),
            "signal": signal,
            "reason": reason,
            "ema_status": "Above" if close > ema_20 else "Below"
        }
