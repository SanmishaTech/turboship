import os
import sqlite3
import subprocess
import shutil
from datetime import datetime
from tabulate import tabulate
from rich import print
from rich.prompt import Prompt
from rich.console import Console
from rich.panel import Panel

DB_FILE = "/opt/turboship/turboship.db"
PROJECTS_ROOT = "/var/www"

console = Console()

def connect_db():
    return sqlite3.connect(DB_FILE)

def remove_project():
    project_name = Prompt.ask("Enter project name to remove")

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE name = ?", (project_name,))
    row = cursor.fetchone()

    if not row:
        print(f"[red]Project '{project_name}' not found.[/red]")
        return

    _, name, domain, sftp_user, sftp_pass, db_type, db_name, db_user, db_pass, created_at = row

    # Confirm deletion
    if Prompt.ask(f"Are you sure you want to delete project [bold]{name}[/bold]? (y/n)").lower() != 'y':
        print("[yellow]Deletion cancelled.[/yellow]")
        return

    print("[cyan]Backing up project files (optional)...[/cyan]")
    # Add optional backup logic here if needed

    # Delete project directory
    project_dir = os.path.join(PROJECTS_ROOT, name)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
        print(f"[green]Deleted project directory: {project_dir}[/green]")

    # Remove system user (SFTP)
    subprocess.run(["sudo", "deluser", "--remove-home", sftp_user])
    print(f"[green]Deleted system user: {sftp_user}[/green]")

    # Remove database and user based on type
    if db_type == "mariadb":
        for host in ['%', 'localhost']:
            subprocess.run(["sudo", "mysql", "-e", f"DROP USER IF EXISTS `{db_user}`@'{host}';"])
        subprocess.run(["sudo", "mysql", "-e", f"DROP DATABASE IF EXISTS `{db_name}`;"])
        print(f"[green]Deleted MariaDB database and user[/green]")

    elif db_type == "postgresql":
        subprocess.run(["sudo", "-u", "postgres", "dropdb", "--if-exists", db_name])
        subprocess.run(["sudo", "-u", "postgres", "dropuser", "--if-exists", db_user])
        print(f"[green]Deleted PostgreSQL database and user[/green]")

    # Remove Nginx config
    nginx_path = f"/etc/nginx/sites-available/{name}"
    nginx_link = f"/etc/nginx/sites-enabled/{name}"
    if os.path.exists(nginx_path):
        os.remove(nginx_path)
    if os.path.exists(nginx_link):
        os.remove(nginx_link)
    subprocess.run(["sudo", "nginx", "-s", "reload"])
    print(f"[green]Removed nginx config[/green]")

    # Remove from SQLite
    cursor.execute("DELETE FROM projects WHERE name = ?", (project_name,))
    conn.commit()
    conn.close()

    print(Panel.fit(f"[bold green]✅ Project '{name}' removed successfully![/bold green]", title="Turboship"))

def list_projects():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, domain, sftp_user, db_type, db_name, db_user, created_at FROM projects")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("[yellow]No projects found.[/yellow]")
        return

    headers = ["Project", "Domain", "SFTP User", "DB Type", "DB Name", "DB User", "Created"]
    table = tabulate(rows, headers=headers, tablefmt="fancy_grid")
    print(table)

if __name__ == "__main__":
    console.rule("[bold blue]Turboship Project Manager v0.4")
    options = {
        "1": ("List all projects", list_projects),
        "2": ("Remove a project", remove_project)
    }

    for key, (desc, _) in options.items():
        print(f"[{key}] {desc}")

    choice = Prompt.ask("Choose an option", choices=options.keys())
    options[choice][1]()
