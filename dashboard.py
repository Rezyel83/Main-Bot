mport os
import json
import base64
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import Flask, render_template_string, request, redirect, session, url_for, flash, jsonify, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ============ CONFIGURATION ============

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-secret-key-in-production')

# Discord OAuth2 Settings
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', '')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5000/callback')
DISCORD_API_BASE = 'https://discord.com/api/v10'

# Render Settings
PORT = int(os.getenv('PORT', 10000))
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

# ============ DATABASE SETUP ============

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect('dashboard.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT,
        avatar TEXT,
        access_token TEXT,
        refresh_token TEXT,
        expires_at INTEGER
    )''')
    
    # Guild Settings
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id TEXT PRIMARY KEY,
        prefix TEXT DEFAULT '?',
        welcome_channel TEXT,
        welcome_message TEXT,
        goodbye_channel TEXT,
        goodbye_message TEXT,
        autorole_id TEXT,
        modlog_channel TEXT,
        automod_enabled INTEGER DEFAULT 0,
        starboard_channel TEXT,
        suggest_channel TEXT,
        birthday_channel TEXT,
        bot_status TEXT,
        stat_channels TEXT
    )''')
    
    # Warnings
    c.execute('''CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        user_id TEXT,
        moderator_id TEXT,
        reason TEXT,
        timestamp INTEGER,
        case_id INTEGER
    )''')
    
    # Economy
    c.execute('''CREATE TABLE IF NOT EXISTS economy (
        user_id TEXT,
        guild_id TEXT,
        balance INTEGER DEFAULT 0,
        bank INTEGER DEFAULT 0,
        daily_streak INTEGER DEFAULT 0,
        last_daily INTEGER,
        reputation INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, guild_id)
    )''')
    
    # Giveaways
    c.execute('''CREATE TABLE IF NOT EXISTS giveaways (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        channel_id TEXT,
        message_id TEXT,
        prize TEXT,
        winner_count INTEGER,
        end_time INTEGER,
        ended INTEGER DEFAULT 0
    )''')
    
    # Suggestions
    c.execute('''CREATE TABLE IF NOT EXISTS suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        user_id TEXT,
        content TEXT,
        status TEXT DEFAULT 'pending',
        upvotes INTEGER DEFAULT 0,
        downvotes INTEGER DEFAULT 0
    )''')
    
    # Team Members
    c.execute('''CREATE TABLE IF NOT EXISTS team_members (
        guild_id TEXT,
        user_id TEXT,
        role TEXT,
        joined_at INTEGER,
        PRIMARY KEY (guild_id, user_id)
    )''')
    
    # Applications
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        user_id TEXT,
        content TEXT,
        status TEXT DEFAULT 'pending',
        applied_at INTEGER
    )''')
    
    # RSS Feeds
    c.execute('''CREATE TABLE IF NOT EXISTS rss_feeds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        url TEXT,
        channel_id TEXT,
        last_check INTEGER
    )''')
    
    # RL Teams
    c.execute('''CREATE TABLE IF NOT EXISTS rl_teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        name TEXT,
        tag TEXT,
        owner_id TEXT,
        created_at INTEGER,
        max_members INTEGER DEFAULT 5
    )''')
    
    # RL Team Members
    c.execute('''CREATE TABLE IF NOT EXISTS rl_team_members (
        team_id INTEGER,
        user_id TEXT,
        role TEXT DEFAULT 'member',
        joined_at INTEGER,
        PRIMARY KEY (team_id, user_id)
    )''')
    
    # Notifications
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        platform TEXT,
        username TEXT,
        channel_id TEXT,
        last_video_id TEXT
    )''')
    
    # Custom Commands
    c.execute('''CREATE TABLE IF NOT EXISTS custom_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        name TEXT,
        response TEXT,
        created_by TEXT
    )''')
    
    # Channel Permissions (NEW)
    c.execute('''CREATE TABLE IF NOT EXISTS channel_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        channel_id TEXT,
        role_id TEXT,
        allow_perms INTEGER DEFAULT 0,
        deny_perms INTEGER DEFAULT 0,
        created_at INTEGER
    )''')
    
    # Role Presets (NEW)
    c.execute('''CREATE TABLE IF NOT EXISTS role_presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        preset_name TEXT,
        role_id TEXT,
        permissions TEXT,  -- JSON array of permission names
        created_at INTEGER
    )''')
    
    # Dashboard Logs
    c.execute('''CREATE TABLE IF NOT EXISTS dashboard_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT,
        user_id TEXT,
        action TEXT,
        details TEXT,
        timestamp INTEGER
    )''')
    
    conn.commit()
    conn.close()

# ============ KEEP ALIVE ============

def keep_alive():
    """Keep the Render instance alive"""
    def ping_self():
        while True:
            time.sleep(300)  # Every 5 minutes
            if RENDER_EXTERNAL_URL:
                try:
                    requests.get(f"{RENDER_EXTERNAL_URL}/ping", timeout=10)
                    print(f"[Keep-Alive] Ping successful at {datetime.now()}")
                except Exception as e:
                    print(f"[Keep-Alive] Ping failed: {e}")
    
    thread = threading.Thread(target=ping_self, daemon=True)
    thread.start()

@app.route('/ping')
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

# ============ DISCORD API HELPERS ============

def discord_api_request(endpoint, method='GET', data=None, token=None, bot=False):
    """Make a request to the Discord API"""
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'DiscordBot (Dashboard, 1.0)'
    }
    
    if bot:
        headers['Authorization'] = f'Bot {DISCORD_BOT_TOKEN}'
    elif token:
        headers['Authorization'] = f'Bearer {token}'
    else:
        return None
    
    url = f"{DISCORD_API_BASE}{endpoint}"
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data)
        elif method == 'PATCH':
            response = requests.patch(url, headers=headers, json=data)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers)
        elif method == 'PUT':
            response = requests.put(url, headers=headers, json=data)
        else:
            return None
        
        if response.status_code in [200, 201, 204]:
            return response.json() if response.content else True
        else:
            print(f"Discord API Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Request Error: {e}")
        return None

def get_user_guilds(access_token):
    """Get user's guilds from Discord"""
    return discord_api_request('/users/@me/guilds', token=access_token) or []

def get_bot_guilds():
    """Get guilds the bot is in"""
    return discord_api_request('/users/@me/guilds', bot=True) or []

def get_guild(guild_id):
    """Get guild info"""
    return discord_api_request(f'/guilds/{guild_id}', bot=True)

def get_guild_channels(guild_id):
    """Get guild channels"""
    return discord_api_request(f'/guilds/{guild_id}/channels', bot=True) or []

def get_guild_roles(guild_id):
    """Get guild roles"""
    return discord_api_request(f'/guilds/{guild_id}/roles', bot=True) or []

def update_channel_permissions(guild_id, channel_id, overwrite_id, allow, deny, type=0):
    """Update channel permissions"""
    data = {
        "allow": str(allow),
        "deny": str(deny),
        "type": type  # 0 = role, 1 = member
    }
    return discord_api_request(
        f'/channels/{channel_id}/permissions/{overwrite_id}',
        method='PUT',
        data=data,
        bot=True
    )

# ============ PERMISSION BITS ============

