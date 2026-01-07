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
        
        # MACD (Momentum Confirmation)
        if len(df) >= 26:
            df.ta.macd(append=True)
        
        # Volume Analysis
        df['volume_avg'] = df['volume'].rolling(window=20).mean()
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
        
        # MACD Confirmation (Momentum)
        macd_hist = last_row.get('MACDh_12_26_9', 0)
        macd_bullish = macd_hist > 0
        
        # Volume Confirmation
        current_vol = last_row.get('volume', 0)
        avg_vol = last_row.get('volume_avg', current_vol or 1)
        volume_spike = current_vol > (avg_vol * 1.5)

        # Thresholds - MODERATE MODE (30/70 = balanced between aggressive and conservative)
        RSI_OVERSOLD = 30 if aggressive_mode else 30  # Was 25 - slightly looser
        RSI_OVERBOUGHT = 70 if aggressive_mode else 70  # Was 75 - slightly looser

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
                 # Ensure we aren't catching a falling knife blindly
                 # REQUIREMENT: Volume Capitulation (Panic Selling) to confirm bottom
                 if volume_spike and rsi > 20: 
                    signal = "BUY"
                    reason = f"📉 Sniper Entry: 40%+ Pullback + Vol Spike ({close:.4f})"
                    confidence = 85

        # PRIORITY 3: Scalping (BUY Only - Exits handled by Trailing Stop/SL/TP)
        if aggressive_mode and confidence < 80:
            # BUY: Dip in Uptrend + Oversold RSI(2) + MACD Confirmation
            # This logic was already good (Close > EMA 50), keeping it.
            if rsi_fast < 15 and close > ema_50 and macd_bullish: 
                signal = "BUY"
                reason = "⚡ Scalp: Trend Pullback + MACD Confirm"
                confidence = 75

        # PRIORITY 4: Standard Indicators (RSI / Trends) - OVERHAULED 2026
        if confidence < 70:
            # RSI OVERSOLD LOGIC (The "Knife Catching" Fix)
            if rsi < RSI_OVERSOLD:
                # SCENARIO A: Strong Uptrend (Safe to buy dip)
                if close > ema_50:
                    signal = "BUY"
                    reason = f"🚀 Uptrend Dip (RSI {rsi:.0f} > EMA50)"
                # SCENARIO B: Downtrend but Capitulation (Volume Spike + MACD)
                # Harder to catch, usually safer to wait.
                elif volume_spike and macd_bullish:
                     signal = "BUY"
                     reason = f"♻️ Reversal: Volume+MACD (RSI {rsi:.0f})"
                else:
                    # IGNORING signal - Trend is down and no reversal confirmation
                    pass

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
