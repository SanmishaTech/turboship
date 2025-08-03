import os
import subprocess
import random
import string
import socket
import re
import sqlite3
import argparse
from datetime import datetime
from tabulate import tabulate
from termcolor import colored
from pyfiglet import figlet_format

TURBOSHIP_VERSION = "0.7"
DB_PATH = "/opt/turboship/turboship.db"
GITHUB_URL = "https://github.com/SanmishaTech/turboship"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS apps (
            app TEXT PRIMARY KEY,
            temp_domain TEXT,
            real_domain TEXT,
            db_type TEXT,
            db_name TEXT,
            db_user TEXT,
            db_pass TEXT,
            sftp_user TEXT,
            sftp_pass TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


def get_public_ip():
    try:
        ip = subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()
        socket.inet_aton(ip)  # Validate IP
        return ip
    except:
        print(colored("❌ Failed to retrieve valid public IP. Cannot generate sslip.io domain.", "red"))
        exit(1)

def generate_password(length=12):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def validate_app_name(name):
    return re.match("^[a-zA-Z0-9_-]+$", name) is not None

def prompt_database():
    print(colored("Choose database type:", "cyan"))
    print("1. MariaDB")
    print("2. PostgreSQL")
    choice = input("Enter choice [1/2]: ").strip()
    return "mariadb" if choice == "1" else "postgres"

def create_app():
    app_name = input("Enter app name: ").strip()
    if not validate_app_name(app_name):
        print(colored("Invalid app name. Use only letters, numbers, dashes, underscores.", "red"))
        return

    db_type = prompt_database()
    sftp_user = f"{app_name}_sftp"
    db_user = f"{app_name}_dbu"
    db_pass = generate_password()
    sftp_pass = generate_password()
    db_name = f"{app_name}_db"
    temp_domain = f"{app_name}.{get_public_ip()}.sslip.io"
    now = datetime.now().isoformat()

    app_root = f"/var/www/{sftp_user}"
    app_path = os.path.join(app_root, "htdocs")
    logs_path = os.path.join(app_root, "logs")
    api_path = os.path.join(app_root, "api")

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} - App Summary:", "yellow"))
    print(f"  🚀 App Name     : {colored(app_name, 'cyan')}")
    print(f"  🌐 Temp Domain  : {colored('https://' + temp_domain, 'green')}")
    print(f"  📦 SFTP User    : {sftp_user}")
    print(f"  🔑 SFTP Pass    : {sftp_pass}")
    print(f"  🛢️  DB Type      : {db_type}")
    print(f"  🗄️  DB Name      : {db_name}")
    print(f"  👤 DB User      : {db_user}")
    print(f"  🔐 DB Password  : {db_pass}")
    print(f"  🕒 Created At   : {now}\n")

    # Create user with SSH + SFTP (middle-ground approach)
    os.system(f"useradd -m -d {app_root} -s /bin/bash {sftp_user}")
    subprocess.run(["bash", "-c", f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])

    # Create directories
    os.makedirs(app_path, exist_ok=True)
    os.makedirs(logs_path, exist_ok=True)
    os.makedirs(api_path, exist_ok=True)

    # Permissions
    os.system(f"chown -R {sftp_user}:{sftp_user} {app_path}")
    os.system(f"chown -R {sftp_user}:{sftp_user} {api_path}")
    os.system(f"chown -R www-data:www-data {logs_path}")

    # Landing page
    landing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing_template.html")
    if os.path.exists(landing_path):
        with open(landing_path) as src:
            content = src.read().replace("{app_name}", app_name).replace("{github}", GITHUB_URL)
        with open(os.path.join(app_path, "index.html"), "w") as dst:
            dst.write(content)
    else:
        print(colored("⚠️ landing_template.html not found — skipping landing page copy.", "yellow"))

    # PM2 config
    pm2_config = f"""module.exports = {{
        apps: [
            {{
            name: "{app_name}-backend",
            script: "npm start",
            cwd: "/var/www/{sftp_user}/api",
            watch: false,
            env: {{
                NODE_ENV: "production"
            }}
            }}
        ]
        }};
        """
    with open(os.path.join(app_root, "pm2.config.js"), "w") as f:
        f.write(pm2_config)

    # Database setup
    if db_type == "mariadb":
        sql = f"""
        CREATE DATABASE IF NOT EXISTS {db_name};
        CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_pass}';
        GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%';
        FLUSH PRIVILEGES;
        """
        subprocess.run(["mysql", "-u", "root", "-e", sql])
    elif db_type == "postgres":
        commands = [
            f"CREATE USER {db_user} WITH PASSWORD '{db_pass}';",
            f"CREATE DATABASE {db_name} OWNER {db_user};"
        ]
        for cmd in commands:
            subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', cmd])

    # Nginx + SSL creation
    configure_nginx(app_name, [temp_domain])
    install_ssl(temp_domain)

    # Save to SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO apps 
        (app, temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (app_name, temp_domain, None, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, now))
    conn.commit()
    conn.close()

