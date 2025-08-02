# turboship.py - Turboship v0.4
import os
import subprocess
import random
import string
import csv
import socket
import re
import sqlite3
from datetime import datetime
from tabulate import tabulate
from termcolor import colored
from pyfiglet import figlet_format

TURBOSHIP_VERSION = "0.4"
DB_PATH = "/opt/turboship/turboship.db"
GITHUB_URL = "https://github.com/SanmishaTech/turboship"


# Ensure database exists
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
    if choice == "1":
        return "mariadb"
    elif choice == "2":
        return "postgres"
    else:
        print(colored("Invalid input. Try again.", "red"))
        return prompt_database()


def create_project(dry_run=False):
    project = input("Enter project name: ").strip()
    if not validate_project_name(project):
        print(colored("Invalid project name. Only alphanumeric characters, dashes and underscores allowed.", "red"))
        return

    db_type = prompt_database()

    sftp_user = f"{project}_sftp"
    db_user = f"{project}_dbu"
    db_pass = generate_password()
    sftp_pass = generate_password()
    db_name = f"{project}_db"

    public_ip = get_public_ip()
    domain = f"{project}.{public_ip}.sslip.io"

    now = datetime.now().isoformat()

    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION} - Project Summary:", "yellow"))
    print(f"  🚀 Project Name : {colored(project, 'cyan')}")
    print(f"  🌐 Domain       : {colored('https://' + domain, 'green')}")
    print(f"  📦 SFTP User    : {sftp_user}")
    print(f"  🔑 SFTP Pass    : {sftp_pass}")
    print(f"  🛢️  DB Type      : {db_type}")
    print(f"  🗄️  DB Name      : {db_name}")
    print(f"  👤 DB User      : {db_user}")
    print(f"  🔐 DB Password  : {db_pass}")
    print(f"  🕒 Created At   : {now}\n")

    if dry_run:
        return

    project_path = f"/var/www/{project}/htdocs"
    os.makedirs(project_path, exist_ok=True)

    # Copy template HTML to index.html
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "landing_template.html")
    with open(template_path) as src:
        content = src.read().replace("{project}", project).replace("{github}", GITHUB_URL)
    with open(os.path.join(project_path, "index.html"), "w") as dst:
        dst.write(content)

    os.system(f"adduser --disabled-password --gecos '' {sftp_user}")
    subprocess.run(['bash', '-c', f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])
    os.system(f"usermod -d {project_path} {sftp_user}")
    os.system(f"chown -R {sftp_user}:{sftp_user} /var/www/{project}")

    if db_type == "mariadb":
        create_mariadb_user(db_user, db_pass, db_name)
    elif db_type == "postgres":
        create_postgres_user(db_user, db_pass, db_name)

    configure_nginx(project, domain)
    install_ssl(domain)
    save_to_db(project, domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, now)


def create_mariadb_user(user, password, db):
    sql = f"""
    CREATE DATABASE IF NOT EXISTS {db};
    CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{password}';
    GRANT ALL PRIVILEGES ON {db}.* TO '{user}'@'%';
    FLUSH PRIVILEGES;
    """
    subprocess.run(['mysql', '-u', 'root', '-e', sql])


def create_postgres_user(user, password, db):
    commands = [
        f"CREATE USER {user} WITH PASSWORD '{password}';",
        f"CREATE DATABASE {db} OWNER {user};"
    ]
    for cmd in commands:
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', cmd])


def configure_nginx(project, domain):
    nginx_conf = f"""
server {{
    listen 80;
    server_name {domain};

    root /var/www/{project}/htdocs;
    index index.html index.htm;

    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""
    conf_path = f"/etc/nginx/sites-available/{project}"
    with open(conf_path, "w") as f:
        f.write(nginx_conf)
    os.symlink(conf_path, f"/etc/nginx/sites-enabled/{project}")
    os.system("nginx -t && systemctl reload nginx")


def install_ssl(domain):
    os.system(f"certbot --nginx --non-interactive --agree-tos -d {domain} -m admin@{domain} --redirect")


def save_to_db(project, domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, created_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (project, domain, db_type, db_name, db_user, db_pass, sftp_user, sftp_pass, created_at))
    conn.commit()
    conn.close()


def list_projects():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    if not rows:
        print(colored("No projects found.", "red"))
    else:
        headers = ["Project", "Domain", "DB Type", "DB Name", "DB User", "DB Pass", "SFTP User", "SFTP Pass", "Created At"]
        print(colored("\nYour Projects:", "green"))
        print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    conn.close()


def remove_project():
    project = input("Enter the project name to remove: ").strip()
    confirm = input(f"Are you sure you want to remove '{project}'? This cannot be undone. (y/N): ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE project = ?", (project,))
    result = c.fetchone()
    if not result:
        print("Project not found in database.")
        conn.close()
        return

    _, _, db_type, db_name, db_user, db_pass, sftp_user, _, _ = result

    backup = input("Do you want to take a backup of the project folder and database? (y/N): ").strip().lower()
    if backup == 'y':
        backup_dir = f"/opt/turboship/backups/{project}"
        os.makedirs(backup_dir, exist_ok=True)

        # Backup project files
        os.system(f"tar czf {backup_dir}/{project}_files.tar.gz /var/www/{project}")

        # Backup database
        if db_type == "mariadb":
            os.system(f"mysqldump -u {db_user} -p'{db_pass}' {db_name} > {backup_dir}/{db_name}.sql")
        elif db_type == "postgres":
            os.system(f"sudo -u postgres pg_dump {db_name} > {backup_dir}/{db_name}.sql")

        print(colored(f"📦 Backup saved at: {backup_dir}", "blue"))

    # Remove nginx
    os.remove(f"/etc/nginx/sites-available/{project}")
    os.unlink(f"/etc/nginx/sites-enabled/{project}")
    os.system("nginx -t && systemctl reload nginx")

    # Remove project folder and sftp user
    os.system(f"rm -rf /var/www/{project}")
    os.system(f"deluser --remove-home {sftp_user}")

    # Drop DB user and DB
    if db_type == "mariadb":
        for host in ['%', 'localhost']:
            subprocess.run([
                "mysql", "-u", "root", "-e",
                f"DROP USER IF EXISTS `{db_user}`@'{host}';"
            ])
        subprocess.run([
            "mysql", "-u", "root", "-e",
            f"DROP DATABASE IF EXISTS `{db_name}`;"
        ])
    elif db_type == "postgres":
        subprocess.run([
            "sudo", "-u", "postgres", "dropdb", "--if-exists", db_name
        ])
        subprocess.run([
            "sudo", "-u", "postgres", "dropuser", "--if-exists", db_user
        ])

    # Delete from SQLite
    c.execute("DELETE FROM projects WHERE project = ?", (project,))
    conn.commit()
    conn.close()

    print(colored(f"✅ Project '{project}' removed successfully.", "green"))


def main():
    init_db()
    print(colored(figlet_format("Turboship"), "green"))
    print(colored(f"Turboship v{TURBOSHIP_VERSION}: Server Management CLI", "blue"))
    print("1. Create Project")
    print("2. Remove Project")
    print("3. List Projects")
    print("4. Dry Run (Preview Setup)")
    action = input("Choose action [1/2/3/4]: ").strip()

    if action == "1":
        create_project()
    elif action == "2":
        remove_project()
    elif action == "3":
        list_projects()
    elif action == "4":
        create_project(dry_run=True)
    else:
        print(colored("Invalid option.", "red"))


if __name__ == "__main__":
    main()
