#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu VM (an Oracle Always Free Ampere A1 works) for Rolecall:
# Docker, firewall, swap, a .env with generated secrets, then the whole stack.
#
#   git clone https://github.com/aayushtiwari845/rolecall.git && cd rolecall
#   bash infra/bootstrap.sh https://<your-app>.vercel.app
#
# Safe to re-run: it keeps an existing .env and just rebuilds and restarts the stack.
set -euo pipefail

WEB_URL="${1:?usage: bash infra/bootstrap.sh https://<your-app>.vercel.app}"
cd "$(dirname "$0")/.."

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "==> Firewall: allow HTTP and HTTPS"
# Oracle's Ubuntu images reject everything except SSH in iptables, on top of the cloud
# security list. Insert the rules before that REJECT and keep them across reboots.
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
    reject=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
    if [ -n "$reject" ]; then
      sudo iptables -I INPUT "$reject" -p tcp --dport "$port" -j ACCEPT
    else
      sudo iptables -A INPUT -p tcp --dport "$port" -j ACCEPT
    fi
  fi
done
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent >/dev/null
sudo netfilter-persistent save >/dev/null

echo "==> Swap (headroom for image builds)"
if ! swapon --show | grep -q .; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> .env"
if [ ! -f .env ]; then
  ip=$(curl -fsS https://api.ipify.org)
  cat > .env <<EOF
ENV=production
WEB_URL=${WEB_URL%/}
# Free hostname that resolves to this VM; Caddy gets an HTTPS certificate for it.
API_DOMAIN=${ip//./-}.sslip.io
POSTGRES_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
CRAWL_USER_AGENT=RolecallBot/1.0 (+https://github.com/aayushtiwari845/rolecall)

# Google sign-in: fill these, then run: bash infra/bootstrap.sh ${WEB_URL%/}
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
# JSON list, e.g. ["you@gmail.com"]: admin dashboard access and health-check emails.
ADMIN_EMAILS=[]

# Optional: free LLM keys for the assistant and AI fit checks (any subset).
GROQ_API_KEY=
GEMINI_API_KEY=
CEREBRAS_API_KEY=
OPENROUTER_API_KEY=

# Optional: SMTP for daily digests and health alerts.
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
EOF
  chmod 600 .env
  echo "    wrote .env with generated secrets"
else
  echo "    keeping existing .env"
fi

echo "==> Build and start (the first build takes ~10 minutes)"
sudo docker compose -f infra/docker-compose.prod.yml --env-file .env up -d --build

domain=$(grep '^API_DOMAIN=' .env | cut -d= -f2)
cat <<EOF

Done. The API will answer at https://$domain/api/health once Caddy has its certificate
(about a minute). The worker starts crawling now; the first full crawl takes ~30 minutes.

Next:
  1. Vercel: set the environment variable API_URL=https://$domain and redeploy.
  2. Google sign-in: authorised redirect URI ${WEB_URL%/}/api/auth/google/callback
     Put the client id and secret in .env (nano .env), then re-run this script.
  3. Check crawling any time:  curl -s https://$domain/api/health/index
EOF
