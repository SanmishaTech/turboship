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

    # Ensure proper permissions for htdocs directory
    os.system(f"chown -R www-data:www-data {app_path}")
    os.system(f"chmod -R 755 {app_path}")

    # Correct ownership and permissions for logs directory
    os.system(f"chown -R www-data:www-data {logs_path}")
    os.system(f"chmod -R 755 {logs_path}")

    # Ensure pm2.config.js is created before setting permissions
    pm2_config_path = os.path.join(app_root, "pm2.config.js")
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
    if not os.path.exists(pm2_config_path):
        with open(pm2_config_path, "w") as f:
            f.write(pm2_config)
    os.system(f"chown {sftp_user}:{sftp_user} {pm2_config_path}")
    os.system(f"chmod 644 {pm2_config_path}")

    # Ensure .well-known directory exists for SSL challenges
    os.makedirs(os.path.join(app_path, ".well-known/acme-challenge"), exist_ok=True)
    os.system(f"chown -R www-data:www-data {os.path.join(app_path, '.well-known')}")
    os.system(f"chmod -R 755 {os.path.join(app_path, '.well-known')}")

    # Landing page
    landing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing_template.html")
    if os.path.exists(landing_path):
        with open(landing_path) as src:
            content = src.read().replace("{app_name}", app_name)
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

    # Ensure proper ownership and permissions for index.html
    index_path = os.path.join(app_path, "index.html")
    if os.path.exists(index_path):
        os.system(f"chown www-data:www-data {index_path}")
        os.system(f"chmod 644 {index_path}")

    # Ensure all files created via SFTP or SSH have www-data ownership
    os.system(f"chown -R www-data:www-data {app_root}")

    # Ensure proper ownership and permissions for the root directory
    os.system(f"chown -R {sftp_user}:{sftp_user} {app_root}")
    os.system(f"chmod -R 755 {app_root}")

    # Add the SFTP user to the www-data group
    os.system(f"usermod -aG www-data {sftp_user}")

    # Set group ownership of the root directory to www-data
    os.system(f"chgrp -R www-data {app_root}")

    # Set group permissions for the root directory
    os.system(f"chmod -R g+rwX {app_root}")

def configure_nginx(project, domains, enable_ssl=False):
    if isinstance(domains, str):
        domains = [domains]
    server_names = " ".join(domains)
    root_path = f"/var/www/{project}_sftp/htdocs"

    conf = f"""
        server {{
            listen 80;
            server_name {server_names};
            return 301 https://$host$request_uri;
        }}

        server {{
            {f'listen 443 ssl;' if enable_ssl else ''}
            server_name {server_names};

            {f'ssl_certificate /etc/letsencrypt/live/{domains[0]}/fullchain.pem; # managed by Certbot\n' if enable_ssl else ''}
            {f'ssl_certificate_key /etc/letsencrypt/live/{domains[0]}/privkey.pem; # managed by Certbot\n' if enable_ssl else ''}
            {f'include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot\n' if enable_ssl else ''}
            {f'ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot\n' if enable_ssl else ''}

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

            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
            add_header X-XSS-Protection "1; mode=block";
        }}
        """

    path = f"/etc/nginx/sites-available/{project}"
    try:
        with open(path, "w") as f:
            f.write(conf)
        print(colored(f"✅ NGINX configuration written to {path}", "green"))
    except Exception as e:
        print(colored(f"❌ Failed to write NGINX configuration: {e}", "red"))
        return

    symlink = f"/etc/nginx/sites-enabled/{project}"
    try:
        if not os.path.exists(symlink):
            os.symlink(path, symlink)
        print(colored(f"✅ Symlink created for {symlink}", "green"))
    except Exception as e:
        print(colored(f"❌ Failed to create symlink: {e}", "red"))
        return

    try:
        os.makedirs(os.path.join(root_path, ".well-known/acme-challenge/"), exist_ok=True)
        print(colored("✅ .well-known/acme-challenge directory created", "green"))
    except Exception as e:
        print(colored(f"❌ Failed to create .well-known/acme-challenge directory: {e}", "red"))
        return

    try:
        result = os.system("nginx -t && systemctl reload nginx")
        if result != 0:
            print(colored("❌ NGINX reload failed. Check configuration syntax.", "red"))
            os.system("nginx -t")  # Check NGINX configuration
            exit(1)  # Stop execution
        else:
            print(colored("✅ NGINX reloaded successfully.", "green"))
    except Exception as e:
        print(colored(f"❌ Failed to reload NGINX: {e}", "red"))

