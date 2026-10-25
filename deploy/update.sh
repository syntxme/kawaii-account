#!/usr/bin/env bash
# GitHub'dagi yangi commitni olib, akkauntni qayta ishga tushiradi. Serverda cron har daqiqada chaqiradi:
#   * * * * * /root/other-bots/kawaii-account/deploy/update.sh >> /root/other-bots/kawaii-account/data/update.log 2>&1
# Server — GitHub'ning ko'zgusi: unda commit/merge qilinmaydi, faqat origin/main ga tenglashtiriladi.
# .env, *.session va data/ git'da yo'q — ularga tegilmaydi.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/.."

exec 9>/tmp/kawaii-account-update.lock
flock -n 9 || exit 0

git fetch -q origin main
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/main)
[ "$old" = "$new" ] && exit 0

git reset -q --hard origin/main
if ! git diff --quiet "$old" "$new" -- requirements.txt; then
    .venv/bin/pip install -q -r requirements.txt
fi
pm2 restart kawaii-account --update-env >/dev/null
echo "$(date '+%F %T') yangilandi: $(git log -1 --format='%h %s')"
