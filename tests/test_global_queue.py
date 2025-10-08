#!/usr/bin/env python3
"""
测试 GlobalMsgQueue 的基本功能
"""
from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage
from uuid import uuid4
from loguru import logger
import time

def main():
    logger.info("=== 测试 GlobalMsgQueue ===")

    # 1. 初始化 GlobalMsgQueue
    logger.info("1. 初始化 GlobalMsgQueue")
    queue = SwarmPilotGlobalMsgQueue()

    # 2. 加载 Task Instance
    logger.info("2. 加载 Task Instance")
    queue.load_task_instance_from_config("task_instances.yaml")

    # 等待模型完全启动
    logger.info("等待 5 秒让模型完全启动...")
    time.sleep(5)

    # 3. 更新队列信息
    logger.info("3. 更新队列信息")
    queue.update_queues()

    logger.info(f"发现 {len(queue.queues)} 个模型队列")
    for model_name, pq in queue.queues.items():
        logger.info(f"  - 模型: {model_name}, 队列大小: {pq.qsize()}")

    # 4. 测试任务分发
    logger.info("4. 测试任务分发")

    # 创建一个测试任务
    test_task = GlobalRequestMessage(
        model_id="easyocr",
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

    # 5. 再次更新队列查看变化
    logger.info("5. 再次更新队列查看变化")
    queue.update_queues()

    for model_name, pq in queue.queues.items():
        logger.info(f"  - 模型: {model_name}, 队列大小: {pq.qsize()}")
        # 查看队列中的详细信息
        temp_list = []
        while not pq.empty():
            temp_list.append(pq.get())
        for q_obj in temp_list:
            logger.info(
                f"    Port: {q_obj.port}, Expected: {q_obj.expected_ms:.2f}ms, "
                f"Error: {q_obj.error_ms:.2f}ms, Length: {q_obj.length}"
            )
            pq.put(q_obj)  # 放回队列

    logger.info("=== 测试完成 ===")

if __name__ == "__main__":
    main()