def install_ssl(domains):
    if isinstance(domains, str):
        domains = [domains]
    domain_flags = " ".join(f"-d {d}" for d in domains)

    print(colored(f"🔧 Starting SSL installation for domains: {', '.join(domains)}", "cyan"))

    # Attempt to generate SSL certificates
    certbot_command = (
        f"certbot --nginx --non-interactive --agree-tos {domain_flags} "
        f"-m admin@{domains[0]} --redirect --expand"
    )

    print(colored(f"🔧 Running Certbot command: {certbot_command}", "cyan"))
    result = os.system(certbot_command)

    if result != 0:
        print(colored("❌ Certbot failed to generate SSL certificates. Retrying...", "red"))

        # Temporarily disable SSL in NGINX
        original_configs = {}
        for domain in domains:
            nginx_path = f"/etc/nginx/sites-available/{domain}"
            if os.path.exists(nginx_path):
                with open(nginx_path, "r") as f:
                    original_configs[domain] = f.read()
                conf = original_configs[domain]
                conf = conf.replace("listen 443 ssl;", "# listen 443 ssl;")
                conf = conf.replace("ssl_certificate", "# ssl_certificate")
                conf = conf.replace("ssl_certificate_key", "# ssl_certificate_key")
                with open(nginx_path, "w") as f:
                    f.write(conf)

        print(colored("🔧 Temporarily disabled SSL in NGINX configurations.", "yellow"))
        os.system("nginx -t && systemctl reload nginx")

        # Retry Certbot
        print(colored(f"🔧 Retrying Certbot command: {certbot_command}", "cyan"))
        result = os.system(certbot_command)

        if result != 0:
            print(colored("❌ Certbot failed again. Please check domain accessibility and logs.", "red"))

            # Restore original NGINX configurations
            for domain, original_conf in original_configs.items():
                nginx_path = f"/etc/nginx/sites-available/{domain}"
                with open(nginx_path, "w") as f:
                    f.write(original_conf)

            print(colored("🔧 Restored original NGINX configurations.", "yellow"))
            os.system("nginx -t && systemctl reload nginx")
            return

        print(colored("✅ SSL certificates generated successfully.", "green"))

        # Restore original NGINX configurations
        for domain, original_conf in original_configs.items():
            nginx_path = f"/etc/nginx/sites-available/{domain}"
            with open(nginx_path, "w") as f:
                f.write(original_conf)

        print(colored("🔧 Restored original NGINX configurations.", "yellow"))
        os.system("nginx -t && systemctl reload nginx")
    else:
        print(colored("✅ SSL certificates generated successfully.", "green"))

    # Update NGINX configuration with SSL enabled
    for domain in domains:
        configure_nginx(domain, [domain], enable_ssl=True)
        os.system("nginx -t && systemctl reload nginx")

def test_project(project):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, db_pass FROM apps WHERE project = ?", (project,))
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

