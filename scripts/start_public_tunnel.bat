@echo off
REM Exposes the Jarvis dashboard (port 9000) to the public internet via a
REM Cloudflare Quick Tunnel. Anyone with the printed https://*.trycloudflare.com
REM URL can reach the dashboard/mobile API from any wifi/network.
REM Requires: cloudflared installed (winget install Cloudflare.cloudflared)
REM and Jarvis already running (python main.py) in another window.

cloudflared tunnel --url http://localhost:9000
