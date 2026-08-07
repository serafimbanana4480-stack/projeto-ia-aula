#!/bin/bash
R=/tmp/repro/result.txt
: > $R
rm -f /tmp/repro/agent_output.py
cd /tmp/repro
setsid /tmp/nx-venv/bin/uvicorn app:app --port 8844 --reload --reload-dir /tmp/repro > /tmp/repro/u4.log 2>&1 < /dev/null &
sleep 5
echo "1) arranque:          $(curl -s localhost:8844/status)" >> $R
echo "2) user manda msg:    $(curl -s -X POST localhost:8844/start)" >> $R
sleep 3
echo "3) IA a trabalhar 3s: $(curl -s localhost:8844/status)" >> $R
echo "" >> $R
echo ">>> a IA escreve um .py no workspace <<<" >> $R
echo "# gerado pelo agente" > /tmp/repro/agent_output.py
sleep 6
echo "4) logo a seguir:     $(curl -s localhost:8844/status)" >> $R
sleep 6
echo "5) +6s, IA retomou?:  $(curl -s localhost:8844/status)" >> $R
echo "" >> $R
echo "--- log uvicorn ---" >> $R
grep -iE "reload|Started server|Shutting|Stopping|detected" /tmp/repro/u4.log >> $R
