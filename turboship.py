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

TURBOSHIP_VERSION = "0.8"
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
            port INTEGER,
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

def allocate_port():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT port FROM apps")
    used_ports = [row[0] for row in c.fetchall()]
    conn.close()

    # Start allocating ports from 3000
    port = 3000
    while port in used_ports:
        port += 1
    return port

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

    # Save to SQLite first
    conn = sqlite3.connect(DB_PATH)
    port = allocate_port()
    conn.execute(
        """
        INSERT INTO apps 
        (app, temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, port, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (app_name, temp_domain, None, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, port, now)
    )
    conn.commit()
    conn.close()

    # Update app_root to exclude temp_domain
    app_root = f"/var/www/{app_name}_sftp"
    app_path = os.path.join(app_root, "htdocs")
    logs_path = os.path.join(app_root, "logs")

    # Ask if API folder is needed
    api_needed = input("Do you need an API folder? (yes/no) [no]: ")


    # Check if the user already exists
    user_check = subprocess.run(["id", "-u", sftp_user], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if user_check.returncode != 0:
        # Create user with SSH + SFTP
        os.system(f"useradd -m -d {app_root} -s /bin/bash {sftp_user}")
        subprocess.run(["bash", "-c", f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])
    else:
        print(colored(f"User {sftp_user} already exists. Skipping user creation.", "yellow"))

    # Restrict the user to SFTP only
    # Removed redundant code for appending to sshd_config as Match Group block is already present.

    # Add the SFTP user to the sftpusers group
    os.system("groupadd -f sftpusers")
    os.system(f"usermod -aG sftpusers {sftp_user}")

    # Ensure the ChrootDirectory exists and has the correct permissions
    chroot_dir = os.path.join(app_root, "..")
    os.makedirs(chroot_dir, exist_ok=True)
    os.system(f"chown root:root {chroot_dir}")
    os.system(f"chmod 755 {chroot_dir}")

    # Ensure the user's home directory inside the chroot is owned by root
    os.system(f"chown root:root {app_root}")
    os.system(f"chmod 755 {app_root}")

    # Create a writable subdirectory for the user
    user_writable_dir = os.path.join(app_root, "htdocs")
    os.makedirs(user_writable_dir, exist_ok=True)
    os.system(f"chown {sftp_user}:{sftp_user} {user_writable_dir}")
    os.system(f"chmod 755 {user_writable_dir}")

    # Create directories
    os.makedirs(app_path, exist_ok=True)
    os.makedirs(logs_path, exist_ok=True)
    if api_path:
        os.makedirs(api_path, exist_ok=True)

    # Permissions
    os.system(f"chown -R {sftp_user}:{sftp_user} {app_path}")
    if api_path:
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
    cwd_path = api_path if api_needed == "yes" else app_path
    pm2_config = f"""module.exports = {{
        apps: [
            {{
            name: "{app_name}-backend",
            script: "npm start",
            cwd: "{cwd_path}",
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
            f"CREATE DATABASE {db_name} OWNER {db_user};",
            f"REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;",
            f"REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;",
            f"GRANT CONNECT ON DATABASE {db_name} TO {db_user};"
        ]
        for cmd in commands:
            subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', cmd])

    # Nginx + SSL creation
    configure_nginx(app_name, [temp_domain], api_path)
    # install_ssl(app_name)

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

    # Set umask for the SFTP user
    sftp_profile_path = os.path.join(app_root, ".bashrc")
    with open(sftp_profile_path, "a") as f:
        f.write("\n# Set umask for SFTP user\n")
        f.write("umask 022\n")

    # Ensure the target directory has the correct group ownership and setgid bit
    os.system(f"chown -R {sftp_user}:www-data {app_root}")
    os.system(f"chmod -R g+rwX {app_root}")
    os.system(f"chmod g+s {app_root}")

    # Print summary
    info_app(app_name)

def configure_nginx(app, domains, api_path=None):
    if isinstance(domains, str):
        domains = [domains]

    server_names = " ".join(domains)
    root_path = f"/var/www/{app}_sftp/htdocs"

    # Get the allocated port for the app
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT port FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    conn.close()
    if not row:
        print(colored(f"❌ App '{app}' not found in DB.", "red"))
        return
    port = row[0]

    # Generate NGINX configuration based on whether a separate API is needed
    if api_path is None:
        # This configuration is for single-process apps like Next.js
        # where the app server handles all routes (pages, api, static).
        conf = f"""
        server {{
            listen 80;
            server_name {server_names};

            # Path for ACME challenge files for Let's Encrypt
            location ^~ /.well-known/acme-challenge/ {{
                allow all;
                default_type "text/plain";
                root {root_path};
            }}

            # Proxy all other requests to the running application
            location / {{
                proxy_pass http://localhost:{port};
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection 'upgrade';
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
                proxy_cache_bypass $http_upgrade;
            }}
        }}
        """
    else:
        # This configuration is for separate frontend (in htdocs) and backend (in api)
        conf = f"""
        server {{
            listen 80;
            server_name {server_names};

            root {root_path};
            index index.html;

            # Path for ACME challenge files for Let's Encrypt
            location ^~ /.well-known/acme-challenge/ {{
                allow all;
                default_type "text/plain";
                root {root_path};
            }}

            # Proxy API requests to the backend server
            location /api/ {{
                proxy_pass http://localhost:{port}/api/;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection 'upgrade';
                proxy_set_header Host $host;
                proxy_cache_bypass $http_upgrade;
            }}

            # Serve static frontend files
            location / {{
                try_files $uri $uri/ /index.html;
            }}

            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
            add_header X-XSS-Protection "1; mode=block";
        }}
        """

    # Use app name for NGINX configuration file
    path = f"/etc/nginx/sites-available/{app}"
    try:
        with open(path, "w") as f:
            f.write(conf)
    except Exception as e:
        print(colored(f"❌ Failed to write NGINX config for {app}: {e}", "red"))
        return

    # Create symlink in sites-enabled
    symlink = f"/etc/nginx/sites-enabled/{app}"
    try:
        if not os.path.exists(symlink):
            os.symlink(path, symlink)
    except Exception as e:
        print(colored(f"❌ Failed to create NGINX symlink for {app}: {e}", "red"))
        return

    # Create .well-known directory for SSL challenges
    try:
        os.makedirs(os.path.join(root_path, ".well-known/acme-challenge/"), exist_ok=True)
    except Exception as e:
        print(colored(f"❌ Failed to create .well-known directory for {app}: {e}", "red"))
        return

    # Test and reload NGINX
    try:
        result = os.system("nginx -t && systemctl reload nginx")
        if result != 0:
            print(colored("❌ NGINX configuration test failed. Please check the syntax.", "red"))
            os.system("nginx -t")  # Show detailed errors
            exit(1)
    except Exception as e:
        print(colored(f"❌ Failed to reload NGINX: {e}", "red"))
        return


def install_ssl(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ App '{app}' not found in DB.", "red"))
        return

    temp_domain, real_domain = row
    domains = [temp_domain]
    if real_domain:
        domains.append(real_domain)

    domain_flags = " ".join(f"-d {d}" for d in domains)

    # Attempt to generate SSL certificates
    certbot_command = (
        f"certbot --nginx --non-interactive --agree-tos {domain_flags} "
        f"-m admin@{temp_domain} --redirect --expand"
    )
    result = os.system(certbot_command)

    if result != 0:
        os.system("nginx -t")  # Show detailed errors
        return

    # Reload NGINX after Certbot updates the configuration
    os.system("nginx -t && systemctl reload nginx")

    conn.close()

def test_app(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    if not row:
        print(colored("❌ App not found.", "red"))
        return

    temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass = row
    print(colored(f"\nTesting app '{app}':", "cyan"))

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

    print(f"📦 Testing SFTP connection for user: {sftp_user}")
    try:
        result = subprocess.call(["sftp", "-oBatchMode=no", "-oStrictHostKeyChecking=no", f"{sftp_user}@localhost"], stderr=subprocess.DEVNULL)
        print(colored("✅ SFTP Connection OK" if result == 0 else "❌ SFTP Connection Failed", "green" if result == 0 else "red"))
    except Exception as e:
        print(colored("❌ SFTP Connection Failed", "red"))

def list_apps():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT app, temp_domain, real_domain, db_type, db_name, db_user, sftp_user, port, created_at FROM apps")
    rows = c.fetchall()
    headers = ["App", "Temp Domain", "Real Domain", "DB Type", "DB Name", "DB User", "SFTP User", "API Port", "Created At"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    conn.close()

def delete_app(app):
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
    domains = [temp_domain]
    if new_domain:
        domains.append(new_domain)

    # Update nginx and certbot
    configure_nginx(app, domains)

    # Install SSL for the app
    install_ssl(app)

    # Update DB
    c.execute("UPDATE apps SET real_domain = ? WHERE app = ?", (new_domain, app))
    conn.commit()
    conn.close()

    print(colored(f"✅ Domain for '{app}' updated to '{new_domain}'", "green"))

def info_app(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM apps WHERE app = ?", (app,))
    row = c.fetchone()
    if not row:
        print(colored(f"❌ App '{app}' not found.", "red"))
        return

    app_name, temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, port, created_at = row

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} - App Information:", "yellow"))
    print(f"  🚀 App Name     : {colored(app_name, 'cyan')}")
    print(f"  🌐 Temp Domain  : {colored('https://' + temp_domain, 'green')}")
    print(f"  🌐 Real Domain  : {colored('https://' + real_domain if real_domain else 'None', 'green')}")
    print(f"  📦 SFTP User    : {sftp_user}")
    print(f"  🔑 SFTP Pass    : {sftp_pass}")
    print(f"  🛢️  DB Type      : {db_type}")
    print(f"  🗄️  DB Name      : {db_name}")
    print(f"  👤 DB User      : {db_user}")
    print(f"  🔐 DB Password  : {db_pass}")
    print(f"  🔌 API Port     : {port}")
    print(f"  🕒 Created At   : {created_at}\n")

    conn.close()

def main():
    init_db()
    parser = argparse.ArgumentParser(
        description=colored(f"Turboship v{TURBOSHIP_VERSION} - Multi-App Hosting Tool\n\nCommands:\n\ncreate: Create a new app\ntest: Run health checks for an app\nlist: List all created apps\ndelete: Delete an app completely\nmap-domain: Map real domain to existing app\ninfo: Display detailed information about an app", "cyan"),
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

    # Delete subcommand
    delete_parser = subparsers.add_parser("delete", help="Delete an app completely")
    delete_parser.add_argument("app", metavar="APP", help="App name to delete")

    # Map-domain subcommand
    map_domain_parser = subparsers.add_parser("map-domain", help="Map real domain to existing app")
    map_domain_parser.add_argument("app", metavar="APP", help="App name")
    map_domain_parser.add_argument("--domain", metavar="DOMAIN", help="Specify real domain")

    # Info subcommand
    info_parser = subparsers.add_parser("info", help="Display detailed information about an app")
    info_parser.add_argument("app", metavar="APP", help="App name to display information for")

    args = parser.parse_args()

    if not args.command or args.command == "interactive":
        try:
            while True:
                print("\nAvailable Commands:")
                print("1. Create App")
                print("2. Test App")
                print("3. List Apps")
                print("4. Delete App")
                print("5. Map Domain")
                print("6. Display App Info")
                print("7. Exit")

                choice = input("Enter your choice: ").strip()

                if choice == "1":
                    create_app()
                elif choice == "2":
                    app_name = input("Enter app name: ").strip()
                    test_app(app_name)
                elif choice == "3":
                    list_apps()
                elif choice == "4":
                    app_name = input("Enter app name: ").strip()
                    delete_app(app_name)
                elif choice == "5":
                    app_name = input("Enter app name: ").strip()
                    domain = input("Enter domain: ").strip()
                    map_domain(app_name, domain)
                elif choice == "6":
                    app_name = input("Enter app name: ").strip()
                    info_app(app_name)
                elif choice == "7":
                    print("Exiting interactive mode.")
                    break
                else:
                    print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\nExiting Turboship mode gracefully. Goodbye!")
            exit(0)
    else:
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
        elif args.command == "delete":
            delete_app(args.app)
        elif args.command == "map-domain":
            map_domain(args.app, args.domain)
        elif args.command == "info":
            info_app(args.app)
        else:
            print(colored("⚠️  No valid command given.\n", "yellow"))
            parser.print_help()

if __name__ == "__main__":
    main()
