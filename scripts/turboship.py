#!/usr/bin/env python3

import os
import subprocess

def create_project():
    print("\n📁 Create New Project")
    project_name = input("Enter project name: ").strip()
    username = input("Enter SFTP username: ").strip()
    db_type = input("Database type (mariadb/postgres): ").strip().lower()

    print(f"\nSetting up project: {project_name}")
    print(f" - Creating /var/www/{project_name}")
    subprocess.run(["sudo", "mkdir", "-p", f"/var/www/{project_name}"])
    subprocess.run(["sudo", "adduser", "--disabled-password", "--gecos", "", username])
    subprocess.run(["sudo", "chown", f"{username}:{username}", f"/var/www/{project_name}"])

    if db_type == "mariadb":
        db_name = input("Enter MariaDB database name: ").strip()
        db_user = input("Enter DB username: ").strip()
        db_pass = input("Enter DB password: ").strip()
        create_mariadb(db_name, db_user, db_pass)

    elif db_type == "postgres":
        db_name = input("Enter PostgreSQL database name: ").strip()
        db_user = input("Enter DB username: ").strip()
        db_pass = input("Enter DB password: ").strip()
        create_postgres(db_name, db_user, db_pass)
    
    else:
        print("⚠️ Invalid database type selected.")

def create_mariadb(db_name, db_user, db_pass):
    print("🔧 Creating MariaDB database...")
    sql = f"CREATE DATABASE {db_name}; CREATE USER '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}'; GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'localhost'; FLUSH PRIVILEGES;"
    subprocess.run(['sudo', 'mysql', '-e', sql])

def create_postgres(db_name, db_user, db_pass):
    print("🔧 Creating PostgreSQL database...")
    cmds = [
        f"CREATE DATABASE {db_name};",
        f"CREATE USER {db_user} WITH ENCRYPTED PASSWORD '{db_pass}';",
        f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"
    ]
    for cmd in cmds:
        subprocess.run(['sudo', '-u', 'postgres', 'psql', '-c', cmd])

def main():
    print("🚀 Welcome to Turboship CLI")
    print("1. Create New Project")
    print("2. Exit")
    choice = input("Choose an option: ").strip()

    if choice == "1":
        create_project()
    else:
        print("👋 Exiting...")

if __name__ == "__main__":
    main()
