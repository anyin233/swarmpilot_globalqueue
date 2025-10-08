#!/usr/bin/env python3
"""
GlobalQueue CLI 工具
使用 typer 实现命令行接口
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
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="服务监听地址"),
    port: int = typer.Option(8102, "--port", "-p", help="服务监听端口"),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="TaskInstance 配置文件路径",
        exists=True
    ),
    reload: bool = typer.Option(False, "--reload", help="启用热重载"),
    log_level: str = typer.Option("info", "--log-level", help="日志级别")
):
    """
    启动 GlobalQueue 服务

    示例:
        globalqueue start --host 0.0.0.0 --port 8102 --config task_instances.yaml
    """
    logger.info(f"Starting GlobalQueue on {host}:{port}")

    # 如果提供了配置文件，在启动后自动加载
    if config:
        logger.info(f"TaskInstance config will be loaded from: {config}")
        # 将配置路径设为环境变量，供 API 启动时读取
        import os
        os.environ["GLOBALQUEUE_CONFIG"] = str(config.absolute())

    # 启动 FastAPI 服务
    uvicorn.run(
        "api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )


@app.command()
def query(
    task_id: str = typer.Argument(..., help="要查询的任务ID"),
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API 地址"
    )
):
    """
    查询任务的转发目标信息

    示例:
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

        typer.echo(f"\n任务路由信息:")
        typer.echo(f"  任务ID:       {data['task_id']}")
        typer.echo(f"  模型名称:     {data['model_name']}")
        typer.echo(f"  目标地址:     {data['target_host']}")
        typer.echo(f"  目标端口:     {data['target_port']}")
        typer.echo(f"  转发时间:     {data['timestamp']}")
        typer.echo(f"  队列大小:     {data['queue_size']}")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            typer.echo(f"错误: 任务 {task_id} 未找到", err=True)
        else:
            typer.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"查询失败: {e}", err=True)
        sys.exit(1)


@app.command()
def info(
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API 地址"
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="以 JSON 格式输出"
    )
):
    """
    查询 GlobalQueue 的状态信息

    示例:
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
            typer.echo(f"\nGlobalQueue 状态信息:")
            typer.echo(f"  TaskInstance 总数: {data['total_task_instances']}")
            typer.echo(f"  模型总数:          {data['total_models']}")
            typer.echo(f"  活跃队列数:        {data['active_queues']}")
            typer.echo(f"\nTaskInstance 列表:")

            for ti in data['task_instances']:
                typer.echo(f"\n  UUID: {ti['uuid']}")
                typer.echo(f"  Host: {ti['host']}")
                typer.echo(f"  状态: {ti['status']}")
                typer.echo(f"  模型数量: {len(ti['models'])}")

                if ti['models']:
                    typer.echo(f"  模型列表:")
                    for model in ti['models']:
                        typer.echo(f"    - {model['model']} (端口: {model['port']}, 状态: {model['status']})")

    except requests.exceptions.ConnectionError:
        typer.echo(f"错误: 无法连接到 {api_url}", err=True)
        typer.echo("请确认 GlobalQueue 服务是否已启动", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"查询失败: {e}", err=True)
        sys.exit(1)


@app.command()
def load_config(
    config: Path = typer.Argument(..., help="TaskInstance 配置文件路径", exists=True),
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API 地址"
    )
):
    """
    从配置文件加载 TaskInstance 列表

    示例:
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
        typer.echo(f"成功: {data['message']}")

    except requests.exceptions.ConnectionError:
        typer.echo(f"错误: 无法连接到 {api_url}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"加载配置失败: {e}", err=True)
        sys.exit(1)


@app.command()
def update_queues(
    api_url: str = typer.Option(
        "http://localhost:8102",
        "--api-url",
        "-u",
        help="GlobalQueue API 地址"
    )
):
    """
    更新所有队列的状态信息

    示例:
        globalqueue update-queues
    """
    try:
        response = requests.post(f"{api_url}/queue/update", timeout=30)
        response.raise_for_status()

        data = response.json()
        typer.echo(f"成功: {data['message']}")
        typer.echo(f"更新的队列数: {data['queues_count']}")

    except requests.exceptions.ConnectionError:
        typer.echo(f"错误: 无法连接到 {api_url}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"更新队列失败: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
