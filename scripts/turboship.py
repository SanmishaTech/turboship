# turboship_v0.5.py - Turboship v0.5 with SFTP chroot, test command, and custom domain support
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

TURBOSHIP_VERSION = "0.5"
DB_PATH = "/opt/turboship/turboship.db"
GITHUB_URL = "https://github.com/SanmishaTech/turboship"


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            project TEXT PRIMARY KEY,
            domain TEXT,
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
    return subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()


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
    domain = custom_domain if custom_domain else f"{project}.{get_public_ip()}.sslip.io"
    now = datetime.now().isoformat()

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} - Project Summary:", "yellow"))
    print(f"  🚀 Project Name : {colored(project, 'cyan')}")
    print(f"  🌐 Domain       : {colored('https://' + domain, 'green')}")
    print(f"  📦 SFTP User    : {sftp_user}")
    print(f"  🔑 SFTP Pass    : {sftp_pass}")
    print(f"  📂 DB Type      : {db_type}")
    print(f"  💾 DB Name      : {db_name}")
    print(f"  👤 DB User      : {db_user}")
    print(f"  🔐 DB Password  : {db_pass}")
    print(f"  🕒 Created At   : {now}\n")

    project_path = f"/var/www/{project}/htdocs"
    os.makedirs(project_path, exist_ok=True)

    # Landing page
    with open("landing_template.html") as src:
        content = src.read().replace("{project}", project).replace("{github}", GITHUB_URL)
    with open(os.path.join(project_path, "index.html"), "w") as dst:
        dst.write(content)

    # Create chrooted SFTP user
    os.system("groupadd sftpusers || true")
    os.system(f"useradd -m -d /var/www/{project} -s /usr/sbin/nologin -G sftpusers {sftp_user}")
    subprocess.run(["bash", "-c", f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])
    os.makedirs(f"/var/www/{project}/htdocs", exist_ok=True)
    os.chown(f"/var/www/{project}/htdocs", 0, 0)  # owned by root
    os.system(f"chown -R {sftp_user}:{sftp_user} /var/www/{project}/htdocs")

    sshd_config_path = "/etc/ssh/sshd_config"
    match_block = f"""
Match Group sftpusers
    ChrootDirectory /var/www/%u
    ForceCommand internal-sftp
    X11Forwarding no
    AllowTcpForwarding no
"""
    with open(sshd_config_path, "r") as f:
        if "Match Group sftpusers" not in f.read():
            with open(sshd_config_path, "a") as fa:
                fa.write(match_block)
    os.system("systemctl restart sshd")

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
    configure_nginx(project, domain)
    install_ssl(domain)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (project, domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, now))
    conn.commit()
    conn.close()


def configure_nginx(project, domain):
    conf = f"""
server {{
    listen 80;
    server_name {domain};
    root /var/www/{project}/htdocs;
    index index.html;
    location / {{ try_files $uri $uri/ =404; }}
}}
"""
    path = f"/etc/nginx/sites-available/{project}"
    with open(path, "w") as f:
        f.write(conf)
    os.symlink(path, f"/etc/nginx/sites-enabled/{project}")
    os.system("nginx -t && systemctl reload nginx")


def install_ssl(domain):
    os.system(f"certbot --nginx --non-interactive --agree-tos -d {domain} -m admin@{domain} --redirect")


def test_project(project):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT domain, db_type, db_name, db_user, db_pass FROM projects WHERE project = ?", (project,))
    row = c.fetchone()
    if not row:
        print(colored("❌ Project not found.", "red"))
        return

    domain, db_type, db_name, db_user, db_pass = row
    print(colored(f"\nTesting project '{project}':", "cyan"))

    # Test domain
    print(f"🌐 Testing domain: {domain}")
    try:
        socket.gethostbyname(domain)
        print(colored("✅ DNS Resolved", "green"))
    except:
        print(colored("❌ DNS failed", "red"))

    # Test DB connection
    if db_type == "mariadb":
        result = subprocess.call(["mysql", "-h", "127.0.0.1", "-u", db_user, f"-p{db_pass}", "-e", "SHOW DATABASES;"])
    elif db_type == "postgres":
        env = os.environ.copy()
        env['PGPASSWORD'] = db_pass
        result = subprocess.call(["psql", "-U", db_user, "-d", db_name, "-c", "\l"], env=env)

    print(colored("✅ DB Connection OK" if result == 0 else "❌ DB Connection Failed", "green" if result == 0 else "red"))


def list_projects():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    headers = ["Project", "Domain", "DB Type", "DB Name", "DB User", "DB Pass", "SFTP User", "SFTP Pass", "Created"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    conn.close()


def main():
    init_db()
    parser = argparse.ArgumentParser(description="Turboship v0.5 - Multi-Project Hosting Tool")
    parser.add_argument("--create", action="store_true", help="Create new project")
    parser.add_argument("--test", metavar="PROJECT", help="Test existing project")
    parser.add_argument("--list", action="store_true", help="List all projects")
    parser.add_argument("--domain", metavar="DOMAIN", help="Use custom domain for project")
    args = parser.parse_args()

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} CLI", "blue"))

    if args.create:
        create_project(custom_domain=args.domain)
    elif args.test:
        test_project(args.test)
    elif args.list:
        list_projects()
    else:
        print("Use --create, --test <project>, or --list")


if __name__ == "__main__":
    main()
