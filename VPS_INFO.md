# VPS Server Info

**SSH Command:**

```bash
ssh root@94.130.177.73
```

**Hostname:** ubuntu-4gb-nbg1-1  
**Provider:** Hetzner Cloud  
**Location:** Nuremberg, Germany (nbg1)

## Quick Commands

**Check sniper status:**

```bash
screen -r sniper
```

**Start sniper if not running:**

```bash
screen -S sniper
bash /opt/US-trading-Crypto/scripts/run_sniper.sh
# Press Ctrl+A then D to detach
```

**View logs:**

```bash
journalctl -u market-sniper -f
```
