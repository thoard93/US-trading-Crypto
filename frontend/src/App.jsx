import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  Activity,
  Wallet,
  Settings,
  History,
  ShieldCheck,
  ChevronRight,
  Zap,
  LayoutDashboard,
  Search,
  Bell,
  LogOut
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const mockChartData = [
  { time: '10:00', price: 92400 },
  { time: '10:05', price: 92800 },
  { time: '10:10', price: 92600 },
  { time: '10:15', price: 93200 },
  { time: '10:20', price: 93500 },
  { time: '10:25', price: 93800 },
  { time: '10:30', price: 94200 },
];

const mockPositions = [
  { symbol: 'XRP/USDT', entry: 2.12, current: 2.34, profit: '+10.4%', side: 'BUY' },
  { symbol: 'SOL/USDT', entry: 185.00, current: 184.20, profit: '-0.4%', side: 'BUY' },
];

const mockLogs = [
  { type: 'BUY', symbol: 'XRP/USDT', price: 2.12, time: '2m ago' },
  { type: 'SELL', symbol: 'SOL/USDT', price: 185.00, time: '15m ago' },
  { type: 'BUY', symbol: 'SOL/USDT', price: 184.50, time: '40m ago' },
];

function App() {
  return (
    <div className="dashboard-layout">
      {/* Sidebar */}
      <aside className="glass glow-shadow sidebar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className="glass" style={{ width: '40px', height: '40px', background: 'var(--accent-color)', borderRadius: '12px', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
            <Zap size={24} color="#05070a" fill="#05070a" />
          </div>
          <h2 style={{ fontSize: '1.25rem' }}>ANTIGRAVITY</h2>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <NavItem icon={<LayoutDashboard size={20} />} label="Dashboard" active />
          <NavItem icon={<TrendingUp size={20} />} label="Live Markets" />
          <NavItem icon={<Wallet size={20} />} label="Portfolio" />
          <NavItem icon={<History size={20} />} label="Trade History" />
          <NavItem icon={<ShieldCheck size={20} />} label="Safety Audit" />
          <NavItem icon={<Settings size={20} />} label="Settings" />
        </nav>

        <div style={{ marginTop: 'auto' }}>
          <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.05)' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>SYSTEM STATUS</p>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
              <div style={{ width: '8px', height: '8px', background: 'var(--success)', borderRadius: '50%' }}></div>
              <span style={{ fontSize: '0.875rem' }}>Bot Active</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="glass glow-shadow" style={{ padding: '16px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Search size={20} color="var(--text-secondary)" />
            <input
              type="text"
              placeholder="Search markets..."
              style={{ background: 'transparent', border: 'none', color: 'var(--text-primary)', outline: 'none', fontSize: '1rem' }}
            />
          </div>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <div className="glass" style={{ padding: '8px', borderRadius: '12px' }}><Bell size={20} /></div>
            <div className="glass" style={{ width: '36px', height: '36px', borderRadius: '12px', background: 'linear-gradient(45deg, #00ffcc, #0099ff)' }}></div>
          </div>
        </header>

        <section className="glass glow-shadow chart-container">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px' }}>
            <div>
              <h1 style={{ fontSize: '2rem' }}>BTC / USDT</h1>
              <p style={{ color: 'var(--text-secondary)' }}>$94,204.32 <span style={{ color: 'var(--success)' }}>+2.45%</span></p>
            </div>
            <div className="glass" style={{ display: 'flex', padding: '4px' }}>
              <button className="glass" style={{ padding: '6px 16px', background: 'rgba(255,255,255,0.1)' }}>1H</button>
              <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>4H</button>
              <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>1D</button>
            </div>
          </div>

          <div style={{ height: '100%', minHeight: '300px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={mockChartData}>
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00ffcc" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#00ffcc" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis hide />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px' }}
                  itemStyle={{ color: '#00ffcc' }}
                />
                <Area type="monotone" dataKey="price" stroke="#00ffcc" strokeWidth={3} fillOpacity={1} fill="url(#colorPrice)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
          <StatCard label="Total Profit" value="$1,245.00" sub="+12.5% this week" color="var(--success)" />
          <StatCard label="Active Bots" value="3 Running" sub="XRP, SOL, ETH" color="var(--accent-color)" />
        </div>
      </main>

      {/* Right Panel */}
      <aside className="right-panel">
        <section className="glass glow-shadow" style={{ padding: '24px', flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3>Active Positions</h3>
            <ChevronRight size={20} color="var(--text-secondary)" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {mockPositions.map((pos, i) => (
              <PositionItem key={i} {...pos} />
            ))}
          </div>
        </section>

        <section className="glass glow-shadow" style={{ padding: '24px', flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3>Recent Activity</h3>
            <History size={20} color="var(--text-secondary)" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {mockLogs.map((log, i) => (
              <LogItem key={i} {...log} />
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}

function NavItem({ icon, label, active = false }) {
  return (
    <div className={`glass`} style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '12px 16px',
      cursor: 'pointer',
      background: active ? 'rgba(0, 255, 204, 0.1)' : 'transparent',
      borderColor: active ? 'rgba(0, 255, 204, 0.3)' : 'transparent',
      color: active ? 'var(--accent-color)' : 'var(--text-secondary)'
    }}>
      {icon}
      <span style={{ fontWeight: 500 }}>{label}</span>
    </div>
  );
}

function StatCard({ label, value, sub, color }) {
  return (
    <div className="glass glow-shadow" style={{ padding: '24px' }}>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{label}</p>
      <h2 style={{ fontSize: '1.75rem', marginTop: '8px', color: color }}>{value}</h2>
      <p style={{ fontSize: '0.875rem', marginTop: '4px', opacity: 0.8 }}>{sub}</p>
    </div>
  );
}

function PositionItem({ symbol, entry, current, profit, side }) {
  const isProfit = profit.startsWith('+');
  return (
    <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.02)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontWeight: 600 }}>{symbol}</span>
        <span className={`badge ${isProfit ? 'badge-success' : 'badge-danger'}`}>{profit}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
        <span>Entry: ${entry}</span>
        <span>Now: ${current}</span>
      </div>
    </div>
  );
}

function LogItem({ type, symbol, price, time }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
      <div style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: type === 'BUY' ? 'var(--success)' : 'var(--danger)'
      }}></div>
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: '0.875rem' }}>{type} **{symbol}**</p>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>at ${price}</p>
      </div>
      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{time}</span>
    </div>
  );
}

export default App;