def configure_nginx(project, domains):
    if isinstance(domains, str):
        domains = [domains]
    server_names = " ".join(domains)
    root_path = f"/var/www/{project}_sftp/htdocs"

    conf = f"""
        server {{
            listen 80;
            server_name {server_names};

            root {root_path};
            index index.html;

            location ^~ /.well-known/acme-challenge/ {{
                allow all;
                default_type "text/plain";
                root {root_path};
            }}

            location /api/ {{
                proxy_pass http://localhost:3000/;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection 'upgrade';
                proxy_set_header Host $host;
                proxy_cache_bypass $http_upgrade;
            }}

            location / {{
                try_files $uri $uri/ =404;
            }}
        }}
        """

    path = f"/etc/nginx/sites-available/{project}"
    with open(path, "w") as f:
        f.write(conf)

    symlink = f"/etc/nginx/sites-enabled/{project}"
    if not os.path.exists(symlink):
        os.symlink(path, symlink)

    os.makedirs(os.path.join(root_path, ".well-known/acme-challenge/"), exist_ok=True)

    os.system("nginx -t && systemctl reload nginx")

def install_ssl(domains):
    if isinstance(domains, str):
        domains = [domains]
    domain_flags = " ".join(f"-d {d}" for d in domains)
    os.system(
        f"certbot --nginx --non-interactive --agree-tos {domain_flags} "
        f"-m admin@{domains[0]} --redirect --expand || true"
    )

def test_project(project):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, db_pass FROM projects WHERE project = ?", (project,))
    row = c.fetchone()
    if not row:
        print(colored("❌ Project not found.", "red"))
        return

    temp_domain, real_domain, db_type, db_name, db_user, db_pass = row
    print(colored(f"\nTesting project '{project}':", "cyan"))

    for domain in filter(None, [temp_domain, real_domain]):
        print(f"🌐 Testing domain: {domain}")
        try:
            socket.gethostbyname(domain)
            print(colored("✅ DNS Resolved", "green"))
        except:
            print(colored("❌ DNS failed", "red"))

    if db_type == "mariadb":
        result = subprocess.call(["mysql", "-h", "127.0.0.1", "-u", db_user, f"-p{db_pass}", "-e", "SHOW DATABASES;"])
    elif db_type == "postgres":
        env = os.environ.copy()
        env['PGPASSWORD'] = db_pass
        result = subprocess.call(["psql", "-U", db_user, "-d", db_name, "-c", "\\l"], env=env)

    print(colored("✅ DB Connection OK" if result == 0 else "❌ DB Connection Failed", "green" if result == 0 else "red"))

