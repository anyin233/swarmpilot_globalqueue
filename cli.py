#!/usr/bin/env python3
"""
GlobalQueue CLI Tool
Command-line interface implemented using typer
"""
import typer
import requests
import uvicorn
from pathlib import Path
from typing import Optional
from loguru import logger
import sys
import json

app = typer.Typer(help="SwarmPilot GlobalQueue CLI")


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Service listen address"),
    port: int = typer.Option(8102, "--port", "-p", help="Service listen port"),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="TaskInstance configuration file path",
        exists=True
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable hot reload"),
    log_level: str = typer.Option("info", "--log-level", help="Log level")
):
    """
    Start GlobalQueue service

    Example:
        globalqueue start --host 0.0.0.0 --port 8102 --config task_instances.yaml
    """
    logger.info(f"Starting GlobalQueue on {host}:{port}")

    # If config file provided, load it on startup
    if config:
        logger.info(f"TaskInstance config will be loaded from: {config}")
        # Set config path as environment variable for API to read on startup
        import os
        os.environ["GLOBALQUEUE_CONFIG"] = str(config.absolute())

    # Start FastAPI service
    uvicorn.run(
        "api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )


@app.command()
def query(
    task_id: str = typer.Argument(..., help="Task ID to query"),
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API address"
    )
):
    """
    Query task routing target information

    Example:
        globalqueue query abc123-def456 --api-url http://localhost:8102
    """
    try:
        response = requests.get(
            f"{api_url}/queue/query-target",
            params={"task_id": task_id},
            timeout=10
        )
        response.raise_for_status()

        data = response.json()

        typer.echo(f"\nTask Routing Information:")
        typer.echo(f"  Task ID:        {data['task_id']}")
        typer.echo(f"  Model Name:     {data['model_name']}")
        typer.echo(f"  Target Host:    {data['target_host']}")
        typer.echo(f"  Target Port:    {data['target_port']}")
        typer.echo(f"  Routing Time:   {data['timestamp']}")
        typer.echo(f"  Queue Size:     {data['queue_size']}")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            typer.echo(f"Error: Task {task_id} not found", err=True)
        else:
            typer.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Query failed: {e}", err=True)
        sys.exit(1)


@app.command()
def info(
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API address"
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output in JSON format"
    )
):
    """
    Query GlobalQueue status information

    Example:
        globalqueue info
        globalqueue info --json
    """
    try:
        response = requests.get(f"{api_url}/info", timeout=10)
        response.raise_for_status()

        data = response.json()

        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"\nGlobalQueue Status:")
            typer.echo(f"  Total TaskInstances: {data['total_task_instances']}")
            typer.echo(f"  Total Models:        {data['total_models']}")
            typer.echo(f"  Active Queues:       {data['active_queues']}")
            typer.echo(f"\nTaskInstance List:")

            for ti in data['task_instances']:
                typer.echo(f"\n  UUID: {ti['uuid']}")
                typer.echo(f"  Host: {ti['host']}")
                typer.echo(f"  Status: {ti['status']}")
                typer.echo(f"  Model Count: {len(ti['models'])}")

                if ti['models']:
                    typer.echo(f"  Models:")
                    for model in ti['models']:
                        typer.echo(f"    - {model['model']} (Port: {model['port']}, Status: {model['status']})")

    except requests.exceptions.ConnectionError:
        typer.echo(f"Error: Cannot connect to {api_url}", err=True)
        typer.echo("Please confirm GlobalQueue service is running", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Query failed: {e}", err=True)
        sys.exit(1)


@app.command()
def load_config(
    config: Path = typer.Argument(..., help="TaskInstance configuration file path", exists=True),
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API address"
    )
):
    """
    Load TaskInstance list from configuration file

    Example:
        globalqueue load-config task_instances.yaml
    """
    try:
        response = requests.post(
            f"{api_url}/config/load-task-instances",
            json={"config_path": str(config.absolute())},
            timeout=10
        )
        response.raise_for_status()

        data = response.json()
        typer.echo(f"Success: {data['message']}")

    except requests.exceptions.ConnectionError:
        typer.echo(f"Error: Cannot connect to {api_url}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Failed to load config: {e}", err=True)
        sys.exit(1)


@app.command()
def update_queues(
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API address"
    )
):
    """
    Update status information for all queues

    Example:
        globalqueue update-queues
    """
    try:
        response = requests.post(f"{api_url}/queue/update", timeout=30)
        response.raise_for_status()

        data = response.json()
        typer.echo(f"Success: {data['message']}")
        typer.echo(f"Updated queues: {data['queues_count']}")

    except requests.exceptions.ConnectionError:
        typer.echo(f"Error: Cannot connect to {api_url}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Failed to update queues: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