def list_apps():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT app, temp_domain, real_domain, db_type, db_name, db_user, sftp_user, created_at FROM apps")
    rows = c.fetchall()
    headers = ["App", "Temp Domain", "Real Domain", "DB Type", "DB Name", "DB User", "SFTP User", "Created At"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    conn.close()

def remove_app(app):
    confirm = input(colored(f"⚠️ Are you sure you want to delete '{app}' and all its resources? (yes/no): ", "red"))
    if confirm.lower() != "yes":
        print("❌ Aborted.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, sftp_user FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ App '{app}' not found.", "red"))
        return

    temp_domain, real_domain, db_type, db_name, db_user, sftp_user = row
    domains = [temp_domain]
    if real_domain:
        domains.append(real_domain)

    app_root = f"/var/www/{app}_sftp"

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
    nginx_path = f"/etc/nginx/sites-available/{app}"
    nginx_symlink = f"/etc/nginx/sites-enabled/{app}"
    if os.path.exists(nginx_symlink):
        os.remove(nginx_symlink)
    if os.path.exists(nginx_path):
        os.remove(nginx_path)

    os.system("nginx -t && systemctl reload nginx")

    # Remove SSL certificates
    for domain in domains:
        subprocess.run(["certbot", "delete", "--cert-name", domain, "--non-interactive"], input=b'y\n')

    # Remove DB record
    c.execute("DELETE FROM apps WHERE app = ?", (app,))
    conn.commit()
    conn.close()

    # Remove the app's root directory
    if os.path.exists(app_root):
        subprocess.run(["rm", "-rf", app_root], stderr=subprocess.DEVNULL)

    print(colored(f"✅ App '{app}' deleted successfully.", "green"))

def map_domain(app, new_domain):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ App '{app}' not found in DB.", "red"))
        return

    temp_domain = row[0]
    domains = [temp_domain, new_domain]

    # Update nginx and certbot
    configure_nginx(app, domains)

    # Install SSL for each domain individually
    for domain in domains:
        install_ssl(domain)

    # Update DB
    c.execute("UPDATE apps SET real_domain = ? WHERE app = ?", (new_domain, app))
    conn.commit()
    conn.close()

    print(colored(f"✅ Domain for '{app}' updated to '{new_domain}'", "green"))

def main():
    init_db()
    parser = argparse.ArgumentParser(
        description=colored("Turboship v0.7 - Multi-App Hosting Tool", "cyan"),
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Create subcommand
    create_parser = subparsers.add_parser("create", help="Create a new app")
    create_parser.add_argument("--domain", metavar="DOMAIN", help="Specify real domain")

    # Test subcommand
    test_parser = subparsers.add_parser("test", help="Run health checks for an app")
    test_parser.add_argument("app", metavar="APP", help="App name to test")

    # List subcommand
    subparsers.add_parser("list", help="List all created apps in a table")

    # Remove subcommand
    remove_parser = subparsers.add_parser("remove", help="Remove an app completely")
    remove_parser.add_argument("app", metavar="APP", help="App name to remove")

    # Map-domain subcommand
    map_domain_parser = subparsers.add_parser("map-domain", help="Map real domain to existing app")
    map_domain_parser.add_argument("app", metavar="APP", help="App name")
    map_domain_parser.add_argument("--domain", metavar="DOMAIN", help="Specify real domain")

    # Install-SSL subcommand
    install_ssl_parser = subparsers.add_parser("install-ssl", help="Install SSL certificates for an app's domains")
    install_ssl_parser.add_argument("app", metavar="APP", help="App name to install SSL for")
    install_ssl_parser.add_argument("--domain", metavar="DOMAIN", help="Comma-separated list of domains")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        exit(1)

    # Banner
    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} CLI", "blue"))

    # Command Handling
    if args.command == "create":
        create_app()
    elif args.command == "test":
        test_app(args.app)
    elif args.command == "list":
        list_apps()
    elif args.command == "remove":
        remove_app(args.app)
    elif args.command == "map-domain":
        map_domain(args.app, args.domain)
    elif args.command == "install-ssl":
        domains = args.domain.split(",")
        install_ssl(domains)
    else:
        print(colored("⚠️  No valid command given.\n", "yellow"))
        parser.print_help()

if __name__ == "__main__":
    main()
