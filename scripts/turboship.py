# turboship.py - Turboship v0.2.1
import os
import subprocess
import random
import string
import csv
import socket
from datetime import datetime


def get_public_ip():
    return subprocess.check_output("curl -s ifconfig.me", shell=True).decode().strip()


def generate_password(length=12):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


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


def validate_project_name(name):
    return name.replace('-', '').replace('_', '').isalnum()


def log_action(action, project):
    log_file = "/opt/turboship/audit.log"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, 'a') as f:
        f.write(f"[{datetime.now()}] {action}: {project}\n")


def create_project(dry_run=False):
    project = input("Enter project name: ").strip()
    if not validate_project_name(project):
        print("Invalid project name. Only letters, numbers, hyphens, and underscores allowed.")
        return

    db_type = prompt_database()

    sftp_user = f"{project}_sftp"
    db_user = f"{project}_dbu"
    db_pass = generate_password()
    db_name = f"{project}_db"

    public_ip = get_public_ip()
    domain = f"{project}.{public_ip}.sslip.io"

    if dry_run:
        print("\n[DRY RUN] These actions would be performed:")
    print(f"\nGenerated Domain: https://{domain}")
    print(f"SFTP User: {sftp_user}")
    print(f"Database Type: {db_type}")
    print(f"Database Name: {db_name}")
    print(f"DB User: {db_user}")
    print(f"DB Password: {db_pass}")

    if dry_run:
        return

    os.makedirs(f"/var/www/{project}/htdocs", exist_ok=True)
    os.system(f"adduser --disabled-password --gecos '' {sftp_user}")
    os.system(f"chown -R {sftp_user}:{sftp_user} /var/www/{project}")

    if db_type == "mariadb":
        create_mariadb_user(db_user, db_pass, db_name)
    elif db_type == "postgres":
        create_postgres_user(db_user, db_pass, db_name)

    configure_nginx(project, domain)
    install_ssl(domain)
    save_to_csv(project, domain, db_type, db_name, db_user, db_pass, sftp_user)
    log_action("CREATED", project)


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


def save_to_csv(project, domain, db_type, db_name, db_user, db_pass, sftp_user):
    csv_file = "/opt/turboship/project_registry.csv"
    os.makedirs(os.path.dirname(csv_file), exist_ok=True)
    file_exists = os.path.isfile(csv_file)
    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["project", "domain", "db_type", "db_name", "db_user", "db_pass", "sftp_user"])
        writer.writerow([project, domain, db_type, db_name, db_user, db_pass, sftp_user])


def remove_project():
    project = input("Enter the project name to remove: ").strip()
    confirm = input(f"Are you sure you want to remove '{project}'? This cannot be undone. (y/N): ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        return

    # Backup files before deletion (optional enhancement)
    backup_dir = f"/opt/turboship/backups/{project}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    os.system(f"cp -r /var/www/{project} {backup_dir} 2>/dev/null")

    # Remove NGINX conf
    nginx_path = f"/etc/nginx/sites-available/{project}"
    if os.path.exists(nginx_path):
        os.remove(nginx_path)
    enabled_link = f"/etc/nginx/sites-enabled/{project}"
    if os.path.islink(enabled_link):
        os.unlink(enabled_link)
    os.system("nginx -t && systemctl reload nginx")

    # Remove project files
    os.system(f"rm -rf /var/www/{project}")

    # Remove user
    os.system(f"deluser --remove-home {project}_sftp")

    # Remove from CSV
    csv_file = "/opt/turboship/project_registry.csv"
    lines = []
    if os.path.exists(csv_file):
        with open(csv_file, 'r') as f:
            reader = csv.reader(f)
            lines = list(reader)
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            for row in lines:
                if row and row[0] != project:
                    writer.writerow(row)

    log_action("REMOVED", project)
    print(f"Project '{project}' removed successfully.")


def list_projects():
    csv_file = "/opt/turboship/project_registry.csv"
    if not os.path.exists(csv_file):
        print("No projects found.")
        return
    with open(csv_file, 'r') as f:
        print(f.read())


if __name__ == "__main__":
    print("Turboship: Server Management CLI")
    print("1. Create Project")
    print("2. Remove Project")
    print("3. List Projects")
    print("4. Dry Run (Create Project Preview)")
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