PERMISSION_BITS = {
    'CREATE_INSTANT_INVITE': 0x00000001,
    'KICK_MEMBERS': 0x00000002,
    'BAN_MEMBERS': 0x00000004,
    'ADMINISTRATOR': 0x00000008,
    'MANAGE_CHANNELS': 0x00000010,
    'MANAGE_GUILD': 0x00000020,
    'ADD_REACTIONS': 0x00000040,
    'VIEW_AUDIT_LOG': 0x00000080,
    'PRIORITY_SPEAKER': 0x00000100,
    'STREAM': 0x00000200,
    'VIEW_CHANNEL': 0x00000400,
    'SEND_MESSAGES': 0x00000800,
    'SEND_TTS_MESSAGES': 0x00001000,
    'MANAGE_MESSAGES': 0x00002000,
    'EMBED_LINKS': 0x00004000,
    'ATTACH_FILES': 0x00008000,
    'READ_MESSAGE_HISTORY': 0x00010000,
    'MENTION_EVERYONE': 0x00020000,
    'USE_EXTERNAL_EMOJIS': 0x00040000,
    'VIEW_GUILD_INSIGHTS': 0x00080000,
    'CONNECT': 0x00100000,
    'SPEAK': 0x00200000,
    'MUTE_MEMBERS': 0x00400000,
    'DEAFEN_MEMBERS': 0x00800000,
    'MOVE_MEMBERS': 0x01000000,
    'USE_VAD': 0x02000000,
    'CHANGE_NICKNAME': 0x04000000,
    'MANAGE_NICKNAMES': 0x08000000,
    'MANAGE_ROLES': 0x10000000,
    'MANAGE_WEBHOOKS': 0x20000000,
    'MANAGE_GUILD_EXPRESSIONS': 0x40000000,
    'USE_APPLICATION_COMMANDS': 0x80000000,
    'REQUEST_TO_SPEAK': 0x0100000000,
    'MANAGE_EVENTS': 0x0200000000,
    'MANAGE_THREADS': 0x0400000000,
    'CREATE_PUBLIC_THREADS': 0x0800000000,
    'CREATE_PRIVATE_THREADS': 0x1000000000,
    'USE_EXTERNAL_STICKERS': 0x2000000000,
    'SEND_MESSAGES_IN_THREADS': 0x4000000000,
    'USE_EMBEDDED_ACTIVITIES': 0x8000000000,
    'MODERATE_MEMBERS': 0x0000010000000000,
    'VIEW_CREATOR_MONETIZATION_ANALYTICS': 0x0000020000000000,
    'USE_SOUNDBOARD': 0x0000040000000000,
    'CREATE_GUILD_EXPRESSIONS': 0x0000080000000000,
    'CREATE_EVENTS': 0x0000100000000000,
    'USE_EXTERNAL_SOUNDS': 0x0000200000000000,
    'SEND_VOICE_MESSAGES': 0x0000400000000000
}

# ============ AUTH DECORATORS ============

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def guild_access_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        guild_id = kwargs.get('guild_id')
        if not guild_id:
            return redirect(url_for('dashboard'))
        
        # Check if user has access to this guild
        user_guilds = get_user_guilds(session.get('access_token'))
        bot_guilds = get_bot_guilds()
        bot_guild_ids = {g['id'] for g in bot_guilds}
        
        user_guild = next((g for g in user_guilds if g['id'] == guild_id), None)
        if not user_guild:
            flash('You do not have access to this server', 'error')
            return redirect(url_for('dashboard'))
        
        if guild_id not in bot_guild_ids:
            flash('Bot is not in this server', 'error')
            return redirect(url_for('dashboard'))
        
        # Check for admin permissions (0x8 = ADMINISTRATOR, 0x20 = MANAGE_GUILD)
        permissions = int(user_guild.get('permissions', 0))
        if not (permissions & 0x8 or permissions & 0x20):
            flash('You need Administrator or Manage Server permissions', 'error')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

# ============ DATABASE HELPERS ============

def get_db():
    conn = sqlite3.connect('dashboard.db')
    conn.row_factory = sqlite3.Row
    return conn

