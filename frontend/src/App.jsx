import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
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
  RefreshCw,
  Play,
  Square
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const USER_ID = 1; // Default for now

function App() {
  const [activeTab, setActiveTab] = useState('Dashboard');
  const [chartData, setChartData] = useState([]);
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({ total_profit: '$0.00', active_bots_count: 0, active_bot_names: 'Connecting...' });
  const [status, setStatus] = useState({ is_running: false });
  const [loading, setLoading] = useState(false);
  const [activeSymbol, setActiveSymbol] = useState('BTC/USDT');
  const [searchInput, setSearchInput] = useState('');

  const fetchData = useCallback(async () => {
    try {
      // 1. Status
      const statusRes = await axios.get(`${API_BASE}/status/${USER_ID}`);
      setStatus(statusRes.data);

      // 2. Positions
      const posRes = await axios.get(`${API_BASE}/positions/${USER_ID}`);
      setPositions(posRes.data);

      // 3. Trade Logs
      const logsRes = await axios.get(`${API_BASE}/trades/${USER_ID}`);
      setLogs(logsRes.data);

      // 4. Stats
      const statsRes = await axios.get(`${API_BASE}/stats/${USER_ID}`);
      setStats(statsRes.data);

      // 5. Chart Data
      const chartRes = await axios.get(`${API_BASE}/chart/${activeSymbol.replace('/', '%2F')}`);
      setChartData(chartRes.data);
    } catch (err) {
      console.error("API Error:", err);
    }
  }, [activeSymbol]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleBot = async () => {
    setLoading(true);
    try {
      if (status.is_running) {
        await axios.post(`${API_BASE}/users/stop/${USER_ID}`);
      } else {
        await axios.post(`${API_BASE}/users/start/${USER_ID}`);
      }
      await fetchData();
    } catch (err) {
      alert("Bot control error. Please check if backend is live.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e) => {
    if (e.key === 'Enter' && searchInput) {
      let sym = searchInput.toUpperCase();
      if (!sym.includes('/')) sym = `${sym}/USDT`;
      setActiveSymbol(sym);
      setSearchInput('');
    }
  };

  return (
    <div className="dashboard-layout">
      {/* Sidebar */}
      <aside className="glass glow-shadow sidebar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className="glass" style={{ width: '40px', height: '40px', background: 'var(--accent-color)', borderRadius: '12px', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
            <Zap size={24} color="#05070a" fill="#05070a" />
          </div>
          <h2 style={{ fontSize: '1.25rem' }}>ANTIGRAVITY <span style={{ fontSize: '0.6rem', color: 'var(--accent-color)', verticalAlign: 'top' }}>V2.0 LIVE</span></h2>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <NavItem icon={<LayoutDashboard size={20} />} label="Dashboard" active={activeTab === 'Dashboard'} onClick={() => setActiveTab('Dashboard')} />
          <NavItem icon={<TrendingUp size={20} />} label="Live Markets" active={activeTab === 'Live Markets'} onClick={() => setActiveTab('Live Markets')} />
          <NavItem icon={<Wallet size={20} />} label="Portfolio" active={activeTab === 'Portfolio'} onClick={() => setActiveTab('Portfolio')} />
          <NavItem icon={<History size={20} />} label="Trade History" active={activeTab === 'Trade History'} onClick={() => setActiveTab('Trade History')} />
          <NavItem icon={<ShieldCheck size={20} />} label="Safety Audit" active={activeTab === 'Safety Audit'} onClick={() => setActiveTab('Safety Audit')} />
          <NavItem icon={<Settings size={20} />} label="Settings" active={activeTab === 'Settings'} onClick={() => setActiveTab('Settings')} />
        </nav>

        <div style={{ marginTop: 'auto' }}>
          <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.05)' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>SYSTEM STATUS</p>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', background: status.is_running ? 'var(--success)' : 'var(--danger)', borderRadius: '50%' }}></div>
                <span style={{ fontSize: '0.875rem' }}>{status.is_running ? 'Bot Active' : 'Bot Idle'}</span>
              </div>
              <button
                onClick={toggleBot}
                disabled={loading}
                className="glass"
                style={{ padding: '6px', borderRadius: '8px', cursor: 'pointer', background: status.is_running ? 'rgba(255, 71, 87, 0.1)' : 'rgba(0, 255, 204, 0.1)' }}
              >
                {status.is_running ? <Square size={16} color="var(--danger)" /> : <Play size={16} color="var(--accent-color)" />}
              </button>
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
              placeholder="Search e.g. BTC/USDT and press Enter"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={handleSearch}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-primary)', outline: 'none', fontSize: '1rem', width: '300px' }}
            />
          </div>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <div className="glass" style={{ padding: '8px', borderRadius: '12px', cursor: 'pointer' }} onClick={fetchData}><RefreshCw size={20} className={loading ? 'spin' : ''} /></div>
            <div className="glass" style={{ width: '36px', height: '36px', borderRadius: '12px', background: 'linear-gradient(45deg, #00ffcc, #0099ff)' }}></div>
          </div>
        </header>

        <section className="glass glow-shadow chart-container">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px' }}>
            <div>
              <h1 style={{ fontSize: '2rem' }}>{activeSymbol}</h1>
              <p style={{ color: 'var(--text-secondary)' }}>
                {chartData.length > 0 ? `$${chartData[chartData.length - 1].price.toLocaleString()}` : 'Loading...'}
                <span style={{ color: 'var(--success)', marginLeft: '8px', fontSize: '0.8rem' }}>LIVE 5M</span>
              </p>
            </div>
            <div className="glass" style={{ display: 'flex', padding: '4px' }}>
              <button className="glass" style={{ padding: '6px 16px', background: 'rgba(255,255,255,0.1)' }}>5M</button>
              <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>1H</button>
              <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>1D</button>
            </div>
          </div>

          <div style={{ height: '300px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00ffcc" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#00ffcc" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <YAxis domain={['auto', 'auto']} hide />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px' }}
                  itemStyle={{ color: '#00ffcc' }}
                />
                <Area animationDuration={1000} type="monotone" dataKey="price" stroke="#00ffcc" strokeWidth={3} fillOpacity={1} fill="url(#colorPrice)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
          <StatCard label="Total Profit" value={stats.total_profit} sub="Combined performance" color="var(--success)" />
          <StatCard label="Active Strategy" value={stats.active_bot_names} sub={`${stats.active_bots_count} engine(s) monitoring`} color="var(--accent-color)" />
        </div>
      </main>

      {/* Right Panel */}
      <aside className="right-panel">
        <section className="glass glow-shadow" style={{ padding: '24px', flex: 1, minHeight: '300px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3>Active Positions</h3>
            {positions.length > 0 && <span className="badge badge-success">{positions.length}</span>}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {positions.length > 0 ? (
              positions.map((pos, i) => <PositionItem key={i} {...pos} />)
            ) : (
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>No active trades detected.</p>
            )}
          </div>
        </section>

        <section className="glass glow-shadow" style={{ padding: '24px', flex: 1, minHeight: '300px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3>Recent Activity</h3>
            <History size={20} color="var(--text-secondary)" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {logs.length > 0 ? (
              logs.map((log, i) => <LogItem key={i} {...log} />)
            ) : (
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>History is empty.</p>
            )}
          </div>
        </section>
      </aside>
    </div>
  );
}

function NavItem({ icon, label, active = false, onClick }) {
  return (
    <div className={`glass`} onClick={onClick} style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '12px 16px',
      cursor: 'pointer',
      transition: 'all 0.3s ease',
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

function PositionItem({ symbol, entry, current, profit }) {
  const isProfit = parseFloat(profit) >= 0;
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
