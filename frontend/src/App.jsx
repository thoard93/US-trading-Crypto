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
  Square,
  AlertTriangle,
  Globe,
  Database,
  User,
  MessageSquare,
  Cpu,
  Wifi,
  WifiOff,
  ExternalLink
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

// --- SMART API RESOLVER ---
const resolveApiBase = () => {
  let base = import.meta.env.VITE_API_URL || '';

  // If we're in a browser on Render
  if (typeof window !== 'undefined' && window.location.hostname.includes('onrender.com')) {
    const currentHost = window.location.hostname; // e.g. trading-dashboard-vpwb.onrender.com

    // Check if the current environment variable is an internal Render name (like trading-api-1pe7)
    // or if we need to derive the public name from the dashboard's own URL.
    if (!base || base.includes('-1pe7') || !base.includes('onrender.com')) {
      const suffix = currentHost.replace('trading-dashboard-', '');
      base = `https://trading-api-${suffix}`;
    }
  }

  // Final sanitization
  if (!base.startsWith('http')) base = `https://${base}`;
  return base.replace(/\/$/, ''); // Remove trailing slash
};

const API_BASE = resolveApiBase();
const USER_ID = 1;

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError(error) { return { hasError: true }; }
  componentDidCatch(error, errorInfo) { console.error("UI Crash:", error, errorInfo); }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#ef4444', gap: '16px', background: '#05070a' }}>
          <AlertTriangle size={48} />
          <h2>Dashboard Component Error</h2>
          <button onClick={() => window.location.reload()} style={{ padding: '8px 24px', background: '#00ffcc', borderRadius: '8px', color: '#000' }}>Retry Layout</button>
        </div>
      );
    }
    return this.props.children;
  }
}

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
  const [apiError, setApiError] = useState(null);
  const [lastHeartbeat, setLastHeartbeat] = useState(null);
  const [connectionActive, setConnectionActive] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      // 1. Check Status (Heartbeat) - Short timeout to fail fast
      const statusRes = await axios.get(`${API_BASE}/status/${USER_ID}`, { timeout: 4000 });
      if (statusRes.data) {
        setStatus(statusRes.data);
        setLastHeartbeat(new Date().toLocaleTimeString());
        setConnectionActive(true);
        setApiError(null);
      } else {
        throw new Error("Empty Response");
      }

      // Parallel fetch for speed
      const [posRes, logsRes, statsRes, chartRes] = await Promise.all([
        axios.get(`${API_BASE}/positions/${USER_ID}`).catch(() => ({ data: [] })),
        axios.get(`${API_BASE}/trades/${USER_ID}`).catch(() => ({ data: [] })),
        axios.get(`${API_BASE}/stats/${USER_ID}`).catch(() => ({ data: {} })),
        axios.get(`${API_BASE}/chart/${activeSymbol.replace('/', '%2F')}`).catch(() => ({ data: [] }))
      ]);

      if (Array.isArray(posRes.data)) setPositions(posRes.data);
      if (Array.isArray(logsRes.data)) setLogs(logsRes.data);
      if (statsRes.data) setStats(statsRes.data);
      if (Array.isArray(chartRes.data)) setChartData(chartRes.data);

    } catch (err) {
      console.warn("Connection Status:", err.message);
      setConnectionActive(false);
      setApiError("Backend route blocked. Cross-checking...");
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
      setTimeout(fetchData, 1500);
    } catch (err) {
      alert("Bot control failed. The API might still be warming up.");
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

  const renderTabContent = () => {
    if (!connectionActive && activeTab === 'Dashboard') {
      return (
        <div className="glass glow-shadow" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '20px', padding: '40px' }}>
          <div className="glass" style={{ padding: '24px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.05)' }}>
            <WifiOff size={48} color="var(--danger)" />
          </div>
          <h2 style={{ fontSize: '1.5rem' }}>Connection Search</h2>
          <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '400px' }}>
            We've detected an internal Render route. I'm attempting to bridge your connection to the public gateway: <code>{API_BASE}</code>
          </p>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button onClick={fetchData} className="glass" style={{ padding: '12px 32px', background: 'rgba(0, 255, 204, 0.1)', color: 'var(--accent-color)' }}>Ping Bridge</button>
            <button onClick={() => setActiveTab('Settings')} className="glass" style={{ padding: '12px 32px' }}>Route Details</button>
          </div>
        </div>
      );
    }

    switch (activeTab) {
      case 'Dashboard':
        return (
          <>
            <section className="glass glow-shadow chart-container" style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px' }}>
                <div>
                  <h1 style={{ fontSize: '2rem' }}>{activeSymbol}</h1>
                  <p style={{ color: 'var(--text-secondary)' }}>
                    {chartData.length > 0 && chartData[chartData.length - 1]?.price
                      ? `$${chartData[chartData.length - 1].price.toLocaleString()}`
                      : 'Polling Live Market Data...'}
                    <span style={{ color: 'var(--success)', marginLeft: '8px', fontSize: '0.8rem' }}>5M SCALPER</span>
                  </p>
                </div>
                <div className="glass" style={{ display: 'flex', padding: '4px' }}>
                  <button className="glass" style={{ padding: '6px 16px', background: 'rgba(255,255,255,0.1)' }}>5M</button>
                  <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>1H</button>
                  <button style={{ padding: '6px 16px', color: 'var(--text-secondary)' }}>1D</button>
                </div>
              </div>

              <div style={{ flex: 1, minHeight: '300px' }}>
                {chartData.length > 0 ? (
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
                ) : (
                  <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                    <Activity size={32} className="spin" style={{ opacity: 0.5 }} />
                  </div>
                )}
              </div>
            </section>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <StatCard label="Total Profit" value={stats.total_profit || '$0.00'} sub="Performance Tracker" color="var(--success)" />
              <StatCard label="Live Strategy" value={stats.active_bot_names || 'None'} sub={`${stats.active_bots_count || 0} active loop(s)`} color="var(--accent-color)" />
            </div>
          </>
        );

      case 'Settings':
        return (
          <div className="main-content" style={{ gap: '24px' }}>
            <section className="glass glow-shadow" style={{ padding: '32px' }}>
              <h2 style={{ marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}><Settings size={24} /> Platform Configuration</h2>

              <div style={{ display: 'grid', gap: '20px' }}>
                <div className="glass" style={{ padding: '20px', borderLeft: `4px solid ${connectionActive ? 'var(--success)' : 'var(--danger)'}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <h4 style={{ color: 'var(--text-secondary)' }}>API BRIDGE GATEWAY</h4>
                    {connectionActive ? <Wifi size={16} color="var(--success)" /> : <WifiOff size={16} color="var(--danger)" />}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <code style={{ background: 'rgba(0,0,0,0.3)', padding: '4px 8px', borderRadius: '4px', fontSize: '0.9rem', flex: 1 }}>{API_BASE}</code>
                    <a href={API_BASE} target="_blank" rel="noreferrer" className="glass" style={{ padding: '4px' }}><ExternalLink size={14} /></a>
                  </div>
                  <p style={{ fontSize: '0.75rem', marginTop: '8px', color: 'var(--text-secondary)' }}>
                    {connectionActive ? `🟢 Verified Live (Heartbeat: ${lastHeartbeat})` : '🔴 Link Blocked. We are attempting to find a public route.'}
                  </p>
                </div>

                <div className="glass" style={{ padding: '20px', borderLeft: '4px solid #5865F2' }}>
                  <h4 style={{ color: 'var(--text-secondary)', marginBottom: '12px' }}>DISCORD COMMUNITY INTEGRATION</h4>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div className="glass" style={{ padding: '8px', background: '#5865F2' }}><MessageSquare size={20} /></div>
                    <div>
                      <p style={{ fontWeight: 600 }}>Server ID: 1376908703227318393</p>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Status: Waiting for Secure API Bridge</p>
                    </div>
                  </div>
                </div>

                <div className="glass" style={{ padding: '20px', borderLeft: '4px solid #f59e0b' }}>
                  <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>USER ACCOUNT</h4>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div className="glass" style={{ width: '40px', height: '40px', background: 'linear-gradient(45deg, #00ffcc, #0099ff)', borderRadius: '50%' }}></div>
                    <p style={{ fontWeight: 600 }}>Demo Trader #1 (Global Admin)</p>
                  </div>
                </div>
              </div>
            </section>
          </div>
        );

      default:
        return (
          <div className="glass glow-shadow" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '20px', padding: '40px' }}>
            <div className="glass" style={{ padding: '24px', borderRadius: '50%', background: 'rgba(0, 255, 204, 0.05)' }}>
              <Cpu size={48} color="var(--accent-color)" />
            </div>
            <h2 style={{ fontSize: '1.5rem' }}>{activeTab} Module</h2>
            <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '400px' }}>
              Your trading engines are safe. We are currently finalizing the render for the **{activeTab}** dashboard.
            </p>
            <button onClick={() => setActiveTab('Dashboard')} className="glass" style={{ padding: '12px 32px', background: 'rgba(0, 255, 204, 0.1)', color: 'var(--accent-color)' }}>Back to Overview</button>
          </div>
        );
    }
  };

  return (
    <ErrorBoundary>
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
            {apiError && <p style={{ color: 'var(--warning)', fontSize: '0.7rem', textAlign: 'center', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}><Globe size={12} /> {apiError}</p>}
            <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.05)' }}>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>V2 ENGINE STATUS</p>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{ width: '8px', height: '8px', background: (connectionActive && status.is_running) ? 'var(--success)' : 'var(--danger)', borderRadius: '50%' }}></div>
                  <span style={{ fontSize: '0.875rem' }}>{(connectionActive && status.is_running) ? 'Bot Active' : 'Bot Idle'}</span>
                </div>
                <button
                  onClick={toggleBot}
                  disabled={loading || !connectionActive}
                  className="glass"
                  style={{ padding: '6px', borderRadius: '8px', cursor: connectionActive ? 'pointer' : 'not-allowed', background: status.is_running ? 'rgba(255, 71, 87, 0.1)' : 'rgba(0, 255, 204, 0.1)' }}
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
                placeholder="Search markets..."
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

          {renderTabContent()}
        </main>

        {/* Right Panel */}
        <aside className="right-panel">
          <section className="glass glow-shadow" style={{ padding: '24px', flex: 1, minHeight: '320px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3>Active Positions</h3>
              {positions.length > 0 && <span className="badge badge-success">{positions.length}</span>}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {connectionActive && Array.isArray(positions) && positions.length > 0 ? (
                positions.map((pos, i) => <PositionItem key={i} {...pos} />)
              ) : (
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{connectionActive ? 'No open trades found.' : 'Waiting for connection...'}</p>
              )}
            </div>
          </section>

          <section className="glass glow-shadow" style={{ padding: '24px', flex: 1, minHeight: '320px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3>Recent Activity</h3>
              <History size={20} color="var(--text-secondary)" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {connectionActive && Array.isArray(logs) && logs.length > 0 ? (
                logs.map((log, i) => <LogItem key={i} {...log} />)
              ) : (
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{connectionActive ? 'Awaiting first trade...' : 'Waiting for connection...'}</p>
              )}
            </div>
          </section>
        </aside>
      </div>
    </ErrorBoundary>
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
  const profitNum = parseFloat(profit) || 0;
  const isProfit = profitNum >= 0;
  return (
    <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.02)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontWeight: 600 }}>{symbol || 'Unknown'}</span>
        <span className={`badge ${isProfit ? 'badge-success' : 'badge-danger'}`}>{profit || '0%'}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
        <span>Entry: ${parseFloat(entry).toFixed(4)}</span>
        <span>Now: ${parseFloat(current).toFixed(4)}</span>
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