def list_projects():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT project, temp_domain, real_domain, db_type, db_name, db_user, sftp_user, created_at FROM projects")
    rows = c.fetchall()
    headers = ["Project", "Temp Domain", "Real Domain", "DB Type", "DB Name", "DB User", "SFTP User", "Created At"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    conn.close()

def remove_project(project):
    confirm = input(colored(f"⚠️ Are you sure you want to delete '{project}' and all its resources? (yes/no): ", "red"))
    if confirm.lower() != "yes":
        print("❌ Aborted.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, sftp_user FROM projects WHERE project = ?", (project,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ Project '{project}' not found.", "red"))
        return

    temp_domain, real_domain, db_type, db_name, db_user, sftp_user = row
    domains = [temp_domain]
    if real_domain:
        domains.append(real_domain)

    # Backup DB (optional future improvement)

    # Remove database user and database
    if db_type == "mariadb":
        sql = f"""
        DROP DATABASE IF EXISTS {db_name};
        DROP USER IF EXISTS '{db_user}'@'%';
        """
        subprocess.run(["mysql", "-u", "root", "-e", sql])
    elif db_type == "postgres":
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', f"DROP DATABASE IF EXISTS {db_name};"])
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', f"DROP ROLE IF EXISTS {db_user};"])

    # Remove Linux user
    subprocess.run(["userdel", "-r", sftp_user], stderr=subprocess.DEVNULL)

    # Remove Nginx config
    nginx_path = f"/etc/nginx/sites-available/{project}"
    nginx_symlink = f"/etc/nginx/sites-enabled/{project}"
    if os.path.exists(nginx_symlink):
        os.remove(nginx_symlink)
    if os.path.exists(nginx_path):
        os.remove(nginx_path)

    os.system("nginx -t && systemctl reload nginx")

    # Remove SSL certificates
    for domain in domains:
        subprocess.run(["certbot", "delete", "--cert-name", domain], input=b'y\n')

    # Remove DB record
    c.execute("DELETE FROM projects WHERE project = ?", (project,))
    conn.commit()
    conn.close()

    print(colored(f"✅ Project '{project}' deleted successfully.", "green"))

def map_domain(project, new_domain):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain FROM projects WHERE project = ?", (project,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ Project '{project}' not found in DB.", "red"))
        return

    temp_domain = row[0]
    domains = [temp_domain, new_domain]

    # Update nginx and certbot
    configure_nginx(project, domains)

    # Install SSL for each domain individually
    for domain in domains:
        install_ssl(domain)

    # Update DB
    c.execute("UPDATE projects SET real_domain = ? WHERE project = ?", (new_domain, project))
    conn.commit()
    conn.close()

    print(colored(f"✅ Domain for '{project}' updated to '{new_domain}'", "green"))

def main():
    init_db()
    parser = argparse.ArgumentParser(
        description=colored("Turboship v0.7 - Multi-App Hosting Tool", "cyan"),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("create", action="store_true", required=False,
                        help="Create a new app with optional real domain\n  Example: create --domain yourdomain.com")
    parser.add_argument("test", metavar="APP", required=False,
                        help="Run health checks for an app\n  Example: test myapp")
    parser.add_argument("list", action="store_true", required=False,
                        help="List all created apps in a table")
    parser.add_argument("remove", metavar="APP", required=False,
                        help="Remove an app completely (with warning)\n  Example: remove myapp")
    parser.add_argument("domain", metavar="DOMAIN", required=False,
                        help="(Used with create or map-domain) Specify real domain\n  Example: create --domain myapp.sanmisha.com")
    parser.add_argument("map-domain", metavar="APP", required=False,
                        help="Map real domain to existing app\n  Example: map-domain myapp --domain mydomain.com")

    args = parser.parse_args()

    if len(vars(args)) == 0:
        parser.print_help()
        exit(1)

    # Banner
    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} CLI", "blue"))

    # Command Handling
    if args.create:
        create_app()
    elif args.test:
        test_app(args.test)
    elif args.list:
        list_apps()
    elif args.remove:
        remove_app(args.remove)
    elif args.map_domain and args.domain:
        map_domain(args.map_domain, args.domain)
    else:
        print(colored("⚠️  No valid command given.\n", "yellow"))
        parser.print_help()

if __name__ == "__main__":
    main()
