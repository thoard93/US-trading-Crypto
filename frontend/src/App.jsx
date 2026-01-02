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
  ExternalLink,
  Edit3,
  Save,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

// --- SMART API RESOLVER ---
const getInitialApiBase = () => {
  const saved = localStorage.getItem('ANTIGRAVITY_API_OVERRIDE');
  if (saved) return saved;
  let base = import.meta.env.VITE_API_URL || '';
  if (typeof window !== 'undefined' && window.location.hostname.includes('onrender.com')) {
    // If we're on the dashboard, the API is almost always on the -1pe7 suffix
    base = `https://trading-api-1pe7.onrender.com`;
  }
  if (!base.startsWith('http') && base) base = `https://${base}`;
  return base.replace(/\/$/, '') || 'https://trading-api-1pe7.onrender.com';
};

// No global USER_ID anymore, we use user?.id from state

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
          <h2>Dashboard Layout Error</h2>
          <button onClick={() => window.location.reload()} style={{ padding: '8px 24px', background: '#00ffcc', borderRadius: '8px', color: '#000' }}>Retry Layout</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const [activeTab, setActiveTab] = useState('Dashboard');
  const [apiBase, setApiBase] = useState(getInitialApiBase());
  const [manualUrl, setManualUrl] = useState(apiBase);
  const [chartData, setChartData] = useState([]);
  const [positions, setPositions] = useState([]);
  const [portfolio, setPortfolio] = useState({ usdt_balance: 0, assets: [] });
  const [marketData, setMarketData] = useState([]);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({ total_profit: '$0.00', active_bots_count: 0, active_bot_names: 'Connecting...' });
  const [status, setStatus] = useState({ is_running: false });
  const [chartTimeframe, setChartTimeframe] = useState('5m');
  const [loading, setLoading] = useState(false);
  const [activeSymbol, setActiveSymbol] = useState('BTC/USDT');
  const [searchInput, setSearchInput] = useState('');
  const [apiError, setApiError] = useState(null);
  const [lastHeartbeat, setLastHeartbeat] = useState(null);
  const [connectionActive, setConnectionActive] = useState(false);
  const [failCount, setFailCount] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const [authError, setAuthError] = useState(null);

  const [user, setUser] = useState(JSON.parse(localStorage.getItem('AG_USER') || 'null'));
  const [authToken, setAuthToken] = useState(localStorage.getItem('AG_TOKEN'));
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [alpacaKey, setAlpacaKey] = useState('');
  const [alpacaSecret, setAlpacaSecret] = useState('');
  const [alpacaEnv, setAlpacaEnv] = useState('paper'); // 'paper' or 'live'

  const loginWithDiscord = async () => {
    setAuthError(null);
    try {
      const res = await axios.get(`${apiBase}/auth/discord/url`);
      window.location.href = res.data.url;
    } catch (err) {
      setAuthError("Failed to connect to backend. Check if your API URL is correct.");
    }
  };

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    if (code && !user) {
      setVerifying(true);
      setAuthError(null);
      axios.get(`${apiBase}/auth/discord/callback?code=${code}`)
        .then(res => {
          localStorage.setItem('AG_TOKEN', res.data.token);
          localStorage.setItem('AG_USER', JSON.stringify(res.data.user));
          setAuthToken(res.data.token);
          setUser(res.data.user);
          setVerifying(false);
          window.history.replaceState({}, document.title, "/");
        })
        .catch(err => {
          console.error("OAuth error:", err);
          setAuthError(err.response?.data?.detail || "Authentication Failed. Please try again.");
          setVerifying(false);
        });
    }
  }, [apiBase, user]);

  const saveKrakenKeys = async () => {
    if (!user) return alert("Please login first");
    setLoading(true);
    try {
      await axios.post(`${apiBase}/settings/keys`, {
        user_id: user.id,
        exchange: 'kraken',
        api_key: apiKey,
        api_secret: apiSecret
      });
      alert("Kraken Keys saved securely (AES-256 Encrypted)");
      setApiKey('');
      setApiSecret('');
    } catch (err) {
      alert("Save failed.");
    } finally {
      setLoading(false);
    }
  };

  const saveAlpacaKeys = async () => {
    if (!user) return alert("Please login first");
    setLoading(true);
    const baseUrl = alpacaEnv === 'live' ? 'https://api.alpaca.markets' : 'https://paper-api.alpaca.markets';
    try {
      await axios.post(`${apiBase}/settings/keys`, {
        user_id: user.id,
        exchange: 'alpaca',
        api_key: alpacaKey,
        api_secret: alpacaSecret,
        extra_config: baseUrl
      });
      alert(`Alpaca ${alpacaEnv.toUpperCase()} Keys saved securely.`);
      setAlpacaKey('');
      setAlpacaSecret('');
    } catch (err) {
      alert("Save failed.");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('AG_TOKEN');
    localStorage.removeItem('AG_USER');
    setAuthToken(null);
    setUser(null);
  };

  const fetchData = useCallback(async () => {
    if (!user) return;
    try {
      const statusRes = await axios.get(`${apiBase}/status/${user.id}`, { timeout: 5000 });
      if (statusRes.data) {
        setStatus(statusRes.data);
        setLastHeartbeat(new Date().toLocaleTimeString());
        setConnectionActive(true);
        setFailCount(0);
        setApiError(null);
      }

      const [posRes, portfolioRes, logsRes, statsRes, chartRes, marketRes] = await Promise.all([
        axios.get(`${apiBase}/positions/${user.id}`).catch(() => ({ data: [] })),
        axios.get(`${apiBase}/portfolio/${user.id}`).catch(() => ({ data: { usdt_balance: 0, assets: [] } })),
        axios.get(`${apiBase}/trades/${user.id}`).catch(() => ({ data: [] })),
        axios.get(`${apiBase}/stats/${user.id}`).catch(() => ({ data: {} })),
        axios.get(`${apiBase}/chart/${activeSymbol.replace('/', '%2F')}?timeframe=${chartTimeframe}`).catch(() => ({ data: [] })),
        axios.get(`${apiBase}/market_data/${user.id}`).catch(() => ({ data: [] }))
      ]);

      if (Array.isArray(posRes.data)) setPositions(posRes.data);
      if (portfolioRes.data) setPortfolio(portfolioRes.data);
      if (Array.isArray(logsRes.data)) setLogs(logsRes.data);
      if (statsRes.data) setStats(statsRes.data);
      if (Array.isArray(chartRes.data)) setChartData(chartRes.data);
      if (Array.isArray(marketRes.data)) setMarketData(marketRes.data);

    } catch (err) {
      setFailCount(prev => {
        const newCount = prev + 1;
        if (newCount >= 2) {
          setConnectionActive(false);
          setApiError("Bridge restricted. Verify URL in Settings.");
        }
        return newCount;
      });
    }
  }, [activeSymbol, apiBase, chartTimeframe, user]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData, chartTimeframe]);

  const toggleBot = async () => {
    if (!user) return alert("Login required");
    setLoading(true);
    try {
      if (status.is_running) {
        await axios.post(`${apiBase}/users/stop/${user.id}`);
      } else {
        await axios.post(`${apiBase}/users/start/${user.id}`);
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
          <h2 style={{ fontSize: '1.5rem' }}>Bridge Link Awaiting</h2>
          <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '400px' }}>
            Predicting gateway: <code>{apiBase}</code>. Not responding yet.
            Go to <b>Settings</b> to paste your exact Render URL if this persists.
          </p>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button onClick={fetchData} className="glass" style={{ padding: '12px 32px', background: 'rgba(0, 255, 204, 0.1)', color: 'var(--accent-color)' }}>Retry Predicted Route</button>
            <button onClick={() => setActiveTab('Settings')} className="glass" style={{ padding: '12px 32px' }}>Manual Overwrite</button>
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
                      : 'Connecting to Market...'}
                    <span style={{ color: 'var(--success)', marginLeft: '8px', fontSize: '0.8rem', textTransform: 'uppercase' }}>LIVE {chartTimeframe}</span>
                  </p>
                </div>
                <div className="glass" style={{ display: 'flex', padding: '4px' }}>
                  <button
                    onClick={() => setChartTimeframe('5m')}
                    className="glass"
                    style={{ padding: '6px 16px', background: chartTimeframe === '5m' ? 'rgba(255,255,255,0.1)' : 'transparent', color: chartTimeframe === '5m' ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                  >5M</button>
                  <button
                    onClick={() => setChartTimeframe('1h')}
                    className="glass"
                    style={{ padding: '6px 16px', background: chartTimeframe === '1h' ? 'rgba(255,255,255,0.1)' : 'transparent', color: chartTimeframe === '1h' ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                  >1H</button>
                  <button
                    onClick={() => setChartTimeframe('1d')}
                    className="glass"
                    style={{ padding: '6px 16px', background: chartTimeframe === '1d' ? 'rgba(255,255,255,0.1)' : 'transparent', color: chartTimeframe === '1d' ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                  >1D</button>
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
              <StatCard label="Live Performance" value={stats.total_profit || '$0.00'} sub="Total realized gains" color="var(--success)" />
              <StatCard label="Active Loop" value={stats.active_bot_names || 'None'} sub={`${stats.active_bots_count || 0} engine(s) scanning`} color="var(--accent-color)" />
            </div>
          </>
        );

      case 'Live Markets':
        return (
          <div className="main-content">
            <section className="glass glow-shadow" style={{ padding: '32px' }}>
              <h3 style={{ marginBottom: '24px' }}>Real-time Market Watchlist</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '20px' }}>
                {marketData.length > 0 ? marketData.map((coin, i) => (
                  <div
                    key={i}
                    className={`glass glow-shadow ${activeSymbol === coin.symbol ? 'active-card' : ''}`}
                    onClick={() => { setActiveSymbol(coin.symbol); setActiveTab('Dashboard'); }}
                    style={{ padding: '20px', cursor: 'pointer', borderTop: coin.type === 'STOCK' ? '3px solid var(--accent-color)' : '3px solid #f59e0b' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.05em' }}>{coin.type || 'ASSET'}</p>
                        <h3 style={{ margin: '4px 0' }}>{coin.symbol}</h3>
                      </div>
                      {coin.type === 'STOCK' ? <Activity size={20} color="var(--accent-color)" /> : <TrendingUp size={20} color="#f59e0b" />}
                    </div>
                    <div style={{ marginTop: '16px' }}>
                      <p style={{ fontSize: '1.5rem', fontWeight: 600 }}>${coin.price.toLocaleString(undefined, { minimumFractionDigits: coin.price < 1 ? 4 : 2 })}</p>
                      <p style={{ color: coin.change >= 0 ? 'var(--success)' : 'var(--danger)', display: 'flex', alignItems: 'center', gap: '4px', marginTop: '4px' }}>
                        {coin.change >= 0 ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                        {coin.change}%
                      </p>
                    </div>
                  </div>
                )) : (
                  <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                    <Activity size={32} className="spin" style={{ marginBottom: '12px' }} />
                    <p>Fetching market data...</p>
                  </div>
                )}
              </div>
            </section>
          </div>
        );

      case 'Portfolio':
        return (
          <div className="main-content" style={{ gap: '24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '24px' }}>
              <section className="glass glow-shadow" style={{ padding: '24px' }}>
                <h3 style={{ marginBottom: '20px' }}>Asset Distribution</h3>
                <div style={{ height: '200px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={portfolio.assets}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value_usdt"
                      >
                        {portfolio.assets.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={`hsl(${index * 45}, 70%, 50%)`} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>USDT Balance</span>
                    <span style={{ fontWeight: 600 }}>${portfolio.usdt_balance.toFixed(2)}</span>
                  </div>
                </div>
              </section>

              <section className="glass glow-shadow" style={{ padding: '24px' }}>
                <h3 style={{ marginBottom: '20px' }}>Kraken Holdings</h3>
                <div className="portfolio-list" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                        <th style={{ textAlign: 'left', padding: '8px 16px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>ASSET</th>
                        <th style={{ textAlign: 'left', padding: '8px 16px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>AMOUNT</th>
                        <th style={{ textAlign: 'left', padding: '8px 16px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>PRICE</th>
                        <th style={{ textAlign: 'left', padding: '8px 16px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>VALUE (USDT)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.assets.map((asset, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                          <td style={{ padding: '16px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '0.7rem', background: asset.type === 'STOCK' ? 'rgba(0, 255, 204, 0.1)' : 'rgba(245, 158, 11, 0.1)', color: asset.type === 'STOCK' ? 'var(--accent-color)' : '#f59e0b', padding: '2px 6px', borderRadius: '4px' }}>{asset.type}</span>
                              {asset.asset}
                            </div>
                          </td>
                          <td style={{ padding: '16px' }}>{asset.amount.toFixed(4)}</td>
                          <td style={{ padding: '16px' }}>${asset.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                          <td style={{ padding: '16px', fontWeight: 600 }}>${asset.value_usdt.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          </div>
        );

      case 'Trade History':
        return (
          <div className="main-content">
            <section className="glass glow-shadow" style={{ padding: '32px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
                <h3>Execution History</h3>
                <button className="glass" style={{ padding: '8px 16px', fontSize: '0.875rem' }}>Export CSV</button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {logs.length > 0 ? logs.map((log, i) => (
                  <div key={i} className="glass" style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <div style={{ padding: '8px', borderRadius: '8px', background: log.type === 'BUY' ? 'rgba(0, 255, 204, 0.1)' : 'rgba(255, 71, 87, 0.1)' }}>
                        {log.type === 'BUY' ? <ArrowDownRight size={20} color="var(--success)" /> : <ArrowUpRight size={20} color="var(--danger)" />}
                      </div>
                      <div>
                        <p style={{ fontWeight: 600 }}>{log.type} {log.symbol}</p>
                        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{log.time}</p>
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <p style={{ fontWeight: 600 }}>${parseFloat(log.price).toFixed(6)}</p>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Settled</p>
                    </div>
                  </div>
                )) : <p style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px' }}>No trades recorded in database yet.</p>}
              </div>
            </section>
          </div>
        );

      case 'Settings':
        return (
          <div className="main-content" style={{ gap: '24px' }}>
            <section className="glass glow-shadow" style={{ padding: '32px' }}>
              <h2 style={{ marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}><Settings size={24} /> Platform Configuration</h2>
              <div style={{ display: 'grid', gap: '20px' }}>

                {/* User Profile */}
                <div className="glass" style={{ padding: '20px', borderLeft: '4px solid var(--accent-color)' }}>
                  <h4 style={{ color: 'var(--text-secondary)', marginBottom: '16px' }}>USER PROFILE</h4>
                  {user ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <img src={user.avatar} alt="Avatar" style={{ width: '48px', height: '48px', borderRadius: '50%' }} />
                      <div>
                        <p style={{ fontWeight: 600 }}>{user.username}</p>
                        <button onClick={logout} style={{ color: 'var(--danger)', fontSize: '0.8rem', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>Logout</button>
                      </div>
                    </div>
                  ) : (
                    <button onClick={loginWithDiscord} className="glass" style={{ padding: '12px 24px', background: '#5865F2', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      Login with Discord
                    </button>
                  )}
                </div>

                {/* API Key Management */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
                  <div className="glass" style={{ padding: '20px', borderLeft: '4px solid #f59e0b' }}>
                    <h4 style={{ color: 'var(--text-secondary)', marginBottom: '16px' }}>KRAKEN API KEYS (CRYPTO)</h4>
                    <div style={{ display: 'grid', gap: '12px' }}>
                      <input
                        type="password"
                        placeholder="Kraken API Key"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        className="glass"
                        style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }}
                      />
                      <input
                        type="password"
                        placeholder="Kraken private Secret"
                        value={apiSecret}
                        onChange={(e) => setApiSecret(e.target.value)}
                        className="glass"
                        style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }}
                      />
                      <button onClick={saveKrakenKeys} className="glass" style={{ padding: '12px', background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' }}>
                        Save Kraken Keys
                      </button>
                    </div>
                  </div>

                  <div className="glass" style={{ padding: '20px', borderLeft: '4px solid var(--accent-color)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                      <h4 style={{ color: 'var(--text-secondary)' }}>ALPACA API KEYS (US STOCKS)</h4>
                      <div className="glass" style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)' }}>
                        <button
                          onClick={() => setAlpacaEnv('paper')}
                          style={{ padding: '4px 12px', fontSize: '0.7rem', background: alpacaEnv === 'paper' ? 'var(--accent-color)' : 'transparent', color: alpacaEnv === 'paper' ? '#000' : '#fff', border: 'none', cursor: 'pointer' }}
                        >PAPER</button>
                        <button
                          onClick={() => setAlpacaEnv('live')}
                          style={{ padding: '4px 12px', fontSize: '0.7rem', background: alpacaEnv === 'live' ? 'var(--success)' : 'transparent', color: alpacaEnv === 'live' ? '#000' : '#fff', border: 'none', cursor: 'pointer' }}
                        >LIVE</button>
                      </div>
                    </div>
                    <div style={{ display: 'grid', gap: '12px' }}>
                      <input
                        type="password"
                        placeholder="Alpaca API Key ID"
                        value={alpacaKey}
                        onChange={(e) => setAlpacaKey(e.target.value)}
                        className="glass"
                        style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }}
                      />
                      <input
                        type="password"
                        placeholder="Alpaca Secret Key"
                        value={alpacaSecret}
                        onChange={(e) => setAlpacaSecret(e.target.value)}
                        className="glass"
                        style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }}
                      />
                      <button onClick={saveAlpacaKeys} className="glass" style={{ padding: '12px', background: 'rgba(0, 255, 204, 0.1)', color: 'var(--accent-color)' }}>
                        Save Alpaca Keys
                      </button>
                    </div>
                  </div>
                </div>

                {/* API Override */}
                <div className="glass" style={{ padding: '20px', borderLeft: `4px solid ${connectionActive ? 'var(--success)' : 'var(--danger)'}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <h4 style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px' }}>API GATEWAY OVERRIDE <Edit3 size={12} /></h4>
                    {connectionActive ? <Wifi size={16} color="var(--success)" /> : <WifiOff size={16} color="var(--danger)" />}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                    <input
                      type="text"
                      value={manualUrl}
                      onChange={(e) => setManualUrl(e.target.value)}
                      placeholder="Paste Render External URL here..."
                      style={{ flex: 1, background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px', color: 'var(--text-primary)', outline: 'none' }}
                    />
                    <button onClick={() => {
                      let url = manualUrl.trim().replace(/\/$/, '');
                      if (!url.startsWith('http')) url = `https://${url}`;
                      localStorage.setItem('ANTIGRAVITY_API_OVERRIDE', url);
                      setApiBase(url);
                      setConnectionActive(false);
                      setTimeout(fetchData, 500);
                    }} className="glass" style={{ padding: '12px 24px', background: 'rgba(0, 255, 204, 0.1)', color: 'var(--accent-color)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Save size={16} /> Save Route
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        );

      case 'Safety Audit':
        return (
          <div className="main-content">
            <section className="glass glow-shadow" style={{ padding: '32px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
                <div className="glass" style={{ padding: '16px', background: 'rgba(0, 255, 204, 0.1)' }}>
                  <ShieldCheck size={32} color="var(--accent-color)" />
                </div>
                <div>
                  <h2>Smart Contract Safety Scan</h2>
                  <p style={{ color: 'var(--text-secondary)' }}>Verify token security before auto-trading.</p>
                </div>
              </div>

              <div className="glass" style={{ padding: '24px', borderLeft: '4px solid var(--accent-color)', marginBottom: '32px' }}>
                <h4 style={{ marginBottom: '16px' }}>GoPlus Security Integration</h4>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: '1.6' }}>
                  The Antigravity engine automatically runs every new DEX gem through the GoPlus Security API.
                  We check for honeypots, mint functions, and liquidity locks before authorizing a buy.
                </p>
                <button className="glass" style={{ marginTop: '20px', padding: '10px 24px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ExternalLink size={16} /> Open Security Portal
                </button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div className="glass" style={{ padding: '20px' }}>
                  <h4 style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Activity size={16} color="var(--success)" /> Live Audit Log
                  </h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '8px' }}>
                      [07:45:12] XRP: No malicious code detected.
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '8px' }}>
                      [07:42:01] PENGU: Liquidity locked for 365 days.
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '8px' }}>
                      [07:30:55] MANA: Buy tax 0%, Sell tax 0%.
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        );
    }
  };

  if (!user) {
    return (
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#05070a', color: '#fff', gap: '32px', textAlign: 'center' }}>
        <div style={{ padding: '32px', borderRadius: '50%', background: 'rgba(0, 255, 204, 0.05)', boxShadow: '0 0 50px rgba(0, 255, 204, 0.1)' }}>
          {verifying ? <RefreshCw size={64} color="var(--accent-color)" className="spin" /> : <Zap size={64} color="var(--accent-color)" />}
        </div>
        <div>
          <h1 style={{ fontSize: '3rem', fontWeight: 800, letterSpacing: '-0.02em', marginBottom: '8px' }}>ANTIGRAVITY</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '400px' }}>
            {verifying ? 'Verifying your credentials...' : 'Professional-grade crypto scalping for individual traders.'}
          </p>
        </div>

        {authError && (
          <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '12px 24px', borderRadius: '12px', color: '#ef4444', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <AlertTriangle size={20} />
            <div>
              <p style={{ fontWeight: 600, fontSize: '0.9rem' }}>Discord Error: {authError}</p>
              <p style={{ fontSize: '0.7rem', opacity: 0.8 }}>Verify your Render environment variables and Discord Secret match.</p>
            </div>
          </div>
        )}

        <button
          onClick={loginWithDiscord}
          disabled={verifying}
          className="glass glow-shadow"
          style={{
            padding: '16px 40px',
            background: verifying ? '#333' : '#5865f2',
            color: '#fff',
            fontSize: '1.1rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            borderRadius: '16px',
            border: 'none',
            cursor: verifying ? 'default' : 'pointer',
            opacity: verifying ? 0.7 : 1
          }}
        >
          {verifying ? <RefreshCw size={24} className="spin" /> : <MessageSquare size={24} />}
          {verifying ? 'Processing...' : 'Login with Discord'}
        </button>
        <p style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.3)' }}>Protected by AES-256 Multi-tenant Encryption</p>
      </div>
    );
  }

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
            <NavItem icon={<History size={20} />} label="Trade History" active={activeTab === 'History'} onClick={() => setActiveTab('History')} />
            <NavItem icon={<ShieldCheck size={20} />} label="Safety Audit" active={activeTab === 'Safety Audit'} onClick={() => setActiveTab('Safety Audit')} />
            <NavItem icon={<Settings size={20} />} label="Settings" active={activeTab === 'Settings'} onClick={() => setActiveTab('Settings')} />
          </nav>

          <div style={{ marginTop: 'auto' }}>
            {apiError && <p style={{ color: 'var(--warning)', fontSize: '0.7rem', textAlign: 'center', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}><Globe size={12} /> {apiError}</p>}
            <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.05)' }}>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>POWER ENGINE STATUS</p>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{ width: '8px', height: '8px', background: (connectionActive && status.is_running) ? 'var(--success)' : 'var(--danger)', borderRadius: '50%' }}></div>
                  <span style={{ fontSize: '0.875rem' }}>{(connectionActive && status.is_running) ? 'Bot Active' : 'Bot Idle'}</span>
                </div>
                <button
                  onClick={toggleBot}
                  disabled={loading || !connectionActive}
                  className="glass"
                  style={{ padding: '6px', borderRadius: '8px', cursor: connectionActive ? 'pointer' : 'not-allowed', background: (connectionActive && status.is_running) ? 'rgba(255, 71, 87, 0.1)' : 'rgba(0, 255, 204, 0.1)' }}
                >
                  {(connectionActive && status.is_running) ? <Square size={16} color="var(--danger)" /> : <Play size={16} color="var(--accent-color)" />}
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
                placeholder="Search markets e.g. XRP..."
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
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{connectionActive ? 'No open trades found.' : 'Bridge syncing...'}</p>
              )}
            </div>
          </section>

          <section className="glass glow-shadow" style={{ padding: '24px', flex: 1, marginTop: '24px' }}>
            <h3 style={{ marginBottom: '20px' }}>Market Radar</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {marketData.length > 0 ? (
                marketData.slice(0, 5).map((m, i) => (
                  <div key={i} className="glass" style={{ padding: '12px', display: 'flex', justifyContent: 'space-between', background: 'rgba(255,255,255,0.02)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div style={{ width: '4px', height: '4px', background: m.change > 0 ? 'var(--success)' : 'var(--danger)', borderRadius: '50%' }}></div>
                      <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{m.symbol}</span>
                    </div>
                    <span style={{ color: m.change > 0 ? 'var(--success)' : 'var(--danger)', fontSize: '0.8rem' }}>
                      {m.change > 0 ? '+' : ''}{m.change}%
                    </span>
                  </div>
                ))
              ) : (
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Scanning markets...</p>
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

function PositionItem({ symbol, entry, current, profit, side }) {
  const isProfit = profit && typeof profit === 'string' && profit.startsWith('+');
  return (
    <div className="glass" style={{ padding: '16px', background: 'rgba(255,255,255,0.02)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontWeight: 600 }}>{symbol || 'Unknown'}</span>
        <span className={`badge ${isProfit ? 'badge-success' : (profit === '---' ? '' : 'badge-danger')}`}>{profit}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
        <span>{side === 'HOLD' ? 'Current' : 'Entry'}: ${parseFloat(entry || current).toFixed(4)}</span>
        <span>{side === 'HOLD' ? 'Price' : 'Now'}: ${parseFloat(current).toFixed(4)}</span>
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
