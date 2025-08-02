# turboship.py - Turboship v0.3
import os
import subprocess
import random
import string
import csv
import socket
import re
import sqlite3
from datetime import datetime

TURBOSHIP_VERSION = "0.3"
DB_PATH = "/opt/turboship/turboship.db"


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
    print("Choose database type:")
    print("1. MariaDB")
    print("2. PostgreSQL")
    choice = input("Enter choice [1/2]: ").strip()
    if choice == "1":
        return "mariadb"
    elif choice == "2":
        return "postgres"
    else:
        print("Invalid input. Try again.")
        return prompt_database()


def create_project(dry_run=False):
    project = input("Enter project name: ").strip()
    if not validate_project_name(project):
        print("Invalid project name. Only alphanumeric characters, dashes and underscores allowed.")
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

    print(f"\nTurboship v{TURBOSHIP_VERSION} - Project Summary:")
    print(f"  Project Name : {project}")
    print(f"  Domain       : https://{domain}")
    print(f"  SFTP User    : {sftp_user}")
    print(f"  SFTP Pass    : {sftp_pass}")
    print(f"  DB Type      : {db_type}")
    print(f"  DB Name      : {db_name}")
    print(f"  DB User      : {db_user}")
    print(f"  DB Password  : {db_pass}")
    print(f"  Created At   : {now}\n")

    if dry_run:
        return

    os.makedirs(f"/var/www/{project}/htdocs", exist_ok=True)
    os.system(f"adduser --disabled-password --gecos '' {sftp_user}")
    subprocess.run(['bash', '-c', f"echo '{sftp_user}:{sftp_pass}' | chpasswd"])
    os.system(f"usermod -d /var/www/{project}/htdocs {sftp_user}")
    os.system(f"chown -R {sftp_user}:{sftp_user} /var/www/{project}")

    if db_type == "mariadb":
        create_mariadb_user(db_user, db_pass, db_name)
    elif db_type == "postgres":
        create_postgres_user(db_user, db_pass, db_name)

    configure_nginx(project, domain)
    install_ssl(domain)
    save_to_db(project, domain, db_type, db_name, db_user, db_pass, sftp_user, now)


def create_mariadb_user(user, password, db):
    sql = f"""
    CREATE DATABASE IF NOT EXISTS {db};
    CREATE USER IF NOT EXISTS '{user}'@'localhost' IDENTIFIED BY '{password}';
    GRANT ALL PRIVILEGES ON {db}.* TO '{user}'@'localhost';
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


def save_to_db(project, domain, db_type, db_name, db_user, db_pass, sftp_user, created_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (project, domain, db_type, db_name, db_user, db_pass, sftp_user, created_at))
    conn.commit()
    conn.close()


def list_projects():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    if not rows:
        print("No projects found.")
    for row in rows:
        print(f"Project: {row[0]}, Domain: {row[1]}, DB: {row[2]} ({row[3]}), SFTP: {row[6]}, Created: {row[7]}")
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

    sftp_user = result[6]

    # Backup
    backup = input("Do you want to take a backup of the project folder? (y/N): ").strip().lower()
    if backup == 'y':
        os.system(f"tar czf /opt/turboship/backups/{project}.tar.gz /var/www/{project}")

    # Remove nginx
    os.remove(f"/etc/nginx/sites-available/{project}")
    os.unlink(f"/etc/nginx/sites-enabled/{project}")
    os.system("nginx -t && systemctl reload nginx")

    # Remove files and user
    os.system(f"rm -rf /var/www/{project}")
    os.system(f"deluser --remove-home {sftp_user}")

    # Remove from DB
    c.execute("DELETE FROM projects WHERE project = ?", (project,))
    conn.commit()
    conn.close()

    print(f"Project '{project}' removed successfully.")


def main():
    init_db()
    print(f"Turboship v{TURBOSHIP_VERSION}: Server Management CLI")
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
        print("Invalid option.")


if __name__ == "__main__":
    main()
