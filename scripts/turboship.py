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
        CREATE TABLE IF NOT EXISTS projects (
            project TEXT PRIMARY KEY,
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

def validate_project_name(name):
    return re.match("^[a-zA-Z0-9_-]+$", name) is not None

def prompt_database():
    print(colored("Choose database type:", "cyan"))
    print("1. MariaDB")
    print("2. PostgreSQL")
    choice = input("Enter choice [1/2]: ").strip()
    return "mariadb" if choice == "1" else "postgres"

def create_project(custom_domain=None):
    project = input("Enter project name: ").strip()
    if not validate_project_name(project):
        print(colored("Invalid project name. Use only letters, numbers, dashes, underscores.", "red"))
        return

    db_type = prompt_database()
    sftp_user = f"{project}_sftp"
    db_user = f"{project}_dbu"
    db_pass = generate_password()
    sftp_pass = generate_password()
    db_name = f"{project}_db"
    temp_domain = f"{project}.{get_public_ip()}.sslip.io"
    real_domain = custom_domain.strip() if custom_domain else ""
    now = datetime.now().isoformat()

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} - Project Summary:", "yellow"))
    print(f"  🚀 Project Name : {colored(project, 'cyan')}")
    print(f"  🌐 Temp Domain  : {colored('https://' + temp_domain, 'green')}")
    if real_domain:
        print(f"  🏷️ Real Domain  : {colored('https://' + real_domain, 'green')}")
    print(f"  📦 SFTP User    : {sftp_user}")
    print(f"  🔑 SFTP Pass    : {sftp_pass}")
    print(f"  🛢️  DB Type      : {db_type}")
    print(f"  🗄️  DB Name      : {db_name}")
    print(f"  👤 DB User      : {db_user}")
    print(f"  🔐 DB Password  : {db_pass}")
    print(f"  🕒 Created At   : {now}\n")

    # Directory structure
    project_root = f"/var/www/{sftp_user}"
    project_path = os.path.join(project_root, "htdocs")
    os.makedirs(project_path, exist_ok=True)

    # Landing page
    landing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing_template.html")
    if os.path.exists(landing_path):
        with open(landing_path) as src:
            content = src.read().replace("{project}", project).replace("{github}", GITHUB_URL)
        with open(os.path.join(project_path, "index.html"), "w") as dst:
            dst.write(content)
    else:
        print(colored("⚠️ landing_template.html not found — skipping landing page copy.", "yellow"))


    # Create user with SSH + SFTP (no chroot)
    os.system(f"useradd -m -d /var/www/{project} -s /bin/bash {sftp_user}")
    subprocess.run(["bash", "-c", f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])

    # Ensure project directory exists and set permissions
    os.makedirs(project_path, exist_ok=True)
    os.system(f"chown -R {sftp_user}:{sftp_user} /var/www/{project}")

    # Database
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

    # Nginx + SSL
    configure_nginx(project, [temp_domain])
    install_ssl(temp_domain)

    if real_domain:
        configure_nginx(project, [temp_domain, real_domain])
        install_ssl(real_domain)

    # Save in SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO projects 
        (project, temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (project, temp_domain, real_domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, now))
    conn.commit()
    conn.close()

def configure_nginx(project, domains):
    if isinstance(domains, str):
        domains = [domains]
    server_names = " ".join(domains)
    root_path = f"/var/www/{project}/htdocs"

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

    # Ensure challenge directory exists
    os.makedirs(os.path.join(root_path, ".well-known", "acme-challenge"), exist_ok=True)

    # Reload nginx
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT temp_domain, real_domain, db_type, db_name, db_user, sftp_user FROM projects WHERE project=?", (project,))
    row = c.fetchone()
    if not row:
        print(colored("❌ Project not found.", "red"))
        return

    temp_domain, real_domain, db_type, db_name, db_user, sftp_user = row
    domains = [temp_domain] + ([real_domain] if real_domain else [])

    print(colored(f"⚠️ Removing project: {project}", "red"))
    confirm = input("Are you sure? This cannot be undone. (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return

    # Remove from SQLite
    c.execute("DELETE FROM projects WHERE project=?", (project,))
    conn.commit()
    conn.close()

    # Remove Nginx
    os.remove(f"/etc/nginx/sites-available/{project}")
    os.remove(f"/etc/nginx/sites-enabled/{project}")
    os.system("nginx -t && systemctl reload nginx")

    # Remove SSL Cert
    for d in domains:
        os.system(f"certbot delete --cert-name {d}")

    # Delete SFTP user
    os.system(f"userdel -r {sftp_user} || true")

    # Drop DB
    if db_type == "mariadb":
        subprocess.run(["mysql", "-u", "root", "-e",
                       f"DROP DATABASE IF EXISTS {db_name}; DROP USER IF EXISTS '{db_user}'@'%';"])
    elif db_type == "postgres":
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c',
                       f"DROP DATABASE IF EXISTS {db_name};"])
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c',
                       f"DROP USER IF EXISTS {db_user};"])

    # Delete project directory
    os.system(f"rm -rf /var/www/{project}")

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
        description=colored("Turboship v0.7 - Multi-Project Hosting Tool", "cyan"),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("--create", action="store_true",
                        help="Create a new project with optional real domain\n  Example: --create --domain yourdomain.com")
    parser.add_argument("--test", metavar="PROJECT",
                        help="Run health checks for a project\n  Example: --test myproject")
    parser.add_argument("--list", action="store_true",
                        help="List all created projects in a table")
    parser.add_argument("--remove", metavar="PROJECT",
                        help="Remove a project completely (with warning)\n  Example: --remove myproject")
    parser.add_argument("--domain", metavar="DOMAIN",
                        help="(Used with --create or --map-domain) Specify real domain\n  Example: --create --domain myapp.sanmisha.com")
    parser.add_argument("--map-domain", metavar="PROJECT",
                        help="Map real domain to existing project\n  Example: --map-domain myproject --domain mydomain.com")

    args = parser.parse_args()

    # Banner
    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} CLI", "blue"))

    # Command Handling
    if args.create:
        create_project(custom_domain=args.domain)
    elif args.test:
        test_project(args.test)
    elif args.list:
        list_projects()
    elif args.remove:
        remove_project(args.remove)
    elif args.map_domain and args.domain:
        map_domain(args.map_domain, args.domain)
    else:
        print(colored("⚠️  No valid command given.\n", "yellow"))
        parser.print_help()

if __name__ == "__main__":
    main()
