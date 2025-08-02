# turboship.py - Turboship v0.2
import os
import subprocess
import random
import string
import csv
import socket


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
    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([project, domain, db_type, db_name, db_user, db_pass, sftp_user])


if __name__ == "__main__":
    create_project()
