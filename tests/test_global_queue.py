#!/usr/bin/env python3
"""
测试 GlobalMsgQueue 的基本功能 (Updated for Strategy Pattern)
"""
from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage
from strategy import ShortestQueueStrategy
from uuid import uuid4
from loguru import logger
import time

def main():
    logger.info("=== 测试 GlobalMsgQueue (Strategy Pattern) ===")

    # 1. 初始化 GlobalMsgQueue
    logger.info("1. 初始化 GlobalMsgQueue")
    queue = SwarmPilotGlobalMsgQueue()

    # 2. 加载 Task Instance
    logger.info("2. 加载 Task Instance")
    queue.load_task_instance_from_config("task_instances.yaml")

    # 等待模型完全启动
    logger.info("等待 5 秒让模型完全启动...")
    time.sleep(5)

    # 3. 显示当前策略信息
    logger.info(f"3. 当前使用的策略: {queue.strategy.__class__.__name__}")
    logger.info(f"已加载 {len(queue.taskinstances)} 个 Task Instance")

    # 4. 测试任务分发
    logger.info("4. 测试任务分发")

    # 创建一个测试任务
    test_task = GlobalRequestMessage(
        model_id="easyocr",
        input_data={},
        input_features={
            "metadata": {
                "hardware": "GPU_RTX_A6000",
                "image_width": 1920,
                "image_height": 1080,
                "long_side": 1920
            }
        },
        uuid=uuid4()
    )

    logger.info(f"发送测试任务: {test_task.uuid}")
    response = queue.enqueue(test_task)
    logger.info(f"任务已入队: task_id={response.task_id}, queue_size={response.queue_size}")

    # 5. 查看路由信息
    logger.info("5. 查看路由信息")
    routing_info = queue.get_last_routing_info()
    logger.info(f"  - 目标模型: {routing_info['model_name']}")
    logger.info(f"  - 目标主机: {routing_info['target_host']}")
    logger.info(f"  - 目标端口: {routing_info['target_port']}")
    logger.info(f"  - TaskInstance UUID: {routing_info['ti_uuid']}")

    # 6. 测试多个任务连续分发
    logger.info("6. 测试多个任务连续分发")
    for i in range(3):
        task = GlobalRequestMessage(
            model_id="easyocr",
            input_data={},
            input_features={
                "metadata": {
                    "hardware": "GPU_RTX_A6000",
                    "image_width": 1920,
                    "image_height": 1080,
                    "long_side": 1920
                }
            },
            uuid=uuid4()
        )
        resp = queue.enqueue(task)
        logger.info(f"  任务 {i+1}: task_id={resp.task_id}, queue_size={resp.queue_size}")

    logger.info("=== 测试完成 ===")

if __name__ == "__main__":
    main()
