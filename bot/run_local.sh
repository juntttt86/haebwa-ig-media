#!/bin/bash
cd "$HOME/.juntt-ig-media" || exit 1
git pull -q --ff-only 2>/dev/null
export IG_TOKEN=$(/usr/bin/python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.juntt-instagram.json')))['access_token'])")
export IG_ID=$(/usr/bin/python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.juntt-instagram.json')))['user_id'])")
date "+%F %T"
/usr/bin/python3 bot/post_queue.py
/usr/bin/python3 bot/dm_bot.py
