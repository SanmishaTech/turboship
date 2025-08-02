# turboship.py - Turboship v0.3
import os
import subprocess
import random
import string
import csv
import socket
import shutil

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

def create_project():
    print("\n=== Create New Project ===")
    project = input("Enter project name: ").strip()
    db_type = prompt_database()

    sftp_user = f"{project}_dev"
    db_user = f"{project}_dbu"
    db_pass = generate_password()
    db_name = f"{project}_db"

    public_ip = get_public_ip()
    domain = f"{project}.{public_ip}.sslip.io"

    print(f"\nGenerated Domain: https://{domain}")
    print(f"SFTP User: {sftp_user}\nDB User: {db_user}\nDB Password: {db_pass}\n")

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

def backup_project(project):
    backup_path = f"/opt/turboship/backups/{project}.tar.gz"
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.make_archive(backup_path.replace(".tar.gz", ""), 'gztar', f"/var/www/{project}")
    print(f"Backup created at: {backup_path}")

def remove_project():
    print("\n=== Remove Project ===")
    project = input("Enter the project name to remove: ").strip()
    confirm = input(f"Are you sure you want to remove '{project}'? This cannot be undone. (y/N): ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        return

    backup = input("Do you want to create a backup before deletion? (y/N): ").strip().lower()
    if backup == 'y':
        backup_project(project)

    nginx_path = f"/etc/nginx/sites-available/{project}"
    if os.path.exists(nginx_path):
        os.remove(nginx_path)
    enabled_link = f"/etc/nginx/sites-enabled/{project}"
    if os.path.islink(enabled_link):
        os.unlink(enabled_link)
    os.system("nginx -t && systemctl reload nginx")

    os.system(f"rm -rf /var/www/{project}")
    os.system(f"deluser --remove-home {project}_dev")

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

    print(f"Project '{project}' removed successfully.")

def list_projects():
    print("\n=== Project List ===")
    csv_file = "/opt/turboship/project_registry.csv"
    if not os.path.exists(csv_file):
        print("No projects found.")
        return

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            print(f"- {row['project']} → {row['domain']} ({row['db_type']})")

if __name__ == "__main__":
    print("\n=== Turboship: Server Management CLI ===")
    print("1. Create Project")
    print("2. Remove Project")
    print("3. List Projects")
    action = input("Choose action [1/2/3]: ").strip()

    if action == "1":
        create_project()
    elif action == "2":
        remove_project()
    elif action == "3":
        list_projects()
    else:
        print("Invalid option.")
