#!/usr/bin/env bash
# Konfiguracja świeżego droplet-a (Ubuntu 24.04) i start aplikacji. Uruchom jako root w katalogu projektu (np. /opt/grafik):
#   bash deploy/setup.sh               # HTTP na porcie 8000 (tylko dane demo!)
#   bash deploy/setup.sh --https       # HTTPS przez Caddy i adres <IP>.sslip.io (bez własnej domeny)
#   bash deploy/setup.sh --https --demo  # j.w. + wczytaj 12 osób demo na miesiąc, na który zapisy są otwarte
#   bash deploy/setup.sh --env-only    # tylko wygeneruj .env i zakończ (nic nie instaluje)
# Zmienna PUBLIC_IP=1.2.3.4 pomija wykrywanie adresu IP serwera. Istniejący .env nie jest nadpisywany (poza kluczami trybu --https).
set -euo pipefail
cd "$(dirname "$0")/.."

HTTPS=0; DEMO=0; ENV_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --https) HTTPS=1 ;;
    --demo) DEMO=1 ;;
    --env-only) ENV_ONLY=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Nieznana opcja: $arg (dostępne: --https, --demo, --env-only)" >&2; exit 2 ;;
  esac
done

rand() { openssl rand -base64 96 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }
setenv() {  # ustaw KLUCZ=WARTOŚĆ w .env (zastąp albo dopisz)
  local k="$1" v="$2"
  if grep -q "^${k}=" .env; then
    awk -v k="$k" -v v="$v" -F= '$1==k{print k"="v; next} {print}' .env > .env.tmp && mv .env.tmp .env
  else
    echo "${k}=${v}" >> .env
  fi
  chmod 600 .env
}

# ---- adres publiczny (potrzebny tylko dla --https)
PUBLIC_IP="${PUBLIC_IP:-}"
if [ "$HTTPS" = 1 ] && [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$PUBLIC_IP" ] || { echo "Nie udało się wykryć adresu IP serwera. Podaj go: PUBLIC_IP=1.2.3.4 bash deploy/setup.sh --https" >&2; exit 1; }
fi

# ---- plik .env z losowymi sekretami (tylko gdy go jeszcze nie ma)
if [ -f .env ]; then
  echo "Plik .env już istnieje: zostawiam hasła bez zmian."
else
  umask 077
  cat > .env <<ENVEOF
POSTGRES_USER=grafik
POSTGRES_PASSWORD=$(rand 28)
POSTGRES_DB=grafik
ADMIN_LOGIN=admin
ADMIN_PASSWORD=$(rand 18)
SECRET_KEY=$(rand 64)
SESSION_HTTPS_ONLY=0
SUBMISSION_DEADLINE_DAY=10
TZ_NAME=Europe/Warsaw
LAW_ENABLED=0
WEB_BIND=0.0.0.0
ENVEOF
  echo "Wygenerowano .env z losowymi hasłami."
fi
if [ "$HTTPS" = 1 ]; then
  setenv SITE_HOST "${PUBLIC_IP//./-}.sslip.io"
  setenv SESSION_HTTPS_ONLY 1       # ciasteczko logowania tylko przez HTTPS
  setenv WEB_BIND 127.0.0.1         # aplikacja dostępna tylko przez Caddy (80/443)
fi
[ "$ENV_ONLY" = 1 ] && { echo "Tryb --env-only: gotowe."; exit 0; }

# ---- serwer: swap, Docker
[ "$(id -u)" -eq 0 ] || { echo "Uruchom jako root (np. sudo bash deploy/setup.sh)." >&2; exit 1; }
mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
if [ "$mem_mb" -lt 1900 ] && [ -z "$(swapon --show --noheadings)" ]; then
  echo "Mało pamięci (${mem_mb} MB): dodaję plik swap 2 GB."
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Instaluję Docker z repozytorium Ubuntu."
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 curl openssl
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || { echo "Brak 'docker compose'. Użyj Ubuntu 24.04 albo doinstaluj wtyczkę compose." >&2; exit 1; }

# ---- start
FILES=(-f docker-compose.yml)
[ "$HTTPS" = 1 ] && FILES+=(-f deploy/docker-compose.caddy.yml)
docker compose "${FILES[@]}" up -d --build
echo -n "Czekam na start aplikacji"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/login 2>/dev/null; then ready=1; break; fi
  echo -n "."; sleep 2
done
echo
[ "${ready:-0}" = 1 ] || { echo "Aplikacja nie wystartowała w 2 minuty. Sprawdź: docker compose logs web" >&2; exit 1; }

if [ "$DEMO" = 1 ]; then
  add=1; [ "$(date +%-d)" -gt 10 ] && add=2     # do 10. dnia: następny miesiąc, potem kolejny po nim (jak w aplikacji)
  month="$(date -d "$(date +%Y-%m-01) +${add} month" +%Y-%m)"
  docker compose exec -T web python -m app.demo --month "$month" --users 12
fi

set -a; . ./.env; set +a
echo
echo "================ GOTOWE ================"
if [ "$HTTPS" = 1 ]; then echo "Adres:        https://${SITE_HOST}   (certyfikat może pojawić się po minucie)"
else echo "Adres:        http://${PUBLIC_IP:-IP_SERWERA}:8000   (HTTP: hasła bez szyfrowania, tylko dane demo)"; fi
echo "Admin:        ${ADMIN_LOGIN} / ${ADMIN_PASSWORD}"
echo "Hasła są w pliku $(pwd)/.env (uprawnienia 600). Ogranicz dostęp w DigitalOcean Cloud Firewall."