def log_action(guild_id, user_id, action, details=''):
    """Log a dashboard action"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO dashboard_logs (guild_id, user_id, action, details, timestamp)
                 VALUES (?, ?, ?, ?, ?)''',
              (guild_id, user_id, action, details, int(time.time())))
    conn.commit()
    conn.close()

# ============ HTML TEMPLATES ============

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Renthol Dashboard{% endblock %}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --primary: #ef4444;
            --primary-dark: #dc2626;
            --primary-light: #f87171;
            --bg-primary: #0f0f0f;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #262626;
            --text-primary: #ffffff;
            --text-secondary: #a1a1aa;
            --accent-green: #22c55e;
            --accent-yellow: #eab308;
            --accent-blue: #3b82f6;
            --border-color: #404040;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        @keyframes slideIn {
            from { transform: translateX(-100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        @keyframes pulse-glow {
            0%, 100% { box-shadow: 0 0 20px rgba(239, 68, 68, 0.3); }
            50% { box-shadow: 0 0 40px rgba(239, 68, 68, 0.6); }
        }
        
        @keyframes gradient-shift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        
        .animate-fade { animation: fadeIn 0.5s ease; }
        .animate-slide { animation: slideIn 0.3s ease; }
        
        /* Navigation */
        .navbar {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--primary);
        }
        
        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            animation: pulse-glow 2s infinite;
        }
        
        .nav-user {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .user-avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 2px solid var(--primary);
        }
        
        /* Sidebar */
        .container {
            display: flex;
            min-height: calc(100vh - 73px);
        }
        
        .sidebar {
            width: 280px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border-color);
            padding: 1.5rem;
        }
        
        .sidebar-section {
            margin-bottom: 1.5rem;
        }
        
        .sidebar-title {
            font-size: 0.75rem;
            text-transform: uppercase;
            color: var(--text-secondary);
            margin-bottom: 0.75rem;
            letter-spacing: 0.05em;
        }
        
        .sidebar-link {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.75rem 1rem;
            color: var(--text-secondary);
            text-decoration: none;
            border-radius: 8px;
            margin-bottom: 0.25rem;
            transition: all 0.2s;
        }
        
        .sidebar-link:hover, .sidebar-link.active {
            background: rgba(239, 68, 68, 0.1);
            color: var(--primary);
        }
        
        .sidebar-link i {
            width: 20px;
            text-align: center;
        }
        
        /* Main Content */
        .main-content {
            flex: 1;
            padding: 2rem;
            overflow-y: auto;
        }
        
        .page-header {
            margin-bottom: 2rem;
        }
        
        .page-title {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        .page-subtitle {
            color: var(--text-secondary);
        }
        
        /* Cards */
        .card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            animation: fadeIn 0.3s ease;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
        }
        
        .card-title {
            font-size: 1.125rem;
            font-weight: 600;
        }
        
        /* Buttons */
        .btn {
            padding: 0.625rem 1.25rem;
            border-radius: 8px;
            font-weight: 500;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            transition: all 0.2s;
            text-decoration: none;
        }
        
        .btn-primary {
            background: var(--primary);
            color: white;
        }
        
        .btn-primary:hover {
            background: var(--primary-dark);
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
        }
        
        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }
        
        .btn-secondary:hover {
            background: var(--border-color);
        }
        
        .btn-success {
            background: var(--accent-green);
            color: white;
        }
        
        .btn-danger {
            background: #dc2626;
            color: white;
        }
        
        .btn-sm {
            padding: 0.375rem 0.75rem;
            font-size: 0.875rem;
        }
        
        /* Forms */
        .form-group {
            margin-bottom: 1.25rem;
        }
        
        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: var(--text-secondary);
        }
        
        .form-input, .form-select, .form-textarea {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.875rem;
            transition: all 0.2s;
        }
        
        .form-input:focus, .form-select:focus, .form-textarea:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
        }
        
        .form-textarea {
            min-height: 100px;
            resize: vertical;
        }
        
        /* Tables */
        .data-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .data-table th {
            text-align: left;
            padding: 0.875rem 1rem;
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid var(--border-color);
        }
        
        .data-table td {
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        .data-table tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
            animation: fadeIn 0.3s ease;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: linear-gradient(90deg, var(--primary), var(--primary-dark));
        }
        
        .stat-value {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }
        
        .stat-label {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        
        /* Server Cards */
        .servers-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1.5rem;
        }
        
        .server-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            text-decoration: none;
            color: inherit;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .server-card:hover {
            transform: translateY(-4px);
            border-color: var(--primary);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
        }
        
        .server-card::after {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 100px;
            height: 100px;
            background: radial-gradient(circle, var(--primary) 0%, transparent 70%);
            opacity: 0.1;
            transition: opacity 0.3s;
        }
        
        .server-card:hover::after {
            opacity: 0.2;
        }
        
        .server-icon {
            width: 64px;
            height: 64px;
            border-radius: 16px;
            background: var(--bg-tertiary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 1rem;
            border: 2px solid var(--border-color);
        }
        
        .server-name {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }
        
        .server-stats {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        
        .server-badge {
            position: absolute;
            top: 1rem;
            right: 1rem;
            background: var(--accent-green);
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        
        /* Login Page */
        .login-container {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, var(--bg-primary) 0%, #1a0f0f 100%);
        }
        
        .login-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 3rem;
            text-align: center;
            max-width: 420px;
            width: 90%;
            animation: fadeIn 0.5s ease;
        }
        
        .login-logo {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            border-radius: 20px;
            margin: 0 auto 1.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            animation: pulse-glow 2s infinite;
        }
        
        .login-title {
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        .login-subtitle {
            color: var(--text-secondary);
            margin-bottom: 2rem;
        }
        
        .discord-btn {
            background: #5865F2;
            color: white;
            width: 100%;
            justify-content: center;
            padding: 1rem;
            font-size: 1rem;
            border-radius: 12px;
        }
        
        .discord-btn:hover {
            background: #4752C4;
        }
        
        /* Permission Editor */
        .perm-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        
        .perm-item {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .perm-state {
            display: flex;
            gap: 0.5rem;
        }
        
        .perm-btn {
            width: 32px;
            height: 32px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.75rem;
            transition: all 0.2s;
        }
        
        .perm-btn.allow {
            background: rgba(34, 197, 94, 0.2);
            color: var(--accent-green);
        }
        
        .perm-btn.allow.active {
            background: var(--accent-green);
            color: white;
        }
        
        .perm-btn.deny {
            background: rgba(220, 38, 38, 0.2);
            color: #dc2626;
        }
        
        .perm-btn.deny.active {
            background: #dc2626;
            color: white;
        }
        
        .perm-btn.neutral {
            background: rgba(161, 161, 170, 0.2);
            color: var(--text-secondary);
        }
        
        .perm-btn.neutral.active {
            background: var(--text-secondary);
            color: white;
        }
        
        /* Preset Cards */
        .preset-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        
        .preset-card {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .preset-card:hover {
            border-color: var(--primary);
        }
        
        .preset-card.selected {
            border-color: var(--primary);
            background: rgba(239, 68, 68, 0.1);
        }
        
        .preset-name {
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        
        .preset-desc {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
        
        /* Status badges */
        .badge {
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        
        .badge-success { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }
        .badge-warning { background: rgba(234, 179, 8, 0.2); color: var(--accent-yellow); }
        .badge-danger { background: rgba(220, 38, 38, 0.2); color: #dc2626; }
        .badge-info { background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); }
        
        /* Mobile */
        @media (max-width: 768px) {
            .sidebar {
                width: 100%;
                position: fixed;
                bottom: 0;
                left: 0;
                z-index: 99;
                display: flex;
                overflow-x: auto;
                padding: 0.5rem;
            }
            
            .sidebar-section { display: none; }
            .container { flex-direction: column; }
            .main-content { padding: 1rem; padding-bottom: 100px; }
            
            .stats-grid { grid-template-columns: 1fr; }
            .servers-grid { grid-template-columns: 1fr; }
        }
        
        /* Alerts */
        .alert {
            padding: 1rem 1.25rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        
        .alert-success {
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid rgba(34, 197, 94, 0.3);
            color: var(--accent-green);
        }
        
        .alert-error {
            background: rgba(220, 38, 38, 0.1);
            border: 1px solid rgba(220, 38, 38, 0.3);
            color: #dc2626;
        }
        
        /* Tabs */
        .tabs {
            display: flex;
            gap: 0.5rem;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 1.5rem;
        }
        
        .tab {
            padding: 0.75rem 1.25rem;
            color: var(--text-secondary);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        
        .tab:hover { color: var(--text-primary); }
        .tab.active {
            color: var(--primary);
            border-bottom-color: var(--primary);
        }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        /* Loading */
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    {% block content %}{% endblock %}
    
    <script>
        // Tab functionality
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const parent = tab.closest('.tabs-container');
                parent.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                parent.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.target).classList.add('active');
            });
        });
        
        // Permission toggle functionality
        function setPerm(permName, state) {
            const btnGroup = document.querySelector(`[data-perm="${permName}"]`);
            btnGroup.querySelectorAll('.perm-btn').forEach(btn => btn.classList.remove('active'));
            btnGroup.querySelector(`.perm-btn.${state}`).classList.add('active');
        }
        
        // Copy to clipboard
        function copy(text) {
            navigator.clipboard.writeText(text);
        }
    </script>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}Login - Renthol Dashboard{% endblock %}

{% block content %}
<div class="login-container">
    <div class="login-card">
        <div class="login-logo">🤖</div>
        <h1 class="login-title">Willkommen zurück</h1>
        <p class="login-subtitle">Melde dich mit Discord an, um deine Server zu verwalten</p>
        <a href="{{ auth_url }}" class="btn discord-btn">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
            </svg>
            Mit Discord anmelden
        </a>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}" style="margin-top: 1rem;">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
    </div>
</div>
{% endblock %}
'''

DASHBOARD_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}Dashboard - Renthol{% endblock %}

{% block content %}
<nav class="navbar">
    <div class="logo">
        <div class="logo-icon">🤖</div>
        <span>Renthol Dashboard</span>
    </div>
    <div class="nav-user">
        <span>{{ user.username }}#{{ user.discriminator }}</span>
        <a href="{{ url_for('logout') }}" class="btn btn-secondary btn-sm">Abmelden</a>
    </div>
</nav>

<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Server auswählen</div>
            <div style="padding: 0 1rem; color: var(--text-secondary); font-size: 0.875rem;">
                Wähle einen Server aus der Liste unten
            </div>
        </div>
    </aside>
    
    <main class="main-content">
        <div class="page-header">
            <h1 class="page-title">Deine Server</h1>
            <p class="page-subtitle">Wähle einen Server, um das Dashboard zu öffnen</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{{ total_guilds }}</div>
                <div class="stat-label">Server mit Bot</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ manageable_guilds }}</div>
                <div class="stat-label">Verwaltbar</div>
            </div>
        </div>
        
        <div class="servers-grid">
            {% for guild in guilds %}
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="server-card">
                <span class="server-badge">Geöffnet</span>
                <div class="server-icon">{{ guild.name[:2] }}</div>
                <div class="server-name">{{ guild.name }}</div>
                <div class="server-stats">{{ guild.member_count|default('?') }} Mitglieder</div>
            </a>
            {% endfor %}
            
            <a href="https://discord.com/api/oauth2/authorize?client_id={{ client_id }}&permissions=8&scope=bot%20applications.commands" target="_blank" class="server-card" style="border-style: dashed; opacity: 0.7;">
                <div class="server-icon" style="background: transparent; border: 2px dashed var(--border-color);">+</div>
                <div class="server-name">Bot hinzufügen</div>
                <div class="server-stats">Zu einem neuen Server einladen</div>
            </a>
        </div>
    </main>
</div>
{% endblock %}
'''

GUILD_DASHBOARD_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}{{ guild.name }} - Renthol Dashboard{% endblock %}

{% block content %}
<nav class="navbar">
    <div class="logo">
        <div class="logo-icon">🤖</div>
        <span>{{ guild.name }}</span>
    </div>
    <div class="nav-user">
        <span>{{ user.username }}</span>
        <a href="{{ url_for('dashboard') }}" class="btn btn-secondary btn-sm">Zurück</a>
        <a href="{{ url_for('logout') }}" class="btn btn-secondary btn-sm">Abmelden</a>
    </div>
</nav>

<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Hauptmenü</div>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link active">
                <span>📊</span> Übersicht
            </a>
            <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link">
                <span>🛡️</span> Moderation
            </a>
            <a href="{{ url_for('economy', guild_id=guild.id) }}" class="sidebar-link">
                <span>💰</span> Economy
            </a>
            <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="sidebar-link">
                <span>🔐</span> Channel-Rechte
            </a>
            <a href="{{ url_for('giveaways', guild_id=guild.id) }}" class="sidebar-link">
                <span>🎁</span> Giveaways
            </a>
            <a href="{{ url_for('suggestions', guild_id=guild.id) }}" class="sidebar-link">
                <span>💡</span> Vorschläge
            </a>
            <a href="{{ url_for('team', guild_id=guild.id) }}" class="sidebar-link">
                <span>👥</span> Team
            </a>
            <a href="{{ url_for('applications', guild_id=guild.id) }}" class="sidebar-link">
                <span>📝</span> Bewerbungen
            </a>
            <a href="{{ url_for('rss', guild_id=guild.id) }}" class="sidebar-link">
                <span>📰</span> RSS Feeds
            </a>
            <a href="{{ url_for('rl_teams', guild_id=guild.id) }}" class="sidebar-link">
                <span>🎮</span> RL Teams
            </a>
            <a href="{{ url_for('notifications', guild_id=guild.id) }}" class="sidebar-link">
                <span>🔔</span> Notifications
            </a>
            <a href="{{ url_for('modlogs', guild_id=guild.id) }}" class="sidebar-link">
                <span>📋</span> Mod Logs
            </a>
            <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">
                <span>⚙️</span> Einstellungen
            </a>
        </div>
    </aside>
    
    <main class="main-content">
        <div class="page-header">
            <h1 class="page-title">Übersicht</h1>
            <p class="page-subtitle">Statistiken und Informationen für {{ guild.name }}</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{{ stats.member_count|default('?') }}</div>
                <div class="stat-label">Mitglieder</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.channel_count|default('?') }}</div>
                <div class="stat-label">Channels</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.role_count|default('?') }}</div>
                <div class="stat-label">Rollen</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.warning_count }}</div>
                <div class="stat-label">Verwarnungen</div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Schnellzugriff</h3>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="btn btn-primary">Warns verwalten</a>
                <a href="{{ url_for('economy', guild_id=guild.id) }}" class="btn btn-primary">Coins bearbeiten</a>
                <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="btn btn-primary">Channel-Rechte</a>
                <a href="{{ url_for('settings', guild_id=guild.id) }}" class="btn btn-secondary">Einstellungen</a>
            </div>
        </div>
    </main>
</div>
{% endblock %}
'''

MODERATION_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}Moderation - {{ guild.name }}{% endblock %}

{% block content %}
<nav class="navbar">
    <div class="logo">
        <div class="logo-icon">🤖</div>
        <span>{{ guild.name }}</span>
    </div>
    <div class="nav-user">
        <span>{{ user.username }}</span>
        <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
        <a href="{{ url_for('logout') }}" class="btn btn-secondary btn-sm">Abmelden</a>
    </div>
</nav>

<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Hauptmenü</div>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
            <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link active">🛡️ Moderation</a>
            <a href="{{ url_for('economy', guild_id=guild.id) }}" class="sidebar-link">💰 Economy</a>
            <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="sidebar-link">🔐 Channel-Rechte</a>
            <a href="{{ url_for('giveaways', guild_id=guild.id) }}" class="sidebar-link">🎁 Giveaways</a>
            <a href="{{ url_for('suggestions', guild_id=guild.id) }}" class="sidebar-link">💡 Vorschläge</a>
            <a href="{{ url_for('team', guild_id=guild.id) }}" class="sidebar-link">👥 Team</a>
            <a href="{{ url_for('applications', guild_id=guild.id) }}" class="sidebar-link">📝 Bewerbungen</a>
            <a href="{{ url_for('rss', guild_id=guild.id) }}" class="sidebar-link">📰 RSS Feeds</a>
            <a href="{{ url_for('modlogs', guild_id=guild.id) }}" class="sidebar-link">📋 Mod Logs</a>
            <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">⚙️ Einstellungen</a>
        </div>
    </aside>
    
    <main class="main-content">
        <div class="page-header">
            <h1 class="page-title">Moderation</h1>
            <p class="page-subtitle">Verwarnungen verwalten und durchsuchen</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Verwarnung suchen</h3>
            </div>
            <form method="GET" action="{{ url_for('moderation', guild_id=guild.id) }}" style="display: flex; gap: 1rem;">
                <input type="text" name="search" class="form-input" placeholder="User ID oder Name..." value="{{ request.args.get('search', '') }}">
                <button type="submit" class="btn btn-primary">Suchen</button>
            </form>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Verwarnungen</h3>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Case ID</th>
                        <th>User</th>
                        <th>Moderator</th>
                        <th>Grund</th>
                        <th>Datum</th>
                        <th>Aktionen</th>
                    </tr>
                </thead>
                <tbody>
                    {% for warn in warnings %}
                    <tr>
                        <td>#{{ warn.case_id }}</td>
                        <td>{{ warn.user_id }}</td>
                        <td>{{ warn.moderator_id }}</td>
                        <td>{{ warn.reason[:50] }}{% if warn.reason|length > 50 %}...{% endif %}</td>
                        <td>{{ warn.timestamp }}</td>
                        <td>
                            <form method="POST" action="{{ url_for('delete_warn', guild_id=guild.id, warn_id=warn.id) }}" style="display: inline;">
                                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Verwarnung löschen?')">🗑️</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="6" style="text-align: center; color: var(--text-secondary);">Keine Verwarnungen gefunden</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </main>
</div>
{% endblock %}
'''

ECONOMY_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}Economy - {{ guild.name }}{% endblock %}

{% block content %}
<nav class="navbar">
    <div class="logo">
        <div class="logo-icon">🤖</div>
        <span>{{ guild.name }}</span>
    </div>
    <div class="nav-user">
        <span>{{ user.username }}</span>
        <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
        <a href="{{ url_for('logout') }}" class="btn btn-secondary btn-sm">Abmelden</a>
    </div>
</nav>

<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Hauptmenü</div>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
            <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link">🛡️ Moderation</a>
            <a href="{{ url_for('economy', guild_id=guild.id) }}" class="sidebar-link active">💰 Economy</a>
            <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="sidebar-link">🔐 Channel-Rechte</a>
            <a href="{{ url_for('giveaways', guild_id=guild.id) }}" class="sidebar-link">🎁 Giveaways</a>
            <a href="{{ url_for('suggestions', guild_id=guild.id) }}" class="sidebar-link">💡 Vorschläge</a>
            <a href="{{ url_for('team', guild_id=guild.id) }}" class="sidebar-link">👥 Team</a>
            <a href="{{ url_for('applications', guild_id=guild.id) }}" class="sidebar-link">📝 Bewerbungen</a>
            <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">⚙️ Einstellungen</a>
        </div>
    </aside>
    
    <main class="main-content">
        <div class="page-header">
            <h1 class="page-title">Economy</h1>
            <p class="page-subtitle">Leaderboard und Coins verwalten</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwt# MEINTE: endwith %}
        
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">User Coins bearbeiten</h3>
            </div>
            <form method="POST" action="{{ url_for('economy', guild_id=guild.id) }}">
                <div style="display: grid; grid-template-columns: 1fr 1fr auto; gap: 1rem;">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label">User ID</label>
                        <input type="text" name="user_id" class="form-input" required>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label">Neuer Betrag</label>
                        <input type="number" name="amount" class="form-input" required>
                    </div>
                    <button type="submit" class="btn btn-primary" style="align-self: flex-end;">Speichern</button>
                </div>
            </form>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Leaderboard</h3>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>User</th>
                        <th>Balance</th>
                        <th>Bank</th>
                        <th>Rep</th>
                    </tr>
                </thead>
                <tbody>
                    {% for entry in leaderboard %}
                    <tr>
                        <td>#{{ loop.index }}</td>
                        <td>{{ entry.user_id }}</td>
                        <td>{{ entry.balance }} 💰</td>
                        <td>{{ entry.bank }} 🏦</td>
                        <td>{{ entry.reputation }} ⭐</td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="5" style="text-align: center; color: var(--text-secondary);">Keine Economy-Daten</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </main>
</div>
{% endblock %}
'''

# ============ CHANNEL PERMISSIONS TEMPLATE (NEW FEATURE) ============

CHANNEL_PERMISSIONS_TEMPLATE = '''
{% extends "base.html" %}

{% block title %}Channel-Rechte - {{ guild.name }}{% endblock %}

{% block content %}
<nav class="navbar">
    <div class="logo">
        <div class="logo-icon">🤖</div>
        <span>{{ guild.name }}</span>
    </div>
    <div class="nav-user">
        <span>{{ user.username }}</span>
        <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
        <a href="{{ url_for('logout') }}" class="btn btn-secondary btn-sm">Abmelden</a>
    </div>
</nav>

<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Hauptmenü</div>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
            <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link">🛡️ Moderation</a>
            <a href="{{ url_for('economy', guild_id=guild.id) }}" class="sidebar-link">💰 Economy</a>
            <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="sidebar-link active">🔐 Channel-Rechte</a>
            <a href="{{ url_for('giveaways', guild_id=guild.id) }}" class="sidebar-link">🎁 Giveaways</a>
            <a href="{{ url_for('suggestions', guild_id=guild.id) }}" class="sidebar-link">💡 Vorschläge</a>
            <a href="{{ url_for('team', guild_id=guild.id) }}" class="sidebar-link">👥 Team</a>
            <a href="{{ url_for('applications', guild_id=guild.id) }}" class="sidebar-link">📝 Bewerbungen</a>
            <a href="{{ url_for('rss', guild_id=guild.id) }}" class="sidebar-link">📰 RSS Feeds</a>
            <a href="{{ url_for('rl_teams', guild_id=guild.id) }}" class="sidebar-link">🎮 RL Teams</a>
            <a href="{{ url_for('notifications', guild_id=guild.id) }}" class="sidebar-link">🔔 Notifications</a>
            <a href="{{ url_for('modlogs', guild_id=guild.id) }}" class="sidebar-link">📋 Mod Logs</a>
            <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">⚙️ Einstellungen</a>
        </div>
    </aside>
    
    <main class="main-content">
        <div class="page-header">
            <h1 class="page-title">Channel-Rechte</h1>
            <p class="page-subtitle">Berechtigungen für Channels und Rollen verwalten</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <!-- Presets Section -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">🔖 Rollen-Presets</h3>
                <button class="btn btn-primary btn-sm" onclick="document.getElementById('preset-modal').style.display='block'">+ Preset erstellen</button>
            </div>
            <div class="preset-grid">
                {% for preset in presets %}
                <div class="preset-card" onclick="applyPreset({{ preset.id }})">
                    <div class="preset-name">{{ preset.preset_name }}</div>
                    <div class="preset-desc">{{ preset.permissions|length }} Berechtigungen</div>
                </div>
                {% else %}
                <div style="color: var(--text-secondary); padding: 1rem;">Keine Presets erstellt</div>
                {% endfor %}
            </div>
        </div>
        
        <!-- Channel Selection -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">📁 Channel auswählen</h3>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                <div>
                    <label class="form-label">Kategorie</label>
                    <select class="form-select" onchange="filterChannels(this.value)">
                        <option value="">Alle Channels</option>
                        {% for category in categories %}
                        <option value="{{ category.id }}">{{ category.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label class="form-label">Channel</label>
                    <select class="form-select" id="channel-select" onchange="loadChannelPerms(this.value)">
                        <option value="">Channel wählen...</option>
                        {% for channel in channels %}
                        <option value="{{ channel.id }}" data-category="{{ channel.parent_id or '' }}">{{ channel.name }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
        </div>
        
        <!-- Permission Editor -->
        <div class="card" id="perm-editor" style="display: none;">
            <div class="card-header">
                <h3 class="card-title">🔐 Berechtigungen bearbeiten</h3>
                <select class="form-select" style="width: auto;" onchange="loadRolePerms(this.value)">
                    <option value="">Rolle wählen...</option>
                    {% for role in roles %}
                    <option value="{{ role.id }}">{{ role.name }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <form id="perm-form" method="POST" action="{{ url_for('save_channel_permissions', guild_id=guild.id) }}">
                <input type="hidden" name="channel_id" id="perm-channel-id">
                <input type="hidden" name="role_id" id="perm-role-id">
                <input type="hidden" name="permissions" id="perm-data">
                
                <div class="perm-grid" id="perm-list">
                    {% for perm_name, perm_value in permission_bits.items() %}
                    <div class="perm-item">
                        <span>{{ perm_name.replace('_', ' ').title() }}</span>
                        <div class="perm-state" data-perm="{{ perm_name }}">
                            <button type="button" class="perm-btn allow" onclick="setPermState('{{ perm_name }}', 'allow')">✓</button>
                            <button type="button" class="perm-btn neutral active" onclick="setPermState('{{ perm_name }}', 'neutral')">−</button>
                            <button type="button" class="perm-btn deny" onclick="setPermState('{{ perm_name }}', 'deny')">✕</button>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                
                <div style="margin-top: 1.5rem; display: flex; gap: 1rem;">
                    <button type="submit" class="btn btn-primary">💾 Speichern</button>
                    <button type="button" class="btn btn-secondary" onclick="saveAsPreset()">🔖 Als Preset speichern</button>
                    <button type="button" class="btn btn-danger" onclick="resetPerms()">🔄 Zurücksetzen</button>
                </div>
            </form>
        </div>
        
        <!-- Current Permissions Overview -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">📋 Aktuelle Berechtigungen</h3>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Channel</th>
                        <th>Rolle</th>
                        <th>Erlaubt</th>
                        <th>Verweigert</th>
                        <th>Aktionen</th>
                    </tr>
                </thead>
                <tbody>
                    {% for perm in saved_permissions %}
                    <tr>
                        <td>{{ perm.channel_name }}</td>
                        <td>{{ perm.role_name }}</td>
                        <td><span class="badge badge-success">{{ perm.allow_count }}</span></td>
                        <td><span class="badge badge-danger">{{ perm.deny_count }}</span></td>
                        <td>
                            <form method="POST" action="{{ url_for('delete_channel_permission', guild_id=guild.id, perm_id=perm.id) }}" style="display: inline;">
                                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Löschen?')">🗑️</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="5" style="text-align: center; color: var(--text-secondary);">Keine gespeicherten Berechtigungen</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </main>
</div>

<!-- Preset Modal -->
<div id="preset-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; align-items: center; justify-content: center;">
    <div class="card" style="max-width: 500px; width: 90%;">
        <div class="card-header">
            <h3 class="card-title">Preset erstellen</h3>
            <button onclick="document.getElementById('preset-modal').style.display='none'" style="background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 1.5rem;">&times;</button>
        </div>
        <form method="POST" action="{{ url_for('create_preset', guild_id=guild.id) }}">
            <div class="form-group">
                <label class="form-label">Preset Name</label>
                <input type="text" name="preset_name" class="form-input" placeholder="z.B. Moderator-Zugriff" required>
            </div>
            <div class="form-group">
                <label class="form-label">Berechtigungen (kommagetrennt)</label>
                <textarea name="permissions" class="form-textarea" placeholder="SEND_MESSAGES, MANAGE_MESSAGES, EMBED_LINKS..." required></textarea>
            </div>
            <button type="submit" class="btn btn-primary">Erstellen</button>
        </form>
    </div>
</div>

<script>
let currentPerms = {};

function filterChannels(categoryId) {
    const channelSelect = document.getElementById('channel-select');
    const options = channelSelect.querySelectorAll('option');
    options.forEach(opt => {
        if (!categoryId || opt.value === '' || opt.dataset.category === categoryId) {
            opt.style.display = '';
        } else {
            opt.style.display = 'none';
        }
    });
    channelSelect.value = '';
    document.getElementById('perm-editor').style.display = 'none';
}

function loadChannelPerms(channelId) {
    if (!channelId) {
        document.getElementById('perm-editor').style.display = 'none';
        return;
    }
    document.getElementById('perm-channel-id').value = channelId;
    document.getElementById('perm-editor').style.display = 'block';
    resetPerms();
}

function loadRolePerms(roleId) {
    document.getElementById('perm-role-id').value = roleId;
    // Load existing perms for this role/channel combination
    // This would be an AJAX call in production
}

function setPermState(permName, state) {
    currentPerms[permName] = state;
    const btnGroup = document.querySelector(`[data-perm="${permName}"]`);
    btnGroup.querySelectorAll('.perm-btn').forEach(btn => btn.classList.remove('active'));
    btnGroup.querySelector(`.perm-btn.${state}`).classList.add('active');
    updatePermData();
}

function updatePermData() {
    document.getElementById('perm-data').value = JSON.stringify(currentPerms);
}

function resetPerms() {
    currentPerms = {};
    document.querySelectorAll('.perm-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.perm-btn.neutral').forEach(btn => btn.classList.add('active'));
    updatePermData();
}

function saveAsPreset() {
    const name = prompt('Preset Name:');
    if (name) {
        alert('Preset wird gespeichert...');
        // Submit to create preset endpoint
    }
}

function applyPreset(presetId) {
    alert('Preset ' + presetId + ' wird angewendet...');
    // Load preset permissions via AJAX
}

// Close modal on outside click
document.getElementById('preset-modal').addEventListener('click', function(e) {
    if (e.target === this) {
        this.style.display = 'none';
    }
});
</script>
{% endblock %}
'''

# ============ ROUTES ============

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    # Discord OAuth2 URL
    scope = 'identify guilds'
    auth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={quote(DISCORD_REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={quote(scope)}"
    )
    
    return render_template_string(LOGIN_TEMPLATE, auth_url=auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        flash('Authentication failed', 'error')
        return redirect(url_for('login'))
    
    # Exchange code for token
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    
    response = requests.post(
        f"{DISCORD_API_BASE}/oauth2/token",
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    if response.status_code != 200:
        flash('Failed to authenticate with Discord', 'error')
        return redirect(url_for('login'))
    
    tokens = response.json()
    
    # Get user info
    user = discord_api_request('/users/@me', token=tokens['access_token'])
    if not user:
        flash('Failed to get user info', 'error')
        return redirect(url_for('login'))
    
    # Save to session
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['discriminator'] = user.get('discriminator', '0')
    session['avatar'] = user.get('avatar')
    session['access_token'] = tokens['access_token']
    session['refresh_token'] = tokens.get('refresh_token')
    
    # Save to database
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users 
                 (id, username, avatar, access_token, refresh_token, expires_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user['id'], user['username'], user.get('avatar'),
               tokens['access_token'], tokens.get('refresh_token'),
               int(time.time()) + tokens.get('expires_in', 604800)))
    conn.commit()
    conn.close()
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_guilds = get_user_guilds(session.get('access_token'))
    bot_guilds = get_bot_guilds()
    bot_guild_ids = {g['id'] for g in bot_guilds}
    
    # Filter guilds where user has admin/manage server permissions
    manageable_guilds = []
    for guild in user_guilds:
        permissions = int(guild.get('permissions', 0))
        if permissions & 0x8 or permissions & 0x20:  # ADMINISTRATOR or MANAGE_GUILD
            manageable_guilds.append(guild)
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        user=session,
        guilds=[g for g in manageable_guilds if g['id'] in bot_guild_ids],
        total_guilds=len(bot_guilds),
        manageable_guilds=len(manageable_guilds),
        client_id=DISCORD_CLIENT_ID
    )

@app.route('/guild/<guild_id>')
@login_required
@guild_access_required
def guild_dashboard(guild_id):
    guild = get_guild(guild_id)
    channels = get_guild_channels(guild_id)
    roles = get_guild_roles(guild_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as count FROM warnings WHERE guild_id = ?', (guild_id,))
    warning_count = c.fetchone()['count']
    conn.close()
    
    stats = {
        'member_count': guild.get('member_count', '?'),
        'channel_count': len(channels),
        'role_count': len(roles),
        'warning_count': warning_count
    }
    
    return render_template_string(
        GUILD_DASHBOARD_TEMPLATE,
        user=session,
        guild=guild,
        stats=stats
    )

@app.route('/guild/<guild_id>/moderation')
@login_required
@guild_access_required
def moderation(guild_id):
    guild = get_guild(guild_id)
    search = request.args.get('search', '')
    
    conn = get_db()
    c = conn.cursor()
    if search:
        c.execute('''SELECT * FROM warnings 
                     WHERE guild_id = ? AND (user_id LIKE ? OR reason LIKE ?)
                     ORDER BY timestamp DESC''',
                  (guild_id, f'%{search}%', f'%{search}%'))
    else:
        c.execute('SELECT * FROM warnings WHERE guild_id = ? ORDER BY timestamp DESC', (guild_id,))
    warnings = c.fetchall()
    conn.close()
    
    return render_template_string(
        MODERATION_TEMPLATE,
        user=session,
        guild=guild,
        warnings=warnings
    )

@app.route('/guild/<guild_id>/moderation/warn/<int:warn_id>/delete', methods=['POST'])
@login_required
@guild_access_required
def delete_warn(guild_id, warn_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM warnings WHERE id = ? AND guild_id = ?', (warn_id, guild_id))
    conn.commit()
    conn.close()
    
    log_action(guild_id, session['user_id'], 'DELETE_WARNING', f'Warn ID: {warn_id}')
    flash('Verwarnung gelöscht!', 'success')
    return redirect(url_for('moderation', guild_id=guild_id))

@app.route('/guild/<guild_id>/economy', methods=['GET', 'POST'])
@login_required
@guild_access_required
def economy(guild_id):
    guild = get_guild(guild_id)
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        amount = request.form.get('amount')
        
        c.execute('''INSERT INTO economy (user_id, guild_id, balance)
                     VALUES (?, ?, ?)
                     ON CONFLICT(user_id, guild_id) DO UPDATE SET balance = ?''',
                  (user_id, guild_id, amount, amount))
        conn.commit()
        log_action(guild_id, session['user_id'], 'ECONOMY_EDIT', f'User: {user_id}, Amount: {amount}')
        flash('Economy-Daten aktualisiert!', 'success')
    
    c.execute('''SELECT * FROM economy WHERE guild_id = ? 
                 ORDER BY balance DESC LIMIT 50''', (guild_id,))
    leaderboard = c.fetchall()
    conn.close()
    
    return render_template_string(
        ECONOMY_TEMPLATE,
        user=session,
        guild=guild,
        leaderboard=leaderboard
    )

# ============ CHANNEL PERMISSIONS ROUTES ============

@app.route('/guild/<guild_id>/channel-permissions')
@login_required
@guild_access_required
def channel_permissions(guild_id):
    guild = get_guild(guild_id)
    channels = get_guild_channels(guild_id)
    roles = get_guild_roles(guild_id)
    
    # Separate categories and channels
    categories = [c for c in channels if c['type'] == 4]
    text_channels = [c for c in channels if c['type'] in [0, 5]]  # Text and announcement
    voice_channels = [c for c in channels if c['type'] in [2, 13]]  # Voice and stage
    
    conn = get_db()
    c = conn.cursor()
    
    # Get presets
    c.execute('SELECT * FROM role_presets WHERE guild_id = ?', (guild_id,))
    presets = c.fetchall()
    for preset in presets:
        preset = dict(preset)
        try:
            preset['permissions'] = json.loads(preset['permissions'])
        except:
            preset['permissions'] = []
    
    # Get saved permissions with names
    c.execute('''SELECT cp.*, c.name as channel_name
                 FROM channel_permissions cp
                 LEFT JOIN guild_channels c ON cp.channel_id = c.channel_id
                 WHERE cp.guild_id = ?
                 ORDER BY cp.created_at DESC''', (guild_id,))
    saved_permissions = c.fetchall()
    
    conn.close()
    
    return render_template_string(
        CHANNEL_PERMISSIONS_TEMPLATE,
        user=session,
        guild=guild,
        channels=text_channels + voice_channels,
        categories=categories,
        roles=sorted(roles, key=lambda x: x.get('position', 0), reverse=True),
        presets=presets,
        saved_permissions=saved_permissions,
        permission_bits=PERMISSION_BITS
    )

@app.route('/guild/<guild_id>/channel-permissions/save', methods=['POST'])
@login_required
@guild_access_required
def save_channel_permissions(guild_id):
    channel_id = request.form.get('channel_id')
    role_id = request.form.get('role_id')
    permissions_json = request.form.get('permissions', '{}')
    
    if not channel_id or not role_id:
        flash('Channel und Rolle erforderlich!', 'error')
        return redirect(url_for('channel_permissions', guild_id=guild_id))
    
    try:
        permissions = json.loads(permissions_json)
    except:
        permissions = {}
    
    # Calculate permission bits
    allow_perms = 0
    deny_perms = 0
    
    for perm_name, state in permissions.items():
        if perm_name in PERMISSION_BITS:
            if state == 'allow':
                allow_perms |= PERMISSION_BITS[perm_name]
            elif state == 'deny':
                deny_perms |= PERMISSION_BITS[perm_name]
    
    # Update Discord API
    result = update_channel_permissions(guild_id, channel_id, role_id, allow_perms, deny_perms)
    
    if result:
        # Save to database
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO channel_permissions 
                     (guild_id, channel_id, role_id, allow_perms, deny_perms, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (guild_id, channel_id, role_id, allow_perms, deny_perms, int(time.time())))
        conn.commit()
        conn.close()
        
        log_action(guild_id, session['user_id'], 'CHANNEL_PERMISSIONS_UPDATE',
                   f'Channel: {channel_id}, Role: {role_id}')
        flash('Berechtigungen gespeichert!', 'success')
    else:
        flash('Fehler beim Speichern der Berechtigungen', 'error')
    
    return redirect(url_for('channel_permissions', guild_id=guild_id))

@app.route('/guild/<guild_id>/channel-permissions/preset/create', methods=['POST'])
@login_required
@guild_access_required
def create_preset(guild_id):
    preset_name = request.form.get('preset_name')
    permissions_text = request.form.get('permissions', '')
    
    permissions = [p.strip() for p in permissions_text.split(',') if p.strip()]
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO role_presets (guild_id, preset_name, permissions, created_at)
                 VALUES (?, ?, ?, ?)''',
              (guild_id, preset_name, json.dumps(permissions), int(time.time())))
    conn.commit()
    conn.close()
    
    log_action(guild_id, session['user_id'], 'CREATE_PRESET', f'Name: {preset_name}')
    flash('Preset erstellt!', 'success')
    return redirect(url_for('channel_permissions', guild_id=guild_id))

@app.route('/guild/<guild_id>/channel-permissions/delete/<int:perm_id>', methods=['POST'])
@login_required
@guild_access_required
def delete_channel_permission(guild_id, perm_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM channel_permissions WHERE id = ? AND guild_id = ?', (perm_id, guild_id))
    conn.commit()
    conn.close()
    
    flash('Berechtigung gelöscht!', 'success')
    return redirect(url_for('channel_permissions', guild_id=guild_id))

# ============ OTHER PAGES (PLACEHOLDERS) ============

GENERIC_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}{{ title }} - {{ guild.name }}{% endblock %}
{% block content %}
<nav class="navbar">
    <div class="logo"><div class="logo-icon">🤖</div><span>{{ guild.name }}</span></div>
    <div class="nav-user">
        <span>{{ user.username }}</span>
        <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
    </div>
</nav>
<div class="container">
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Hauptmenü</div>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
            <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link">🛡️ Moderation</a>
            <a href="{{ url_for('economy', guild_id=guild.id) }}" class="sidebar-link">💰 Economy</a>
            <a href="{{ url_for('channel_permissions', guild_id=guild.id) }}" class="sidebar-link">🔐 Channel-Rechte</a>
            <a href="{{ url_for('giveaways', guild_id=guild.id) }}" class="sidebar-link">🎁 Giveaways</a>
            <a href="{{ url_for('suggestions', guild_id=guild.id) }}" class="sidebar-link">💡 Vorschläge</a>
            <a href="{{ url_for('team', guild_id=guild.id) }}" class="sidebar-link">👥 Team</a>
            <a href="{{ url_for('applications', guild_id=guild.id) }}" class="sidebar-link">📝 Bewerbungen</a>
            <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">⚙️ Einstellungen</a>
        </div>
    </aside>
    <main class="main-content">
        <h1 class="page-title">{{ title }}</h1>
        <p class="page-subtitle">{{ description }}</p>
        <div class="card">
            <p>Diese Funktion wird bald verfügbar sein!</p>
        </div>
    </main>
</div>
{% endblock %}
'''

@app.route('/guild/<guild_id>/giveaways')
@login_required
@guild_access_required
def giveaways(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild, 
                                  title='Giveaways', description='Giveaways verwalten')

@app.route('/guild/<guild_id>/suggestions')
@login_required
@guild_access_required
def suggestions(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='Vorschläge', description='Community-Vorschläge')

@app.route('/guild/<guild_id>/team')
@login_required
@guild_access_required
def team(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='Team', description='Team-Mitglieder verwalten')

@app.route('/guild/<guild_id>/applications')
@login_required
@guild_access_required
def applications(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='Bewerbungen', description='Bewerbungen verwalten')

@app.route('/guild/<guild_id>/rss')
@login_required
@guild_access_required
def rss(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='RSS Feeds', description='RSS-Feeds verwalten')

@app.route('/guild/<guild_id>/rl-teams')
@login_required
@guild_access_required
def rl_teams(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='RL Teams', description='Rocket League Teams')

@app.route('/guild/<guild_id>/notifications')
@login_required
@guild_access_required
def notifications(guild_id):
    guild = get_guild(guild_id)
    return render_template_string(GENERIC_TEMPLATE, user=session, guild=guild,
                                  title='Notifications', description='Twitch & YouTube Benachrichtigungen')

@app.route('/guild/<guild_id>/modlogs')
@login_required
@guild_access_required
def modlogs(guild_id):
    guild = get_guild(guild_id)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT * FROM dashboard_logs 
                 WHERE guild_id = ? 
                 ORDER BY timestamp DESC LIMIT 100''', (guild_id,))
    logs = c.fetchall()
    conn.close()
    
    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}Mod Logs - {{ guild.name }}{% endblock %}
    {% block content %}
    <nav class="navbar">
        <div class="logo"><div class="logo-icon">🤖</div><span>{{ guild.name }}</span></div>
        <div class="nav-user">
            <span>{{ user.username }}</span>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
        </div>
    </nav>
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Hauptmenü</div>
                <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
                <a href="{{ url_for('moderation', guild_id=guild.id) }}" class="sidebar-link">🛡️ Moderation</a>
                <a href="{{ url_for('modlogs', guild_id=guild.id) }}" class="sidebar-link active">📋 Mod Logs</a>
                <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link">⚙️ Einstellungen</a>
            </div>
        </aside>
        <main class="main-content">
            <h1 class="page-title">Mod Logs</h1>
            <p class="page-subtitle">Letzte Dashboard-Aktionen</p>
            <div class="card">
                <table class="data-table">
                    <thead>
                        <tr><th>Zeit</th><th>User</th><th>Aktion</th><th>Details</th></tr>
                    </thead>
                    <tbody>
                        {% for log in logs %}
                        <tr>
                            <td>{{ log.timestamp }}</td>
                            <td>{{ log.user_id }}</td>
                            <td><span class="badge badge-info">{{ log.action }}</span></td>
                            <td>{{ log.details }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" style="text-align:center;color:var(--text-secondary)">Keine Logs</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </main>
    </div>
    {% endblock %}
    ''', user=session, guild=guild, logs=logs)

@app.route('/guild/<guild_id>/settings', methods=['GET', 'POST'])
@login_required
@guild_access_required
def settings(guild_id):
    guild = get_guild(guild_id)
    channels = get_guild_channels(guild_id)
    text_channels = [c for c in channels if c['type'] == 0]
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        prefix = request.form.get('prefix', '?')
        welcome_channel = request.form.get('welcome_channel')
        welcome_msg = request.form.get('welcome_message')
        goodbye_channel = request.form.get('goodbye_channel')
        goodbye_msg = request.form.get('goodbye_message')
        modlog_channel = request.form.get('modlog_channel')
        suggest_channel = request.form.get('suggest_channel')
        
        c.execute('''INSERT OR REPLACE INTO guild_settings 
                     (guild_id, prefix, welcome_channel, welcome_message,
                      goodbye_channel, goodbye_message, modlog_channel, suggest_channel)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (guild_id, prefix, welcome_channel, welcome_msg,
                   goodbye_channel, goodbye_msg, modlog_channel, suggest_channel))
        conn.commit()
        flash('Einstellungen gespeichert!', 'success')
    
    c.execute('SELECT * FROM guild_settings WHERE guild_id = ?', (guild_id,))
    settings = c.fetchone()
    conn.close()
    
    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}Einstellungen - {{ guild.name }}{% endblock %}
    {% block content %}
    <nav class="navbar">
        <div class="logo"><div class="logo-icon">🤖</div><span>{{ guild.name }}</span></div>
        <div class="nav-user">
            <span>{{ user.username }}</span>
            <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="btn btn-secondary btn-sm">Zurück</a>
        </div>
    </nav>
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Hauptmenü</div>
                <a href="{{ url_for('guild_dashboard', guild_id=guild.id) }}" class="sidebar-link">📊 Übersicht</a>
                <a href="{{ url_for('settings', guild_id=guild.id) }}" class="sidebar-link active">⚙️ Einstellungen</a>
            </div>
        </aside>
        <main class="main-content">
            <h1 class="page-title">Einstellungen</h1>
            <p class="page-subtitle">Bot-Konfiguration für {{ guild.name }}</p>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'error' if category == 'error' else 'success' }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            <form method="POST" class="card">
                <h3 class="card-title">Allgemein</h3>
                <div class="form-group">
                    <label class="form-label">Prefix</label>
                    <input type="text" name="prefix" class="form-input" value="{{ settings.prefix if settings else '?' }}" maxlength="5">
                </div>
                
                <h3 class="card-title" style="margin-top: 1.5rem;">Willkommen</h3>
                <div class="form-group">
                    <label class="form-label">Willkommens-Channel</label>
                    <select name="welcome_channel" class="form-select">
                        <option value="">-- Deaktiviert --</option>
                        {% for ch in channels %}
                        <option value="{{ ch.id }}" {% if settings and settings.welcome_channel == ch.id %}selected{% endif %}>#{{ ch.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Willkommens-Nachricht</label>
                    <textarea name="welcome_message" class="form-textarea" placeholder="Willkommen {user} auf {server}!">{{ settings.welcome_message if settings else '' }}</textarea>
                </div>
                
                <h3 class="card-title" style="margin-top: 1.5rem;">Abschied</h3>
                <div class="form-group">
                    <label class="form-label">Abschieds-Channel</label>
                    <select name="goodbye_channel" class="form-select">
                        <option value="">-- Deaktiviert --</option>
                        {% for ch in channels %}
                        <option value="{{ ch.id }}" {% if settings and settings.goodbye_channel == ch.id %}selected{% endif %}>#{{ ch.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                
                <h3 class="card-title" style="margin-top: 1.5rem;">Logging</h3>
                <div class="form-group">
                    <label class="form-label">Mod-Log Channel</label>
                    <select name="modlog_channel" class="form-select">
                        <option value="">-- Deaktiviert --</option>
                        {% for ch in channels %}
                        <option value="{{ ch.id }}" {% if settings and settings.modlog_channel == ch.id %}selected{% endif %}>#{{ ch.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                
                <h3 class="card-title" style="margin-top: 1.5rem;">Vorschläge</h3>
                <div class="form-group">
                    <label class="form-label">Vorschlags-Channel</label>
                    <select name="suggest_channel" class="form-select">
                        <option value="">-- Deaktiviert --</option>
                        {% for ch in channels %}
                        <option value="{{ ch.id }}" {% if settings and settings.suggest_channel == ch.id %}selected{% endif %}>#{{ ch.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                
                <button type="submit" class="btn btn-primary">💾 Speichern</button>
            </form>
        </main>
    </div>
    {% endblock %}
    ''', user=session, guild=guild, channels=text_channels, settings=settings)

# ============ MAIN ============

if __name__ == '__main__':
    init_db()
    keep_alive()
    app.run(host='0.0.0.0', port=PORT, debug=False)
