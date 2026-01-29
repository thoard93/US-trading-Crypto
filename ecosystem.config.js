module.exports = {
    apps: [
        {
            name: "market-sniper",
            script: "python3",
            args: "-u market_sniper.py",
            cwd: "/opt/US-trading-Crypto/backend",
            interpreter: "none",
            watch: false,
            autorestart: true,
            max_restarts: 10,
            restart_delay: 5000,
            env: {
                PYTHONUNBUFFERED: "1"
            },
            // Load .env file
            node_args: [],
            merge_logs: true,
            log_date_format: "YYYY-MM-DD HH:mm:ss",
        }
    ]
};
